"""11b_option_universe.py — Option chain characterisation at signal fires.

For every signal fire in the Jan–May 2026 options window, load the actual
options chain and record available straddle legs across a (DTE × delta_target)
grid.  No Black-Scholes, no assumptions — all prices from real bid/ask data.

Grid:
  DTE          : 1, 2, 3, 4
  delta_target : 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40

For each (fire_timestamp, DTE, delta_target):
  • Find best-matching call and put (expiry = fire_date + DTE days)
  • Record actual_delta, actual_iv, ask_usd, bid_usd, spread_pct per leg
  • Compute straddle_ask, straddle_bid, straddle_spread_pct, straddle_pct_spot
  • Mark available = True when both legs pass quality filters

Filters:
  call_ask_usd >= 75   (per-leg minimum liquidity)
  put_ask_usd  >= 75
  spread_pct   <= 30%  (per leg)
  hours_to_expiry >= 4  (DTE-1 guard)

Sections
--------
  A   Availability grid   (% of fires where a valid straddle exists)
  B   Median straddle cost grid   (USD and % of spot)
  C   Median IV at entry   (by DTE × delta_target)
  D   Pullback vs vol_burst cost comparison   (same grids split by signal tier)
  E   IV vs rv_rank   (does our vol-regime gate predict premium cost?)

Outputs
-------
  11b_option_universe.csv  — one row per (signal_fire × DTE × delta_target)
"""
from __future__ import annotations

import sys, types, importlib.util
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO / "pineforge"))

# option_utils lives in research/intraday_options/
_OPT_UTILS_DIR = Path(__file__).resolve().parent.parent / "intraday_options"
sys.path.insert(0, str(_OPT_UTILS_DIR))
import option_utils as ou  # noqa: E402

# ── Import build_features / add_outcomes from 06 ─────────────────────────────
_06_path = Path(__file__).resolve().parent / "06_v2_spot_signals.py"
_spec    = importlib.util.spec_from_file_location("sig06", _06_path)
sig06    = types.ModuleType("sig06")
sig06.__file__ = str(_06_path)
sig06.__spec__ = _spec
_spec.loader.exec_module(sig06)  # type: ignore[union-attr]

build_features = sig06.build_features
add_outcomes   = sig06.add_outcomes
PRIMARY        = sig06.PRIMARY

import pineforge.data as pfdata

HERE = Path(__file__).resolve().parent

# ── Config ────────────────────────────────────────────────────────────────────
LOAD_FROM    = "2024-01-01"
OPT_START    = "2026-01-01"
OPT_END      = "2026-05-12"

DTE_TARGETS   = [1, 2, 3, 4]
DELTA_TARGETS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]

MIN_LEG_ASK_USD     = 75.0    # per-leg liquidity floor
MAX_SPREAD_PCT      = 30.0    # per-leg bid-ask spread ceiling
MIN_HOURS_TO_EXPIRY = 4.0     # DTE-1 guard: skip nearly-expired contracts


# ── Data loading ──────────────────────────────────────────────────────────────

@lru_cache(maxsize=60)
def _load_merged(date_str: str) -> pd.DataFrame | None:
    """Load + merge options+spot for one date. Cached per date."""
    try:
        df_opt  = ou.load_day(date_str)
        df_spot = ou.load_spot_day(date_str)
    except FileNotFoundError:
        return None

    df_opt  = df_opt.sort_values("timestamp").reset_index(drop=True)
    df_spot = (df_spot
               .sort_values("timestamp")[["timestamp", "close"]]
               .rename(columns={"close": "spot_usd"}))

    merged = pd.merge_asof(df_opt, df_spot, on="timestamp", direction="backward")
    spot   = merged["spot_usd"].values
    merged["bid_usd"]  = merged["bid_price"].values * spot
    merged["ask_usd"]  = merged["ask_price"].values * spot
    merged["mark_usd"] = merged["mark_price"].values * spot
    return merged


def _get_snapshot(merged: pd.DataFrame, target_ts_us: int) -> pd.DataFrame:
    """Return the options chain snapshot nearest to target_ts_us."""
    ts_vals = merged["timestamp"].unique()
    snap_ts = int(ts_vals[np.abs(ts_vals - target_ts_us).argmin()])
    return merged[merged["timestamp"] == snap_ts].copy()


def _find_straddle(
    snap: pd.DataFrame,
    expiry_code: str,
    delta_target: float,
    entry_ts_us: int,
) -> dict | None:
    """Find best-matching call+put at a given expiry and delta target.

    Returns a dict of leg and straddle stats, or None if matching fails.
    """
    exp_snap = snap[snap["expiry"] == expiry_code].copy()
    if exp_snap.empty:
        return None

    exp_snap["abs_delta"] = exp_snap["delta"].abs()
    calls = exp_snap[exp_snap["is_call"] == True]
    puts  = exp_snap[exp_snap["is_call"] == False]

    if calls.empty or puts.empty:
        return None

    # Best call: closest abs_delta to target — no tolerance cutoff, always use nearest
    call_diffs   = (calls["abs_delta"] - delta_target).abs()
    best_call_i  = int(call_diffs.values.argmin())
    call_row     = calls.iloc[best_call_i]
    call_delta_dist = float(call_diffs.iloc[best_call_i])

    # Best put: closest abs_delta to target
    put_diffs   = (puts["abs_delta"] - delta_target).abs()
    best_put_i  = int(put_diffs.values.argmin())
    put_row     = puts.iloc[best_put_i]
    put_delta_dist = float(put_diffs.iloc[best_put_i])

    # Require positive ask/bid on both legs
    if (float(call_row["ask_usd"]) <= 0 or float(put_row["ask_usd"]) <= 0 or
            float(call_row["bid_usd"]) <= 0 or float(put_row["bid_usd"]) <= 0):
        return None

    # Hours to expiry
    expiry_dt       = ou.parse_expiry(expiry_code)      # 08:00 UTC
    fire_dt         = datetime.fromtimestamp(entry_ts_us / 1e6, tz=timezone.utc)
    hours_to_expiry = (expiry_dt - fire_dt).total_seconds() / 3600

    call_ask  = float(call_row["ask_usd"])
    call_bid  = float(call_row["bid_usd"])
    put_ask   = float(put_row["ask_usd"])
    put_bid   = float(put_row["bid_usd"])

    call_spread = (call_ask - call_bid) / call_ask * 100
    put_spread  = (put_ask  - put_bid)  / put_ask  * 100

    straddle_ask       = call_ask + put_ask
    straddle_bid       = call_bid + put_bid
    straddle_spread    = (straddle_ask - straddle_bid) / straddle_ask * 100
    spot               = float(call_row["spot_usd"])
    straddle_pct_spot  = straddle_ask / spot * 100 if spot > 0 else None

    return {
        "call_strike":        float(call_row["strike"]),
        "call_actual_delta":  round(float(call_row["delta"]), 4),
        "call_delta_dist":    round(call_delta_dist, 4),
        "call_actual_iv":     round(float(call_row["mark_iv"]), 2),
        "call_ask_usd":       round(call_ask, 2),
        "call_bid_usd":       round(call_bid, 2),
        "call_spread_pct":    round(call_spread, 2),
        "put_strike":         float(put_row["strike"]),
        "put_actual_delta":   round(float(put_row["delta"]), 4),
        "put_delta_dist":     round(put_delta_dist, 4),
        "put_actual_iv":      round(float(put_row["mark_iv"]), 2),
        "put_ask_usd":        round(put_ask, 2),
        "put_bid_usd":        round(put_bid, 2),
        "put_spread_pct":     round(put_spread, 2),
        "straddle_ask_usd":   round(straddle_ask, 2),
        "straddle_bid_usd":   round(straddle_bid, 2),
        "straddle_spread_pct": round(straddle_spread, 2),
        "straddle_pct_spot":  round(straddle_pct_spot, 3) if straddle_pct_spot else None,
        "spot_usd":           round(spot, 2),
        "hours_to_expiry":    round(hours_to_expiry, 1),
    }


def _is_available(row: dict) -> bool:
    return (
        row["call_ask_usd"]     >= MIN_LEG_ASK_USD and
        row["put_ask_usd"]      >= MIN_LEG_ASK_USD and
        row["call_spread_pct"]  <= MAX_SPREAD_PCT and
        row["put_spread_pct"]   <= MAX_SPREAD_PCT and
        row["hours_to_expiry"]  >= MIN_HOURS_TO_EXPIRY
    )


# ── Print helpers ─────────────────────────────────────────────────────────────
def _header(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)

def _tstr(t: float) -> str:
    return f"_{t:.1f}".replace(".", "p")


def _pivot_table(df: pd.DataFrame, value_col: str, agg: str = "median",
                 fmt: str = "{:.0f}") -> None:
    """Print a DTE × delta_target pivot table."""
    grp = df.groupby(["dte", "delta_target"])[value_col]
    if agg == "median":
        tbl = grp.median()
    elif agg == "mean":
        tbl = grp.mean()
    elif agg == "availability":
        tbl = grp.apply(lambda x: x.sum() / len(x) if len(x) > 0 else float("nan"))
    else:
        raise ValueError(agg)

    tbl = tbl.unstack("delta_target")
    header = "  DTE \\ δ  " + "".join(f"  {d:.2f}  " for d in DELTA_TARGETS)
    print(header)
    print("  " + "-" * len(header))
    for dte in DTE_TARGETS:
        if dte not in tbl.index:
            continue
        parts = []
        for d in DELTA_TARGETS:
            try:
                val = float(tbl.loc[dte, d])
                cell = f"{fmt.format(val):>6}" if not np.isnan(val) else "   — "
            except (KeyError, TypeError, ValueError):
                cell = "   — "
            parts.append(f"  {cell}  ")
        print(f"  DTE {dte}   {''.join(parts)}")


# =============================================================================
# Main
# =============================================================================
def main() -> None:

    # ── 1h features and signal masks ─────────────────────────────────────────
    print("Loading BTCUSDT 1h data …")
    df_raw = pfdata.load("BTCUSDT", "1h")
    df_raw = df_raw[df_raw.index >= pd.Timestamp(LOAD_FROM, tz="UTC")]

    print("Computing features …")
    df = build_features(df_raw)
    df = add_outcomes(df)
    df = df[df.index >= pd.Timestamp(OPT_START, tz="UTC")]
    df = df[df.index <= pd.Timestamp(OPT_END,   tz="UTC")]
    df = df.dropna(subset=[f"mag_win{_tstr(PRIMARY)}"])

    opt_weeks = (df.index[-1] - df.index[0]).days / 7
    print(f"  {len(df):,} bars  {df.index[0].date()} → {df.index[-1].date()}  "
          f"({opt_weeks:.1f} weeks)")

    rv  = df["rv_rank"]
    vz  = df["vol_z"]
    r4h = df["ret_4h"]
    r1h = df["ret_1h"]

    mtf_calls    = (r4h >= 1.0) & (r1h <= -0.5)
    mtf_puts     = (r4h <= -1.0) & (r1h >= 0.5)
    pullback_mask = (mtf_calls | mtf_puts) & (rv >= 0.60)
    vol_burst_mask = (vz >= 1.5) & (rv >= 0.60)

    # Signal fire timestamps for each tier
    fires: dict[str, list[pd.Timestamp]] = {
        "pullback":  pullback_mask[pullback_mask].index.tolist(),
        "vol_burst": vol_burst_mask[vol_burst_mask].index.tolist(),
    }
    print(f"  pullback fires : {len(fires['pullback'])}")
    print(f"  vol_burst fires: {len(fires['vol_burst'])}")

    # ── Main loop ─────────────────────────────────────────────────────────────
    print(f"\nScanning options chain for each fire …")
    rows: list[dict] = []
    miss_dates: set[str] = set()

    all_fires: list[tuple[str, pd.Timestamp, float]] = []
    for sig, ts_list in fires.items():
        for ts in ts_list:
            rv_val = float(df.loc[ts, "rv_rank"]) if ts in df.index else float("nan")
            all_fires.append((sig, ts, rv_val))

    for i, (signal, ts, rv_val) in enumerate(all_fires):
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(all_fires)}] …")

        date_str  = ts.date().isoformat()
        fire_date = ts.date()
        fire_dt   = ts.to_pydatetime().replace(tzinfo=timezone.utc)
        entry_ts_us = int(fire_dt.timestamp() * 1_000_000)

        merged = _load_merged(date_str)
        if merged is None:
            miss_dates.add(date_str)
            continue

        snap = _get_snapshot(merged, entry_ts_us)
        if snap.empty:
            continue

        for dte in DTE_TARGETS:
            target_expiry_date = fire_date + timedelta(days=dte)
            expiry_code = ou.format_expiry(
                datetime(target_expiry_date.year, target_expiry_date.month,
                         target_expiry_date.day, 8, 0, tzinfo=timezone.utc)
            )

            for delta_tgt in DELTA_TARGETS:
                result = _find_straddle(snap, expiry_code, delta_tgt, entry_ts_us)

                base = {
                    "signal":       signal,
                    "fire_ts":      ts.isoformat(),
                    "date":         date_str,
                    "hour_utc":     ts.hour,
                    "rv_rank":      round(rv_val, 4),
                    "dte":          dte,
                    "delta_target": delta_tgt,
                }

                if result is None:
                    rows.append({**base, "available": False,
                                 "skip_reason": "no_matching_contract"})
                else:
                    avail = _is_available(result)
                    skip  = None if avail else (
                        "leg_ask_too_low"   if (result["call_ask_usd"] < MIN_LEG_ASK_USD or
                                                result["put_ask_usd"]  < MIN_LEG_ASK_USD)
                        else "spread_too_wide" if (result["call_spread_pct"] > MAX_SPREAD_PCT or
                                                   result["put_spread_pct"]  > MAX_SPREAD_PCT)
                        else "near_expiry"
                    )
                    rows.append({
                        **base,
                        **result,
                        "available":   avail,
                        "skip_reason": skip,
                    })
    df_out = pd.DataFrame(rows)
    df_avail = df_out[df_out["available"] == True].copy()

    print(f"\n  Total rows: {len(df_out):,}  ({len(df_avail):,} available)")
    if miss_dates:
        print(f"  Missing option data dates: {sorted(miss_dates)}")

    # =========================================================================
    # Section A — Availability grid
    # =========================================================================
    _header("A — AVAILABILITY RATE  (% of fires with a valid straddle)")
    print(f"  Filters: leg ask≥${MIN_LEG_ASK_USD:.0f}, spread≤{MAX_SPREAD_PCT:.0f}%, "
          f"hours_to_expiry≥{MIN_HOURS_TO_EXPIRY:.0f}h\n")

    df_out_flag = df_out.copy()
    df_out_flag["avail_flag"] = df_out_flag["available"].astype(float)

    for sig in ["pullback", "vol_burst"]:
        sub = df_out_flag[df_out_flag["signal"] == sig]
        print(f"  {sig}  (N fires = {sub['fire_ts'].nunique()})")
        _pivot_table(sub, "avail_flag", agg="availability", fmt="{:.0%}")
        print()

    # =========================================================================
    # Section B — Median straddle cost (USD)
    # =========================================================================
    _header("B — MEDIAN STRADDLE ASK  (USD, available rows only)")

    for sig in ["pullback", "vol_burst"]:
        sub = df_avail[df_avail["signal"] == sig]
        print(f"\n  {sig}  (N available = {len(sub):,})")
        _pivot_table(sub, "straddle_ask_usd", agg="median", fmt="${:.0f}")

    # =========================================================================
    # Section C — Median straddle cost as % of spot
    # =========================================================================
    _header("C — MEDIAN STRADDLE COST AS % OF SPOT  (available rows only)")

    for sig in ["pullback", "vol_burst"]:
        sub = df_avail[df_avail["signal"] == sig]
        print(f"\n  {sig}")
        _pivot_table(sub, "straddle_pct_spot", agg="median", fmt="{:.2f}%")

    # =========================================================================
    # Section D — Median IV at entry
    # =========================================================================
    _header("D — MEDIAN CALL IV AT ENTRY  (%, available rows only)")

    for sig in ["pullback", "vol_burst"]:
        sub = df_avail[df_avail["signal"] == sig]
        print(f"\n  {sig}")
        _pivot_table(sub, "call_actual_iv", agg="median", fmt="{:.1f}%")

    # =========================================================================
    # Section E — IV vs rv_rank quartile
    # =========================================================================
    _header("E — IV vs RV_RANK  (median call IV by rv_rank quartile, DTE=2 ATM ≈ δ0.35)")

    sub_atm = df_avail[(df_avail["dte"] == 2) & (df_avail["delta_target"] == 0.35)]
    if len(sub_atm) > 20:
        sub_atm = sub_atm.copy()
        sub_atm["rv_quartile"] = pd.qcut(sub_atm["rv_rank"], q=4,
                                         labels=["Q1 (low)", "Q2", "Q3", "Q4 (high)"])
        grp = sub_atm.groupby(["signal", "rv_quartile"], observed=True).agg(
            n=("call_actual_iv", "count"),
            median_iv=("call_actual_iv", "median"),
            median_straddle_ask=("straddle_ask_usd", "median"),
        ).reset_index()
        print(f"\n  {'signal':<12}  {'rv_quartile':<14}  {'N':>5}  "
              f"{'med_IV':>8}  {'med_straddle_ask':>18}")
        print("  " + "-" * 65)
        for _, r in grp.iterrows():
            print(f"  {r['signal']:<12}  {str(r['rv_quartile']):<14}  {int(r['n']):>5}  "
                  f"{r['median_iv']:>7.1f}%  ${r['median_straddle_ask']:>16.0f}")
    else:
        print(f"\n  (too few DTE-2 δ0.35 rows: {len(sub_atm)})")

    # =========================================================================
    # Section F — Summary per signal tier
    # =========================================================================
    _header("F — STRADDLE COST SUMMARY  (available, all DTE × delta combinations)")
    for sig in ["pullback", "vol_burst"]:
        sub = df_avail[df_avail["signal"] == sig]
        if sub.empty:
            continue
        print(f"\n  {sig}:")
        print(f"    {'DTE':>3}  {'δ tgt':>6}  {'N':>5}  {'med ask $':>10}  "
              f"{'med % spot':>12}  {'med IV%':>9}  {'med δ dist':>11}  {'avail%':>8}")
        print("    " + "-" * 72)
        grp = sub.groupby(["dte", "delta_target"]).agg(
            n=("straddle_ask_usd", "count"),
            med_ask=("straddle_ask_usd", "median"),
            med_pct=("straddle_pct_spot", "median"),
            med_iv=("call_actual_iv", "median"),
            med_ddist=("call_delta_dist", "median"),
        ).reset_index()
        # Availability denominator = all rows for this signal/dte/delta
        all_grp = df_out_flag[df_out_flag["signal"] == sig].groupby(
            ["dte", "delta_target"])["avail_flag"].agg(["sum", "count"]).reset_index()
        all_grp["avail_pct"] = all_grp["sum"] / all_grp["count"]
        merged_grp = grp.merge(all_grp[["dte", "delta_target", "avail_pct"]],
                               on=["dte", "delta_target"], how="left")
        for _, r in merged_grp.iterrows():
            avail_pct = float(r["avail_pct"]) if not np.isnan(float(r["avail_pct"])) else 0.0
            pct_str   = f"{float(r['med_pct']):.3f}%" if r["med_pct"] and not np.isnan(float(r["med_pct"])) else "  —"
            ddist_str = f"{float(r['med_ddist']):.3f}" if not np.isnan(float(r["med_ddist"])) else "  —"
            print(f"    {int(r['dte']):>3}  {float(r['delta_target']):>6.2f}  "
                  f"{int(r['n']):>5}  "
                  f"${float(r['med_ask']):>9.0f}  {pct_str:>12}  "
                  f"{float(r['med_iv']):>8.1f}%  {ddist_str:>10}  {avail_pct:>7.0%}")

    # ── Save CSV ───────────────────────────────────────────────────────────────
    df_out.to_csv(HERE / "11b_option_universe.csv", index=False)
    print(f"\n  → Saved {len(df_out):,} rows to 11b_option_universe.csv")
    print(f"    ({len(df_avail):,} available rows)")
    print("\nDone.")


if __name__ == "__main__":
    main()
