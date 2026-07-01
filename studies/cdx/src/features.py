"""Feature engineering for CDX.NA.IG analysis."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .paths import load_config


def is_roll_window(dates: pd.DatetimeIndex, *, months: tuple[int, ...] = (3, 9), day: int = 20, window: int = 2) -> pd.Series:
    """True within ±window calendar days of IMM roll (Mar/Sep 20)."""
    out = pd.Series(False, index=dates)
    for ts in dates:
        for month in months:
            roll = pd.Timestamp(year=ts.year, month=month, day=day, tz=dates.tz)
            if abs((ts.normalize() - roll.normalize()).days) <= window:
                out.loc[ts] = True
                break
    return out


def level_regime(spread_bps: pd.Series, cfg: dict | None = None) -> pd.Series:
    cfg = cfg or load_config()
    cuts = cfg["regimes"]["level"]
    s = spread_bps
    return pd.Series(
        np.select(
            [s < cuts["tight"], s < cuts["normal"], s < cuts["elevated"]],
            ["tight", "normal", "elevated"],
            default="stress",
        ),
        index=s.index,
        name="regime_level",
    )


def velocity_regime(pct_chg_1d: pd.Series, cfg: dict | None = None) -> pd.Series:
    """Nguyen-style buckets using expanding σ of 1d % change (decimal scale)."""
    cfg = cfg or load_config()
    sig = (pct_chg_1d / 100.0).expanding(min_periods=63).std()
    buckets = cfg["regimes"]["velocity_sigma"]
    return pd.Series(
        np.select(
            [sig < buckets["low"], sig < buckets["moderate"]],
            ["low", "moderate"],
            default="high",
        ),
        index=pct_chg_1d.index,
        name="regime_velocity",
    )


def build_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Derive spread, velocity, regime, and carry features."""
    cfg = load_config()
    day_count = cfg["cds_economics"]["day_count"]

    feat = panel[["spread_bps"]].copy()
    feat["d_spread_1d"] = feat["spread_bps"].diff()
    feat["pct_chg_1d"] = feat["spread_bps"].pct_change() * 100
    feat["pct_chg_3d"] = feat["spread_bps"].pct_change(3) * 100
    feat["level_pctile_expanding"] = feat["spread_bps"].expanding(min_periods=252).rank(pct=True)
    feat["regime_level"] = level_regime(feat["spread_bps"], cfg)
    feat["regime_velocity"] = velocity_regime(feat["pct_chg_1d"], cfg)
    feat["is_roll_window"] = is_roll_window(feat.index)
    feat["carry_daily_per_1m"] = -(feat["spread_bps"] / 10_000) / day_count
    return feat
