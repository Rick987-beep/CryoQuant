"""Phase 2e — Regime and path-dependent NAV analysis vs BTCUSD daily curve."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from .nav_sim import CANDIDATE_SPECS, NavResult, simulate_book

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"

# Calendar regimes aligned to observed BTC path in chain window (2025-04-11 → 2026-06-07).
DEFAULT_REGIMES: dict[str, tuple[str, str]] = {
    "full_window": ("2025-04-11", "2026-06-07"),
    "early_rally": ("2025-04-11", "2025-09-30"),   # BTC +37% into Sep peak area
    "oct_decline": ("2025-10-01", "2026-06-07"),   # BTC −47% from Oct start to end
    "feb_2026_crash": ("2026-02-01", "2026-02-28"),  # worst single month in window
}


@dataclass(frozen=True)
class PeriodMetrics:
    start: str
    end: str
    days: int
    nav_return: float
    btc_return: float
    excess_return: float
    nav_max_dd: float
    btc_max_dd: float
    upside_capture: float | None
    downside_capture: float | None
    nav_end: float
    btc_end: float


def load_nav_frame(candidate: str, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    path = data_dir / f"nav_{candidate}.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    return df[["nav", "btc"]].sort_index()


def period_metrics(
    nav: pd.Series,
    btc: pd.Series,
    start: str | date,
    end: str | date,
) -> PeriodMetrics | None:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    n = nav.loc[start_ts:end_ts]
    b = btc.loc[start_ts:end_ts]
    if len(n) < 2:
        return None

    nav_ret = float(n.iloc[-1] / n.iloc[0] - 1)
    btc_ret = float(b.iloc[-1] / b.iloc[0] - 1)
    nav_dd = float((n / n.cummax() - 1).min())
    btc_dd = float((b / b.cummax() - 1).min())

    nav_d = n.pct_change().dropna()
    btc_d = b.pct_change().dropna()
    aligned = pd.concat([nav_d, btc_d], axis=1, keys=["nav", "btc"], sort=False).dropna()

    cap_up = cap_dn = None
    up = aligned["btc"] > 0
    dn = aligned["btc"] < 0
    if up.any() and aligned.loc[up, "btc"].sum() != 0:
        cap_up = float(aligned.loc[up, "nav"].sum() / aligned.loc[up, "btc"].sum())
    if dn.any() and aligned.loc[dn, "btc"].sum() != 0:
        cap_dn = float(aligned.loc[dn, "nav"].sum() / aligned.loc[dn, "btc"].sum())

    return PeriodMetrics(
        start=str(n.index[0].date()),
        end=str(n.index[-1].date()),
        days=len(n),
        nav_return=nav_ret,
        btc_return=btc_ret,
        excess_return=nav_ret - btc_ret,
        nav_max_dd=nav_dd,
        btc_max_dd=btc_dd,
        upside_capture=cap_up,
        downside_capture=cap_dn,
        nav_end=float(n.iloc[-1]),
        btc_end=float(b.iloc[-1]),
    )


def monthly_excess_table(nav: pd.Series, btc: pd.Series) -> pd.DataFrame:
    """Month-end returns and nav−btc excess (percentage points)."""
    nav_m = nav.resample("ME").last().pct_change()
    btc_m = btc.resample("ME").last().pct_change()
    out = pd.DataFrame({
        "nav_return": nav_m,
        "btc_return": btc_m,
        "excess_pp": (nav_m - btc_m) * 100,
    }).dropna()
    out.index = out.index.strftime("%Y-%m")
    return out


def build_regime_report(
    candidates: list[str] | None = None,
    *,
    regimes: dict[str, tuple[str, str]] | None = None,
    data_dir: Path = DATA_DIR,
    results: dict[str, NavResult] | None = None,
) -> dict:
    """Path-dependent report: full curve segmented by regime, not endpoint-only."""
    candidates = candidates or list(CANDIDATE_SPECS.keys())
    regimes = regimes or DEFAULT_REGIMES

    report: dict = {"regimes": {}, "candidates": {}, "btc_path": {}}

    # BTC path reference from first available candidate
    ref_key = candidates[0]
    ref_df = (
        results[ref_key].nav.to_frame(name="nav").join(results[ref_key].btc.rename("btc"))
        if results and ref_key in results
        else load_nav_frame(ref_key, data_dir)
    )
    btc = ref_df["btc"]
    for regime_name, (a, b) in regimes.items():
        m = period_metrics(btc, btc, a, b)
        if m:
            report["btc_path"][regime_name] = {
                "btc_return": m.btc_return,
                "btc_max_dd": m.btc_max_dd,
                "start": m.start,
                "end": m.end,
            }

    for key in candidates:
        if results and key in results:
            df = results[key].nav.to_frame(name="nav").join(results[key].btc.rename("btc"))
        else:
            df = load_nav_frame(key, data_dir)

        cand: dict = {"monthly": {}, "regimes": {}}
        monthly = monthly_excess_table(df["nav"], df["btc"])
        cand["monthly"] = {
            row.Index: {
                "nav_return": float(row.nav_return),
                "btc_return": float(row.btc_return),
                "excess_pp": float(row.excess_pp),
            }
            for row in monthly.itertuples()
        }

        for regime_name, (a, b) in regimes.items():
            m = period_metrics(df["nav"], df["btc"], a, b)
            if m is None:
                continue
            cand["regimes"][regime_name] = {
                "nav_return": m.nav_return,
                "btc_return": m.btc_return,
                "excess_return": m.excess_return,
                "nav_max_dd": m.nav_max_dd,
                "btc_max_dd": m.btc_max_dd,
                "upside_capture": m.upside_capture,
                "downside_capture": m.downside_capture,
                "nav_end": m.nav_end,
                "btc_end": m.btc_end,
                "days": m.days,
            }

        report["candidates"][key] = cand

    return report


def write_regime_report(
    path: Path | None = None,
    *,
    results: dict[str, NavResult] | None = None,
) -> dict:
    path = path or DATA_DIR / "phase2_regime_report.json"
    report = build_regime_report(results=results)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("Wrote regime report → %s", path)
    return report


def print_regime_summary(report: dict) -> None:
    print("\n" + "=" * 78)
    print("REGIME ANALYSIS — daily NAV path vs BTCUSD (not endpoint-only)")
    print("=" * 78)

    for regime in ("early_rally", "oct_decline", "feb_2026_crash", "full_window"):
        if regime not in report["candidates"].get(next(iter(report["candidates"])), {}).get("regimes", {}):
            continue
        btc_info = report["btc_path"].get(regime, {})
        print(f"\n── {regime} ({btc_info.get('start')} → {btc_info.get('end')}) "
              f"BTC {btc_info.get('btc_return', 0)*100:+.1f}% ──")

        rows = []
        for key, cand in report["candidates"].items():
            r = cand["regimes"][regime]
            rows.append((key, r))
        rows.sort(key=lambda x: x[1]["excess_return"], reverse=True)

        for key, r in rows:
            up = r["upside_capture"]
            up_s = f"{up:.2f}" if up is not None else "n/a"
            print(
                f"  {key:14s}  nav {r['nav_return']*100:+6.1f}%  "
                f"btc {r['btc_return']*100:+6.1f}%  "
                f"excess {r['excess_return']*100:+6.1f}%  "
                f"dd {r['nav_max_dd']*100:5.1f}%  up_cap={up_s}"
            )
    print("=" * 78)
