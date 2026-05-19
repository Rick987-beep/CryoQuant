"""Tier-2 FeatureBuilder protocol and concrete implementations.

FeatureBuilder protocol::

    class FeatureBuilder(Protocol):
        id: str
        version: str
        def build(self, frames: dict) -> pd.DataFrame: ...

DatasetRef is a (Symbol, tf) pair used as the frames dict key.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd

from cryocore.instruments import Symbol
from cryoquant.features import primitives as P
from cryoquant.features.store import cached


@dataclass(frozen=True)
class DatasetRef:
    symbol: Symbol
    tf: str

    def __str__(self) -> str:
        return f"{self.symbol}@{self.tf}"


class FeatureBuilder(Protocol):
    id: str
    version: str

    def build(self, frames: dict[DatasetRef, pd.DataFrame]) -> pd.DataFrame: ...


# ---------------------------------------------------------------------------
# SpotFeatures — technical features for 1h spot bars
# ---------------------------------------------------------------------------

# Config constants (match the original research script)
_BB_LEN = 20
_BB_MULT = 2.0
_EMA_SHORT = 24    # 24h EMA
_EMA_LONG = 168    # 7-day EMA
_RV_BARS = 24
_RV_RANK_BARS = 720   # 30 days × 24h
_VOL_Z_BARS = 24
_RANGE_BARS = 24


class SpotFeatures:
    """Technical feature set for 1h spot bars.

    Expects a single DatasetRef for BTCUSDT (or equivalent) 1h in the frames dict.

    Output columns::

        ret_1h, ret_4h, ret_1d, accel_1h,
        close_vs_ema24, close_vs_ema168,
        rv_24h, rv_rank, rv_trend,
        bb_width, vol_z, range_ratio,
        hour_utc, day_of_week,
        close, high, low, volume   (raw OHLCV for labelling)
    """

    id = "spot_features"
    version = "1"

    @cached
    def build(self, frames: dict[DatasetRef, pd.DataFrame]) -> pd.DataFrame:
        # Expect exactly one 1h frame
        ref = next(iter(frames))
        df1h = frames[ref]
        return _compute_spot_features(df1h)


def _compute_spot_features(df1h: pd.DataFrame) -> pd.DataFrame:
    """Pure function used by SpotFeatures and tests."""
    close  = df1h["close"]
    high   = df1h["high"]
    low    = df1h["low"]
    volume = df1h["volume"]

    # 1h momentum
    ret_1h   = close.pct_change() * 100
    accel_1h = ret_1h - ret_1h.shift(1)

    # 4h momentum (closed-bar-safe HTF align)
    df4h       = P.resample(df1h, "4h")
    ret_4h_htf = df4h["close"].pct_change() * 100
    ret_4h_htf.name = "ret_4h"
    ret_4h     = P.htf_align(df1h, ret_4h_htf, htf="4h")

    # 1d momentum
    df1d       = P.resample(df1h, "1d")
    ret_1d_htf = df1d["close"].pct_change() * 100
    ret_1d_htf.name = "ret_1d"
    ret_1d     = P.htf_align(df1h, ret_1d_htf, htf="1d")

    # EMA distances
    ema24  = P.ema(close, _EMA_SHORT)
    ema168 = P.ema(close, _EMA_LONG)
    close_vs_ema24  = (close / ema24  - 1) * 100
    close_vs_ema168 = (close / ema168 - 1) * 100

    # Realised vol
    rv_24h = P.realised_vol(close, _RV_BARS)
    rv_rank = P.rv_rank(close, _RV_BARS, _RV_RANK_BARS)
    rv_trend = rv_24h - rv_24h.shift(24)

    # BB width
    bbw = P.bb_width(close, _BB_LEN, _BB_MULT)

    # Volume z-score
    vol_z_s = P.vol_z(volume, _VOL_Z_BARS)

    # Range ratio
    range_ratio_s = P.range_ratio(df1h, _RANGE_BARS)

    # Session (timestamp-based, no shift needed)
    hour_utc    = pd.Series(df1h.index.hour,      index=df1h.index, dtype="int8")
    day_of_week = pd.Series(df1h.index.dayofweek, index=df1h.index, dtype="int8")

    # All price-derived features shifted by 1 bar so feature[T] uses only
    # information available at T (bar T's close is known at T+1h).
    return pd.DataFrame({
        "ret_1h":          ret_1h.shift(1),
        "ret_4h":          ret_4h.shift(1),
        "ret_1d":          ret_1d.shift(1),
        "accel_1h":        accel_1h.shift(1),
        "close_vs_ema24":  close_vs_ema24.shift(1),
        "close_vs_ema168": close_vs_ema168.shift(1),
        "rv_24h":          rv_24h.shift(1),
        "rv_rank":         rv_rank.shift(1),
        "rv_trend":        rv_trend.shift(1),
        "bb_width":        bbw.shift(1),
        "vol_z":           vol_z_s.shift(1),
        "range_ratio":     range_ratio_s.shift(1),
        "hour_utc":        hour_utc,
        "day_of_week":     day_of_week,
        "close":           close,
        "high":            high,
        "low":             low,
        "volume":          volume,
    })


# ---------------------------------------------------------------------------
# DailyEmaCrossFeatures — EMA 7/21 crossover on daily bars
# ---------------------------------------------------------------------------

class DailyEmaCrossFeatures:
    """EMA 7/21 crossover feature set for daily bars.

    Expects a single DatasetRef for BTCUSDT (or equivalent) 1d in the frames dict.

    Output columns::

        ema_7, ema_21,          (shifted 1 bar: value known at bar close)
        cross_up, cross_down,   (True on the bar where the cross occurred)
        open, high, low, close, volume  (raw OHLCV passthrough)
    """

    id = "daily_ema_cross"
    version = "1"

    @cached
    def build(self, frames: dict[DatasetRef, pd.DataFrame]) -> pd.DataFrame:
        ref = next(iter(frames))
        df1d = frames[ref]
        return _compute_ema_cross_features(df1d)


def _compute_ema_cross_features(df: pd.DataFrame) -> pd.DataFrame:
    """Pure function used by DailyEmaCrossFeatures and tests."""
    close = df["close"]

    ema_7  = P.ema(close, 7)
    ema_21 = P.ema(close, 21)

    # Cross detection at bar T: fast crossed slow between T-1 and T
    cross_up   = (ema_7 > ema_21) & (ema_7.shift(1) <= ema_21.shift(1))
    cross_down = (ema_7 < ema_21) & (ema_7.shift(1) >= ema_21.shift(1))

    # Shift by 1 bar so that feature[T] reflects information from bar T-1.
    # At bar T the trader knows bar T-1 closed with a cross → enters at T's open.
    return pd.DataFrame({
        "ema_7":      ema_7.shift(1),
        "ema_21":     ema_21.shift(1),
        "cross_up":   cross_up.shift(1),
        "cross_down": cross_down.shift(1),
        "open":       df["open"],
        "high":       df["high"],
        "low":        df["low"],
        "close":      close,
        "volume":     df["volume"],
    })
