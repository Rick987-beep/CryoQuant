"""01_scan_tradeable_longs.py — Identify historically tradeable BTC long options.

Scans 2026-01-01 → 2026-05-12, sampling entry snapshots at 4-hour UTC intervals.
For each candidate option at entry, walks forward at 5-min resolution to find
the first moment where selling at bid yields ≥20% gross gain net of Deribit fees.

Universe filters at entry:
  - DTE 1–7
  - |delta| ∈ [0.10, 0.40]  (sampled at target buckets 0.10, 0.15 … 0.40)
  - entry ask ≥ $75 USD

Fee model (per leg, Deribit options taker):
  fee_btc = min(0.0003, 0.125 × mark_price_btc)
  fee_usd = fee_btc × spot_index_usd
  RT fee  = entry_fee_usd + exit_fee_usd

Outputs (written to this folder):
  tradeable_longs.parquet     — one row per tradeable trade
  candidates_summary.parquet  — all evaluated entries with tradeable flag
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Path setup — import option_utils from the sibling intraday_options folder
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "intraday_options"))
import option_utils as ou  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATE_START     = date(2026, 1, 1)
DATE_END       = date(2026, 5, 12)
ENTRY_HOURS    = [0, 4, 8, 12, 16, 20]          # UTC

DTE_MIN        = 1
DTE_MAX        = 7

# abs(delta) target buckets — both calls (positive delta) and puts (negative)
DELTA_TARGETS  = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
DELTA_TOL      = 0.04    # skip strike if nearest delta is >4pp from target

MIN_ENTRY_USD  = 75.0
GROSS_FACTOR   = 1.20    # require exit bid >= entry ask × 1.20

# Deribit taker fee constants
FEE_RATE_BTC   = 0.0003   # 0.03% × 1 BTC contract per leg (floor)
FEE_CAP_RATIO  = 0.125    # 12.5% of mark price per leg (cap)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

@lru_cache(maxsize=14)
def _load_merged(date_str: str) -> pd.DataFrame | None:
    """Load options parquet for date_str with spot_usd merged in.

    Adds columns: spot_usd, bid_usd, ask_usd, mark_usd.
    Returns None if either parquet file is missing.
    Cached: subsequent calls for the same date are free.
    """
    try:
        df_opt  = ou.load_day(date_str)
        df_spot = ou.load_spot_day(date_str)
    except FileNotFoundError:
        return None

    df_opt  = df_opt.sort_values("timestamp").reset_index(drop=True)
    df_spot = (df_spot
               .sort_values("timestamp")
               [["timestamp", "close"]]
               .rename(columns={"close": "spot_usd"}))

    merged = pd.merge_asof(df_opt, df_spot, on="timestamp", direction="backward")
    spot   = merged["spot_usd"].values
    merged["bid_usd"]  = merged["bid_price"].values  * spot
    merged["ask_usd"]  = merged["ask_price"].values  * spot
    merged["mark_usd"] = merged["mark_price"].values * spot
    return merged


def _option_forward_rows(
    expiry: str,
    strike: float,
    is_call: bool,
    from_ts_us: int,
    to_ts_us: int,
) -> pd.DataFrame:
    """Return all 5-min rows for one specific option between two µs timestamps.

    Loads only the parquet day-files that overlap [from_ts_us, to_ts_us].
    Excludes rows with bid_price == 0 (stale / zeroed data).
    """
    from_d = datetime.fromtimestamp(from_ts_us / 1e6, tz=timezone.utc).date()
    to_d   = datetime.fromtimestamp(to_ts_us   / 1e6, tz=timezone.utc).date()

    chunks: list[pd.DataFrame] = []
    cur = from_d
    while cur <= to_d:
        df = _load_merged(cur.isoformat())
        if df is not None:
            mask = (
                (df["expiry"]    == expiry) &
                (np.abs(df["strike"].values - strike) < 0.5) &
                (df["is_call"]   == is_call) &
                (df["timestamp"] >= from_ts_us) &
                (df["timestamp"] <= to_ts_us) &
                (df["bid_price"] >  0)
            )
            chunk = df[mask]
            if not chunk.empty:
                chunks.append(chunk)
        cur += timedelta(days=1)

    if not chunks:
        return pd.DataFrame()

    return (pd.concat(chunks, ignore_index=True)
            .sort_values("timestamp")
            .drop_duplicates("timestamp")
            .reset_index(drop=True))


def _expiry_cutoff_ts_us(expiry_code: str) -> int:
    """Return µs timestamp of 1 hour before Deribit expiry (08:00 UTC → 07:00 UTC)."""
    expiry_dt = ou.parse_expiry(expiry_code)          # datetime at 08:00 UTC
    cutoff_dt = expiry_dt - timedelta(hours=1)        # 07:00 UTC on expiry day
    return int(cutoff_dt.timestamp() * 1_000_000)


def _fee_usd(mark_btc: float, spot_usd: float) -> float:
    """Deribit taker option fee in USD for one leg (buy OR sell)."""
    fee_btc = min(FEE_RATE_BTC, FEE_CAP_RATIO * mark_btc)
    return fee_btc * spot_usd


def _ts_to_str(ts_us: int) -> str:
    dt = datetime.fromtimestamp(ts_us / 1_000_000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _contract_label(expiry: str, strike: float, is_call: bool) -> str:
    return f"{expiry} {int(strike)} {'C' if is_call else 'P'}"


# ---------------------------------------------------------------------------
# Entry snapshot: build candidate list for one (date, hour)
# ---------------------------------------------------------------------------

def _build_entry_snapshot(date_str: str, hour: int) -> tuple[pd.DataFrame, int] | None:
    """Return (snapshot_df, snap_ts_us) for the 5-min bar nearest to hour:00 UTC.

    snapshot_df has DTE and abs_delta added; filtered to DTE_MIN–DTE_MAX and
    positive mark/ask/bid prices.
    Returns None if data is missing or snapshot is empty after filtering.
    """
    df = _load_merged(date_str)
    if df is None:
        return None

    entry_date = date.fromisoformat(date_str)
    target_dt  = datetime(entry_date.year, entry_date.month, entry_date.day,
                          hour, 0, 0, tzinfo=timezone.utc)
    target_us  = int(target_dt.timestamp() * 1_000_000)

    ts_vals   = df["timestamp"].unique()
    snap_ts   = int(ts_vals[np.abs(ts_vals - target_us).argmin()])
    snap      = df[df["timestamp"] == snap_ts].copy()
    if snap.empty:
        return None

    # Compute DTE for each option row
    exp_codes   = snap["expiry"].unique().tolist()
    exp_date_map = {code: ou.parse_expiry(code).date() for code in exp_codes}
    snap["expiry_date"] = snap["expiry"].map(exp_date_map)
    snap["dte"]         = snap["expiry_date"].apply(lambda ed: (ed - entry_date).days)

    # Quality + universe filters
    snap = snap[
        (snap["dte"]         >= DTE_MIN) &
        (snap["dte"]         <= DTE_MAX) &
        (snap["mark_price"]  >  0) &
        (snap["ask_price"]   >  0) &
        (snap["bid_price"]   >  0) &
        (snap["spot_usd"]    >  0)
    ].copy()

    if snap.empty:
        return None

    snap["abs_delta"] = snap["delta"].abs()
    return snap, snap_ts


def _select_delta_targets(snap: pd.DataFrame) -> pd.DataFrame:
    """For each (expiry, is_call), pick one option row per DELTA_TARGETS bucket.

    Deduplicates so that if two adjacent targets map to the same strike, only
    one row is returned for that (expiry, strike, is_call) triple.
    """
    seen_keys: set[tuple] = set()
    rows: list[dict] = []

    for (expiry, is_call), grp in snap.groupby(["expiry", "is_call"]):
        for tgt in DELTA_TARGETS:
            diffs = (grp["abs_delta"] - tgt).abs()
            if diffs.empty:
                continue
            best_pos = int(diffs.values.argmin())
            if diffs.iloc[best_pos] > DELTA_TOL:
                continue
            row = grp.iloc[best_pos]
            key = (expiry, float(row["strike"]), bool(is_call))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            rows.append(row.to_dict())

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

def main() -> None:
    all_dates  = ou.available_dates()
    scan_dates = [
        d for d in all_dates
        if DATE_START <= date.fromisoformat(d) <= DATE_END
    ]
    print(f"Scanning {len(scan_dates)} days  {scan_dates[0]} → {scan_dates[-1]}")
    print(f"Entry hours: {ENTRY_HOURS} UTC | DTE {DTE_MIN}–{DTE_MAX} | "
          f"delta targets: {DELTA_TARGETS}")
    print()

    tradeable_rows: list[dict] = []
    candidate_rows: list[dict] = []

    for di, date_str in enumerate(scan_dates, 1):
        if di % 10 == 0 or di == len(scan_dates):
            print(f"  [{di:3d}/{len(scan_dates)}]  {date_str}  "
                  f"— {len(tradeable_rows)} tradeable so far")

        for entry_hour in ENTRY_HOURS:
            result = _build_entry_snapshot(date_str, entry_hour)
            if result is None:
                continue
            snap, snap_ts_us = result

            cands = _select_delta_targets(snap)
            if cands.empty:
                continue

            for _, row in cands.iterrows():
                expiry         = str(row["expiry"])
                strike         = float(row["strike"])
                is_call        = bool(row["is_call"])
                dte            = int(row["dte"])
                entry_spot     = float(row["spot_usd"])
                entry_ask_usd  = float(row["ask_usd"])
                entry_ask_btc  = float(row["ask_price"])
                entry_mark_btc = float(row["mark_price"])
                entry_iv       = float(row["mark_iv"])
                entry_delta    = float(row["delta"])

                cand_base = {
                    "entry_ts":        _ts_to_str(snap_ts_us),
                    "contract":        _contract_label(expiry, strike, is_call),
                    "expiry":          expiry,
                    "strike":          strike,
                    "is_call":         is_call,
                    "dte_at_entry":    dte,
                    "delta_at_entry":  round(entry_delta, 4),
                    "entry_ask_usd":   round(entry_ask_usd, 2),
                    "entry_ask_btc":   round(entry_ask_btc, 6),
                    "entry_iv":        round(entry_iv, 2),
                    "entry_spot_usd":  round(entry_spot, 2),
                }

                # --- filter: minimum entry price ---
                if entry_ask_usd < MIN_ENTRY_USD:
                    candidate_rows.append({
                        **cand_base,
                        "tradeable":   False,
                        "skip_reason": "ask_too_low",
                    })
                    continue

                cutoff_ts_us   = _expiry_cutoff_ts_us(expiry)
                from_ts_us     = snap_ts_us + 5 * 60 * 1_000_000   # first bar after entry

                # --- filter: must have at least one forward bar before cutoff ---
                if from_ts_us >= cutoff_ts_us:
                    candidate_rows.append({
                        **cand_base,
                        "tradeable":   False,
                        "skip_reason": "past_cutoff",
                    })
                    continue

                # --- load forward rows for this specific option ---
                fwd = _option_forward_rows(
                    expiry, strike, is_call, from_ts_us, cutoff_ts_us
                )

                if fwd.empty:
                    candidate_rows.append({
                        **cand_base,
                        "tradeable":   False,
                        "skip_reason": "no_forward_data",
                    })
                    continue

                # --- vectorised: first row where bid_usd >= entry_ask × 1.20 ---
                target_bid_usd = entry_ask_usd * GROSS_FACTOR
                bid_arr        = fwd["bid_usd"].values
                hit_mask       = bid_arr >= target_bid_usd

                if not hit_mask.any():
                    candidate_rows.append({
                        **cand_base,
                        "tradeable":   False,
                        "skip_reason": "never_hit",
                    })
                    continue

                # --- check net P&L after fees ---
                hit_idx  = int(np.argmax(hit_mask))
                exit_row = fwd.iloc[hit_idx]

                exit_bid_usd  = float(exit_row["bid_usd"])
                exit_mark_btc = float(exit_row["mark_price"])
                exit_spot     = float(exit_row["spot_usd"])
                exit_ts_us    = int(exit_row["timestamp"])

                entry_fee_usd = _fee_usd(entry_mark_btc, entry_spot)
                exit_fee_usd  = _fee_usd(exit_mark_btc,  exit_spot)
                rt_fee_usd    = entry_fee_usd + exit_fee_usd

                net_pnl_usd   = exit_bid_usd - entry_ask_usd - rt_fee_usd

                if net_pnl_usd <= 0:
                    candidate_rows.append({
                        **cand_base,
                        "tradeable":   False,
                        "skip_reason": "fee_kill",
                    })
                    continue

                # --- tradeable ---
                hold_hours        = (exit_ts_us - snap_ts_us) / 1_000_000 / 3600
                gross_gain_pct    = (exit_bid_usd / entry_ask_usd - 1) * 100
                spot_move_pct     = (exit_spot / entry_spot - 1) * 100

                trade = {
                    **cand_base,
                    "tradeable":               True,
                    "exit_ts":                 _ts_to_str(exit_ts_us),
                    "exit_bid_usd":            round(exit_bid_usd, 2),
                    "exit_bid_btc":            round(float(exit_row["bid_price"]), 6),
                    "exit_spot_usd":           round(exit_spot, 2),
                    "hold_hours":              round(hold_hours, 2),
                    "gross_gain_pct":          round(gross_gain_pct, 2),
                    "entry_fee_usd":           round(entry_fee_usd, 2),
                    "exit_fee_usd":            round(exit_fee_usd, 2),
                    "rt_fee_usd":              round(rt_fee_usd, 2),
                    "net_pnl_usd":             round(net_pnl_usd, 2),
                    "spot_move_entry_exit_pct": round(spot_move_pct, 2),
                }

                tradeable_rows.append(trade)
                candidate_rows.append({
                    **cand_base,
                    "tradeable":   True,
                    "skip_reason": None,
                })

    # ---------------------------------------------------------------------------
    # Write outputs
    # ---------------------------------------------------------------------------
    n_cands    = len(candidate_rows)
    n_tradeable = len(tradeable_rows)
    base_rate  = 100 * n_tradeable / n_cands if n_cands else 0.0

    print()
    print(f"Done.")
    print(f"  Candidates evaluated : {n_cands:,}")
    print(f"  Tradeable trades     : {n_tradeable:,}")
    print(f"  Base rate            : {base_rate:.1f}%")

    df_tradeable  = pd.DataFrame(tradeable_rows)
    df_candidates = pd.DataFrame(candidate_rows)

    out_t = HERE / "tradeable_longs.parquet"
    out_c = HERE / "candidates_summary.parquet"
    df_tradeable.to_parquet(out_t,  index=False)
    df_candidates.to_parquet(out_c, index=False)
    print(f"\nWrote {out_t}")
    print(f"Wrote {out_c}")

    # --- quick preview ---
    if not df_tradeable.empty:
        preview_cols = [
            "entry_ts", "contract", "dte_at_entry", "delta_at_entry",
            "entry_ask_usd", "entry_iv", "entry_spot_usd",
            "exit_ts", "exit_bid_usd", "hold_hours",
            "gross_gain_pct", "rt_fee_usd", "net_pnl_usd",
            "spot_move_entry_exit_pct",
        ]
        available = [c for c in preview_cols if c in df_tradeable.columns]
        pd.set_option("display.max_columns", 20)
        pd.set_option("display.width", 200)
        pd.set_option("display.float_format", "{:.2f}".format)
        print("\nSample tradeable trades (first 10):")
        print(df_tradeable[available].head(10).to_string(index=False))

        # Skip reason breakdown
        print("\nCandidates by skip reason:")
        print(df_candidates.groupby(["skip_reason", "tradeable"]).size()
              .rename("count").to_string())


if __name__ == "__main__":
    main()
