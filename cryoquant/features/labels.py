"""Forward-return and distributional labelers.

All labelers compute **forward-looking** targets and must never be used as model
features — only as training targets.

Conventions (daily bars):
  - ``horizon_bars=H`` uses prices over ``(t+1 .. t+H]``; last H rows are NaN.
  - Forward RV annualises with ``sqrt(252)``; levels are in percent (match DVOL).
  - H=1 RV uses ``|r_{t+1}|`` because ``rolling(1).std()`` is undefined.
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

Direction = Literal["up", "down", "magnitude"]
ExceedanceSide = Literal["call", "put"]

DAILY_ANNUALISE = 252


def _nan_tail(series: pd.Series, horizon: int) -> pd.Series:
    out = series.copy()
    if horizon > 0 and len(out):
        out.iloc[-horizon:] = np.nan
    return out


def _daily_log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1))


def _forward_close(close: pd.Series, horizon: int) -> pd.Series:
    return close.shift(-horizon)


class ForwardReturnLabeler:
    """Label each bar based on forward-horizon price movement.

    Args:
        horizon_h:   Look-forward window in bars.
        threshold:   Price move threshold in percent (e.g. 2.5 = 2.5%).
        direction:   "up"  → fwd max high >= close*(1+thr/100)
                     "down" → fwd min low <= close*(1-thr/100)
                     "magnitude" → either direction.
    """

    def __init__(self, horizon_h: int, threshold: float, direction: Direction = "magnitude"):
        if horizon_h < 1:
            raise ValueError("horizon_h must be >= 1")
        if threshold <= 0:
            raise ValueError("threshold must be > 0")
        self.horizon_h = horizon_h
        self.threshold = threshold
        self.direction = direction

    @property
    def column_name(self) -> str:
        t = f"{self.threshold:.1f}".replace(".", "p")
        return f"{self.direction}_win_t{t}_h{self.horizon_h}"

    def column_name_volscaled(self) -> str:
        return f"{self.direction}_win_volscaled_h{self.horizon_h}"

    def apply(
        self,
        df: pd.DataFrame,
        *,
        threshold_pct: float | pd.Series | None = None,
    ) -> pd.Series:
        """Return a float label Series (0/1/NaN) aligned to df.index.

        Pass ``threshold_pct`` (percent units) to override the constructor threshold
        per bar — used for vol-scaled directional labels.
        """
        close = df["close"]
        high = df["high"]
        low = df["low"]
        h = self.horizon_h
        thr_pct = threshold_pct if threshold_pct is not None else self.threshold
        thr = thr_pct / 100.0

        fwd_max_high = high.rolling(h, min_periods=h).max().shift(-h)
        fwd_min_low = low.rolling(h, min_periods=h).min().shift(-h)

        move_up = (fwd_max_high - close) / close
        move_dn = (close - fwd_min_low) / close

        if self.direction == "up":
            label = move_up >= thr
        elif self.direction == "down":
            label = move_dn >= thr
        else:
            label = (move_up >= thr) | (move_dn >= thr)

        result = label.astype(float)
        out = _nan_tail(result, h)
        if threshold_pct is not None and isinstance(threshold_pct, pd.Series):
            name = self.column_name_volscaled()
        else:
            name = self.column_name
        return out.rename(name)


class LogReturnLabeler:
    """y = ln(close[t+H] / close[t])."""

    def __init__(self, horizon_bars: int):
        if horizon_bars < 1:
            raise ValueError("horizon_bars must be >= 1")
        self.horizon_bars = horizon_bars

    @property
    def column_name(self) -> str:
        return f"log_return_h{self.horizon_bars}"

    def apply(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        fwd = _forward_close(close, self.horizon_bars)
        out = np.log(fwd / close)
        return _nan_tail(out, self.horizon_bars).rename(self.column_name)


class RealizedVolLabeler:
    """Forward realized vol: std(daily log returns over (t+1..t+H]) annualised (%)."""

    def __init__(self, horizon_bars: int, annualise_factor: float = DAILY_ANNUALISE):
        if horizon_bars < 1:
            raise ValueError("horizon_bars must be >= 1")
        self.horizon_bars = horizon_bars
        self.annualise_factor = annualise_factor

    @property
    def column_name(self) -> str:
        return f"fwd_rv_h{self.horizon_bars}"

    def apply(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        log_ret = _daily_log_returns(close)
        h = self.horizon_bars
        if h == 1:
            # One forward daily return: |r_{t+1}| scaled to annualised % (rolling std of n=1 is NaN).
            fwd_log = np.log(_forward_close(close, 1) / close)
            out = fwd_log.abs() * np.sqrt(self.annualise_factor) * 100.0
        else:
            fwd_std = log_ret.rolling(h, min_periods=h).std().shift(-h)
            out = fwd_std * np.sqrt(self.annualise_factor) * 100.0
        return _nan_tail(out, h).rename(self.column_name)


class ExceedanceLabeler:
    """Terminal exceedance for European cash settlement (Goal 2).

    Call: y=1 iff close[t+H] > close[t] * exp(threshold_log_return).
    Put:  y=1 iff close[t+H] < close[t] * exp(threshold_log_return)
          (threshold_log_return is typically negative for OTM puts).
    """

    def __init__(
        self,
        horizon_bars: int,
        side: ExceedanceSide,
        *,
        delta: float | None = None,
        threshold_log_return: float | None = None,
    ):
        if horizon_bars < 1:
            raise ValueError("horizon_bars must be >= 1")
        if side not in ("call", "put"):
            raise ValueError("side must be 'call' or 'put'")
        self.horizon_bars = horizon_bars
        self.side = side
        self.delta = delta
        self.threshold_log_return = threshold_log_return

    @property
    def column_name(self) -> str:
        if self.delta is not None:
            d = f"{self.delta:.2f}".replace(".", "p")
            return f"exceedance_{self.side}_d{d}_h{self.horizon_bars}"
        return f"exceedance_{self.side}_h{self.horizon_bars}"

    def apply(
        self,
        df: pd.DataFrame,
        threshold_log_return: float | pd.Series | None = None,
    ) -> pd.Series:
        thr = threshold_log_return
        if thr is None:
            thr = self.threshold_log_return
        if thr is None:
            raise ValueError("threshold_log_return required")

        close = df["close"]
        fwd_close = _forward_close(close, self.horizon_bars)
        strike = close * np.exp(thr)

        if self.side == "call":
            label = fwd_close > strike
        else:
            label = fwd_close < strike

        out = label.astype(float)
        return _nan_tail(out, self.horizon_bars).rename(self.column_name)


class VRPRealizationLabeler:
    """Variance-risk-premium realization: IV at t minus forward realized vol (%).

    y = IV_t - RV_{t+1..t+H}.  Positive → implied vol rich vs subsequent realization.
    """

    def __init__(self, horizon_bars: int, annualise_factor: float = DAILY_ANNUALISE):
        if horizon_bars < 1:
            raise ValueError("horizon_bars must be >= 1")
        self.horizon_bars = horizon_bars
        self.annualise_factor = annualise_factor

    @property
    def column_name(self) -> str:
        return f"vrp_realized_h{self.horizon_bars}"

    def apply(self, df: pd.DataFrame, iv: pd.Series) -> pd.Series:
        rv_labeler = RealizedVolLabeler(self.horizon_bars, self.annualise_factor)
        fwd_rv = rv_labeler.apply(df)
        iv_aligned = iv.reindex(df.index)
        out = iv_aligned - fwd_rv
        return _nan_tail(out, self.horizon_bars).rename(self.column_name)


class VolScaledThreshold:
    """Per-bar directional threshold (%): k * daily_vol% * sqrt(H)."""

    @staticmethod
    def apply(
        close: pd.Series,
        horizon_bars: int,
        *,
        window: int = 5,
        k: float = 1.0,
    ) -> pd.Series:
        log_ret = _daily_log_returns(close)
        daily_vol_pct = log_ret.rolling(window, min_periods=window).std() * 100.0
        return k * daily_vol_pct * np.sqrt(horizon_bars)


def causal_forward_return_quantile(
    close: pd.Series,
    horizon_bars: int,
    quantile: float,
    lookback: int,
    *,
    min_periods: int | None = None,
) -> pd.Series:
    """Rolling quantile of **past** forward log returns (causal strike calibration).

    At bar *t* uses forward returns from bars < *t* only (``shift(1)`` on the
    forward-return series).
    """
    if not 0.0 < quantile < 1.0:
        raise ValueError("quantile must be in (0, 1)")
    mp = min_periods if min_periods is not None else max(lookback // 4, 20)
    fwd = np.log(_forward_close(close, horizon_bars) / close)
    return fwd.shift(1).rolling(lookback, min_periods=mp).quantile(quantile)
