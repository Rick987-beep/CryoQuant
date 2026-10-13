"""Ground option vol evolution in realised yield history.

Fits realised normal (bp/day) vol of the OAT–Bund spread against the spread
level and recent change, using CNBC daily + FRED monthly history. Caps the
fitted vol at the maximum observed. Flat-IV (today's surface held at constant
moneyness) is the conservative alternative — never invent a VOL_UP rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.calibrate import VolCalib
from src.options import Skew


STRESS_WINDOWS = [
    ("euro_crisis_2011", "2011-07-01", "2012-06-30"),
    ("france_snap_2024", "2024-06-01", "2024-08-31"),
    ("france_stress_2026", "2026-08-15", "2026-10-12"),
]


@dataclass(frozen=True)
class VolFit:
    """Maps spread widening to an ATM vol multiplier vs today's surface."""

    intercept: float
    coef_level: float
    coef_dlevel: float
    r2: float
    max_obs_mult: float
    max_obs_sig_bp: float
    base_sig_bp: float
    n_obs: int
    by_episode: dict[str, dict[str, float]]
    use_level: bool  # False → flat-IV (multiplier = 1)

    def atm_mult(self, ds_bp: float | np.ndarray, s0: float) -> np.ndarray:
        """Multiplier on today's ATM IV given cumulative spread change ``ds_bp``."""
        ds = np.asarray(ds_bp, dtype=float)
        if not self.use_level:
            return np.ones_like(ds, dtype=float)
        level = s0 + ds
        # Predicted daily bp vol → ratio to base.
        pred = self.intercept + self.coef_level * level + self.coef_dlevel * np.maximum(ds, 0.0)
        pred = np.maximum(pred, 0.5)  # bp/day floor
        mult = pred / max(self.base_sig_bp, 1e-6)
        return np.clip(mult, 0.7, self.max_obs_mult)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intercept": self.intercept,
            "coef_level": self.coef_level,
            "coef_dlevel": self.coef_dlevel,
            "r2": self.r2,
            "max_obs_mult": self.max_obs_mult,
            "max_obs_sig_bp": self.max_obs_sig_bp,
            "base_sig_bp": self.base_sig_bp,
            "n_obs": self.n_obs,
            "by_episode": self.by_episode,
            "use_level": self.use_level,
            "note": (
                "Fitted realised spread σ (bp/day, 21d rolling) on level + Δlevel. "
                "Multiplier capped at max observed / base. Flat-IV sets use_level=False."
            ),
        }


def _rolling_sig(s: pd.Series, window: int = 21) -> pd.Series:
    return s.diff().rolling(window).std()


def _episode_stats(sig: pd.Series, level: pd.Series, start: str, end: str) -> dict[str, float]:
    sl = slice(start, end)
    sub_s = sig.loc[sl].dropna()
    sub_l = level.loc[sl].dropna()
    if sub_s.empty:
        return {"n": 0}
    return {
        "n": int(len(sub_s)),
        "sig_mean": float(sub_s.mean()),
        "sig_max": float(sub_s.max()),
        "level_mean": float(sub_l.reindex(sub_s.index).mean()),
        "level_max": float(sub_l.reindex(sub_s.index).max()),
    }


def fit_vol_vs_spread(
    yields_daily: pd.DataFrame,
    fred_monthly: pd.DataFrame | None = None,
    *,
    vol: VolCalib | None = None,
    window: int = 21,
    flat: bool = False,
) -> VolFit:
    """OLS of 21d realised spread σ on spread level and 21d Δspread.

    FRED monthly (IRLTLT01FRM086S − IRLTLT01DEM086S style) extends the sample
    when present; monthly σ is converted to daily by /√21.
    """
    y = yields_daily.copy()
    y.index = pd.DatetimeIndex(y.index).tz_localize(None).normalize()
    level = y["spread_bp"].astype(float)
    sig = _rolling_sig(level, window)
    dlevel = level.diff(window)

    df = pd.DataFrame({"sig": sig, "level": level, "dlevel": dlevel}).dropna()
    # Clip extreme dlevel outliers from weekends/gaps.
    df = df[df["dlevel"].abs() < 80]

    episodes: dict[str, dict[str, float]] = {}
    for name, a, b in STRESS_WINDOWS:
        episodes[name] = _episode_stats(sig, level, a, b)

    fred_spr: pd.Series | None = None
    if fred_monthly is not None and not fred_monthly.empty:
        fm = fred_monthly.copy()
        fm.index = pd.DatetimeIndex(fm.index).tz_localize(None).normalize()
        # Expect columns like FR10Y, DE10Y or oat/bund aliases.
        cols = {c.lower(): c for c in fm.columns}
        fr = next((cols[k] for k in cols if "fr" in k or "oat" in k), None)
        de = next((cols[k] for k in cols if "de" in k or "bund" in k or "ger" in k), None)
        if fr and de:
            spr = (fm[fr] - fm[de]) * 100.0  # percent → bp if yields in %
            # Some FRED files already store bp; detect by magnitude.
            if spr.abs().median() > 500:
                spr = spr / 100.0
            fred_spr = spr
            m_sig = spr.diff().rolling(3).std() / np.sqrt(21)  # monthly → daily-ish
            m_lvl = spr
            m_dl = spr.diff(3)
            extra = pd.DataFrame({"sig": m_sig, "level": m_lvl, "dlevel": m_dl}).dropna()
            extra = extra[extra["dlevel"].abs() < 150]
            episodes["fred_monthly"] = {
                "n": int(len(extra)),
                "sig_mean": float(extra["sig"].mean()) if len(extra) else 0.0,
                "sig_max": float(extra["sig"].max()) if len(extra) else 0.0,
            }
            # Fill episode stats from FRED when CNBC daily does not cover them.
            for name, a, b in STRESS_WINDOWS:
                if episodes[name].get("n", 0) == 0:
                    episodes[name] = {
                        **_episode_stats(m_sig, m_lvl, a, b),
                        "source": "fred_monthly",
                    }
            df = pd.concat([df, extra], axis=0)

    base = float(vol.sig_s) if vol is not None else float(df["sig"].iloc[-60:].mean())
    max_sig = float(df["sig"].max()) if len(df) else base
    max_mult = max(1.0, max_sig / max(base, 1e-6))

    if flat or len(df) < 40:
        return VolFit(
            intercept=base,
            coef_level=0.0,
            coef_dlevel=0.0,
            r2=0.0,
            max_obs_mult=max_mult,
            max_obs_sig_bp=max_sig,
            base_sig_bp=base,
            n_obs=len(df),
            by_episode=episodes,
            use_level=False,
        )

    x = np.column_stack(
        [np.ones(len(df)), df["level"].to_numpy(), np.maximum(df["dlevel"].to_numpy(), 0.0)]
    )
    yv = df["sig"].to_numpy()
    beta, _, _, _ = np.linalg.lstsq(x, yv, rcond=None)
    resid = yv - x @ beta
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((yv - yv.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Only keep the level/Δ relation if it has positive R² and a sensible sign
    # (wider spreads → higher vol). Otherwise fall back to flat-IV.
    use = r2 > 0.05 and (beta[1] > 0 or beta[2] > 0)
    return VolFit(
        intercept=float(beta[0]),
        coef_level=float(beta[1]),
        coef_dlevel=float(beta[2]),
        r2=float(r2),
        max_obs_mult=float(max_mult),
        max_obs_sig_bp=max_sig,
        base_sig_bp=base,
        n_obs=len(df),
        by_episode=episodes,
        use_level=use,
    )


def flat_vol_fit(base: VolFit) -> VolFit:
    """Conservative sensitivity: hold today's surface (multiplier = 1)."""
    return VolFit(
        intercept=base.base_sig_bp,
        coef_level=0.0,
        coef_dlevel=0.0,
        r2=0.0,
        max_obs_mult=base.max_obs_mult,
        max_obs_sig_bp=base.max_obs_sig_bp,
        base_sig_bp=base.base_sig_bp,
        n_obs=base.n_obs,
        by_episode=base.by_episode,
        use_level=False,
    )


def scaled_atm(skew: Skew, mult: float | np.ndarray) -> float | np.ndarray:
    return skew.atm * np.asarray(mult, dtype=float)
