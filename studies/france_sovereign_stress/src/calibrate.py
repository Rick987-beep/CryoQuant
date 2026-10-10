"""DV01 / carry / vol calibration and live P&L reconciliation (Phase 2)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.instruments import BOND_FUTURES, FOAT


YIELD_COL = {"FOAT": "oat10", "FGBL": "bund10"}
QUARTER_BDAYS = 63  # carry amortisation horizon used in v5


def _weekdays(df: pd.DataFrame) -> pd.DataFrame:
    out = df[df.index.dayofweek < 5]
    return out[~out.index.duplicated(keep="last")].sort_index()


@dataclass(frozen=True)
class FutCalib:
    """Futures €/bp, duration, carry from Eurex settles vs CNBC yields (v5 method)."""

    eur_per_bp: dict[str, float]
    duration: dict[str, float]
    carry_bp_per_day: dict[str, float]
    corr_price_yield: dict[str, float]
    mean_price: dict[str, float]
    calendar_points: dict[str, float]
    hedge_ratio: float
    days: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VolCalib:
    """Daily spread / Bund vol and correlation over a trailing window."""

    sig_s: float
    sig_b: float
    rho: float
    window: int
    n_obs: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StockBeta:
    beta_s: float
    beta_b: float
    idio: float
    r2: float


@dataclass(frozen=True)
class LivePnLCheck:
    """Short FOAT / long FGBL on settlement path."""

    start: str
    end: str
    foat_n: int
    fgbl_n: int
    foat_start: float
    foat_end: float
    fgbl_start: float
    fgbl_end: float
    spread_start_bp: float
    spread_end_bp: float
    spread_change_bp: float
    pnl_eur: float
    target_eur: float
    pnl_ok: bool
    eur_per_bp_realized: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calibrate_futures(
    settles: pd.DataFrame,
    yields: pd.DataFrame,
) -> FutCalib:
    """v5 FutCalib: regress Δsettle on Δyield (bp); carry from mean front−next calendar."""
    es = settles.copy()
    es.index = pd.DatetimeIndex(es.index).tz_localize(None).normalize()
    y = _weekdays(yields.copy())
    y.index = pd.DatetimeIndex(y.index).tz_localize(None).normalize()
    df = es.join(y, how="inner")
    if len(df) < 5:
        raise ValueError(f"need ≥5 overlapping settle/yield days; got {len(df)}")
    d = df.diff().dropna()

    eur: dict[str, float] = {}
    dur: dict[str, float] = {}
    carry: dict[str, float] = {}
    corr: dict[str, float] = {}
    mean_px: dict[str, float] = {}
    calendars: dict[str, float] = {}

    for code, yld in YIELD_COL.items():
        front = f"{code}_front"
        next_ = f"{code}_next"
        slope = float(np.polyfit(d[yld] * 100.0, d[front], 1)[0])  # points per bp
        mean_p = float(df[front].mean())
        eur[code] = float(-slope * BOND_FUTURES[code].multiplier)
        dur[code] = float(-slope * 1e4 / mean_p)
        corr[code] = float(np.corrcoef(d[yld], d[front])[0, 1])
        calendar = float((df[front] - df[next_]).mean())
        calendars[code] = calendar
        # calendar (price pts) → bp/day via €/bp and ~one quarter of business days
        carry[code] = calendar * BOND_FUTURES[code].multiplier / eur[code] / QUARTER_BDAYS
        mean_px[code] = mean_p

    hedge = eur["FOAT"] / eur["FGBL"]
    return FutCalib(
        eur_per_bp=eur,
        duration=dur,
        carry_bp_per_day=carry,
        corr_price_yield=corr,
        mean_price=mean_px,
        calendar_points=calendars,
        hedge_ratio=float(hedge),
        days=len(df),
    )


def eur_per_bp_from_duration(duration: float, price: float) -> float:
    """Second method: €/bp = duration × price × €1,000 / 10,000 = duration × price / 10.

    Same algebra as the regression when ``duration`` is the regression-implied figure;
    also used with an assumed duration for an independent rough check.
    """
    return float(duration * price / 10.0)


def duration_cross_check(fc: FutCalib) -> dict[str, Any]:
    """Compare regression €/bp to duration×price/10 (identity) and to D=8.0×last-mean proxy."""
    out: dict[str, Any] = {}
    for code in ("FOAT", "FGBL"):
        identity = eur_per_bp_from_duration(fc.duration[code], fc.mean_price[code])
        assumed = eur_per_bp_from_duration(8.0, fc.mean_price[code])
        out[code] = {
            "regression_eur_per_bp": fc.eur_per_bp[code],
            "identity_dur_times_price_over_10": identity,
            "identity_diff": identity - fc.eur_per_bp[code],
            "assumed_D8_eur_per_bp": assumed,
            "assumed_D8_vs_regression_pct": (assumed / fc.eur_per_bp[code] - 1.0) * 100.0,
        }
    return out


def calibrate_vol(yields: pd.DataFrame, *, window: int = 126) -> VolCalib:
    y = _weekdays(yields)
    d = pd.DataFrame(
        {
            "ds": y["spread_bp"].diff(),
            "db": y["bund10"].diff() * 100.0,
        }
    ).dropna()
    recent = d.iloc[-window:]
    return VolCalib(
        sig_s=float(recent["ds"].std()),
        sig_b=float(recent["db"].std()),
        rho=float(recent["ds"].corr(recent["db"])),
        window=window,
        n_obs=len(recent),
    )


def stock_betas(
    stocks: pd.DataFrame,
    yields: pd.DataFrame,
    *,
    vol_window: int = 126,
    tickers: list[str] | None = None,
) -> dict[str, StockBeta]:
    """OLS of daily log return on Δspread_bp and ΔBund_bp (v5)."""
    y = _weekdays(yields)
    d = pd.DataFrame(
        {
            "ds": y["spread_bp"].diff(),
            "db": y["bund10"].diff() * 100.0,
        }
    ).dropna()
    px = stocks.copy()
    px.index = pd.DatetimeIndex(px.index).tz_localize(None).normalize()
    r = np.log(px).diff()
    cols = tickers or list(px.columns)
    out: dict[str, StockBeta] = {}
    for c in cols:
        if c not in r.columns:
            continue
        df = pd.concat([r[c], d], axis=1, join="inner").dropna()
        if len(df) < vol_window + 5:
            continue
        x = np.column_stack([np.ones(len(df)), df["ds"].to_numpy(), df["db"].to_numpy()])
        yv = df[c].to_numpy()
        b = np.linalg.lstsq(x, yv, rcond=None)[0]
        e = pd.Series(yv - x @ b, index=df.index)
        out[c] = StockBeta(
            beta_s=float(b[1]),
            beta_b=float(b[2]),
            idio=float(e.iloc[-vol_window:].std()),
            r2=float(1.0 - e.var() / pd.Series(yv).var(ddof=1)),
        )
    return out


def live_spread_pnl(
    settles: pd.DataFrame,
    yields: pd.DataFrame,
    *,
    start: str = "2026-09-11",
    end: str = "2026-10-08",
    foat_n: int = 3,
    fgbl_n: int = 3,
    target_eur: float = 11_490.0,
    tol_eur: float = 0.5,
) -> LivePnLCheck:
    """Mark-to-settlement P&L of short FOAT / long FGBL (integer contracts, no costs)."""
    es = settles.copy()
    es.index = pd.DatetimeIndex(es.index).tz_localize(None).normalize()
    y = yields.copy()
    y.index = pd.DatetimeIndex(y.index).tz_localize(None).normalize()

    a = es.loc[pd.Timestamp(start)]
    b = es.loc[pd.Timestamp(end)]
    foat0, foat1 = float(a["FOAT_front"]), float(b["FOAT_front"])
    fgbl0, fgbl1 = float(a["FGBL_front"]), float(b["FGBL_front"])
    mult = FOAT.multiplier
    # short FOAT, long FGBL
    pnl = -foat_n * (foat1 - foat0) * mult + fgbl_n * (fgbl1 - fgbl0) * mult

    s0 = float(y.loc[pd.Timestamp(start), "spread_bp"])
    s1 = float(y.loc[pd.Timestamp(end), "spread_bp"])
    ds = s1 - s0
    return LivePnLCheck(
        start=start,
        end=end,
        foat_n=foat_n,
        fgbl_n=fgbl_n,
        foat_start=foat0,
        foat_end=foat1,
        fgbl_start=fgbl0,
        fgbl_end=fgbl1,
        spread_start_bp=s0,
        spread_end_bp=s1,
        spread_change_bp=ds,
        pnl_eur=float(pnl),
        target_eur=target_eur,
        pnl_ok=abs(pnl - target_eur) <= tol_eur,
        eur_per_bp_realized=float(pnl / ds) if abs(ds) > 1e-9 else float("nan"),
    )


def reconcile_v5(
    fc: FutCalib,
    vol: VolCalib,
    pnl: LivePnLCheck,
    *,
    v5_eur: dict[str, float] | None = None,
    v5_vol: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compare against HANDOVER / v5 snapshot targets."""
    v5_eur = v5_eur or {"FOAT": 87.58, "FGBL": 96.57}
    v5_vol = v5_vol or {"sig_s": 3.18, "sig_b": 3.95, "rho": 0.14, "hedge": 0.907}
    return {
        "eur_per_bp": {
            code: {
                "v6": fc.eur_per_bp[code],
                "v5": v5_eur[code],
                "diff": fc.eur_per_bp[code] - v5_eur[code],
            }
            for code in ("FOAT", "FGBL")
        },
        "hedge_ratio": {"v6": fc.hedge_ratio, "v5": v5_vol["hedge"], "diff": fc.hedge_ratio - v5_vol["hedge"]},
        "vol": {
            "sig_s": {"v6": vol.sig_s, "v5": v5_vol["sig_s"], "diff": vol.sig_s - v5_vol["sig_s"]},
            "sig_b": {"v6": vol.sig_b, "v5": v5_vol["sig_b"], "diff": vol.sig_b - v5_vol["sig_b"]},
            "rho": {"v6": vol.rho, "v5": v5_vol["rho"], "diff": vol.rho - v5_vol["rho"]},
        },
        "live_pnl": {
            "v6": pnl.pnl_eur,
            "v5_target": pnl.target_eur,
            "ok": pnl.pnl_ok,
            "spread_change_bp": pnl.spread_change_bp,
        },
    }
