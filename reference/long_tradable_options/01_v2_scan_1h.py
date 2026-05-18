"""01_v2_scan_1h.py — V2 option universe scan at 1-hour entry resolution.

Key differences from v1 (01_scan_tradeable_longs.py):
  - Entry windows: every hour UTC (24/day vs 6/day in v1)
  - Forward window: capped at 24 hours (v1 went to expiry, often 96h+)
  - Winner threshold: peak bid ≥ entry ask × 2.0 within that 24h window
  - Tracks peak_multiple_24h for ALL candidates (not just winners)
    → enables winners-first signal discovery

Approach:
  For each 1h entry window:
    1. Sample the option chain
    2. For each candidate option, load 24h of forward bars
    3. Record max bid reached → peak_multiple_24h
    4. tradeable = (peak_multiple_24h >= 2.0)

Outputs (written alongside this script):
  candidates_1h.parquet   — one row per evaluated option, with peak_multiple_24h
  winners_2x_1h.parquet   — tradeable subset (peak ≥ 2×) with hold/pnl details
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "intraday_options"))
import option_utils as ou  # noqa: E402

# ---------------------------------------------------------------------------
# Config  — only these constants differ from v1
# ---------------------------------------------------------------------------
DATE_START    = date(2026, 1, 1)
DATE_END      = date(2026, 5, 12)
ENTRY_HOURS   = list(range(24))          # every hour UTC  ← v2 change

FORWARD_HOURS = 24                       # cap forward scan at 24h  ← v2 change
WIN_FACTOR    = 2.0                      # peak bid / entry ask to be "tradeable"  ← v2 change

DTE_MIN       = 1
DTE_MAX       = 7

DELTA_TARGETS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
DELTA_TOL     = 0.04

MIN_ENTRY_USD = 75.0

FEE_RATE_BTC  = 0.0003
FEE_CAP_RATIO = 0.125


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

@lru_cache(maxsize=30)
def _load_merged(date_str: str) -> pd.DataFrame | None:
    """Load + merge options+spot for one date. Cached."""
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


@lru_cache(maxsize=30)
def _contract_index(date_str: str) -> dict:
    """Pre-group a day's merged df by contract key for O(1) lookup.

    Returns: {(expiry, strike, is_call): numpy array shaped (n, 4)}
      columns: timestamp, bid_usd, spot_usd, mark_price
    Built once per date, then all forward-scan calls are O(1) lookup + O(288) slice.
    """
    merged = _load_merged(date_str)
    if merged is None:
        return {}

    idx: dict = {}
    # Only keep rows with valid bid
    valid = merged[merged["bid_price"] > 0]
    cols  = ["timestamp", "bid_usd", "spot_usd", "mark_price"]
    for (expiry, strike, is_call), grp in valid.groupby(
        ["expiry", "strike", "is_call"], sort=False
    ):
        idx[(expiry, float(strike), bool(is_call))] = (
            grp[cols].sort_values("timestamp").values  # numpy array, fast to slice
        )
    return idx


def _option_forward_rows(
    expiry: str,
    strike: float,
    is_call: bool,
    from_ts_us: int,
    to_ts_us: int,
) -> np.ndarray | None:
    """Return forward bars as numpy array (timestamp, bid_usd, spot_usd, mark_price).

    Uses pre-indexed contract dict — O(1) lookup per day + O(k) slice.
    Returns None if no data found.
    """
    from_d = datetime.fromtimestamp(from_ts_us / 1e6, tz=timezone.utc).date()
    to_d   = datetime.fromtimestamp(to_ts_us   / 1e6, tz=timezone.utc).date()
    key    = (expiry, float(strike), bool(is_call))

    chunks: list[np.ndarray] = []
    cur = from_d
    while cur <= to_d:
        idx = _contract_index(cur.isoformat())
        arr = idx.get(key)
        if arr is not None and len(arr):
            # arr[:,0] = timestamps; slice to window
            mask  = (arr[:, 0] >= from_ts_us) & (arr[:, 0] <= to_ts_us)
            chunk = arr[mask]
            if len(chunk):
                chunks.append(chunk)
        cur += timedelta(days=1)

    if not chunks:
        return None
    return np.concatenate(chunks, axis=0)


def _expiry_cutoff_ts_us(expiry_code: str) -> int:
    expiry_dt = ou.parse_expiry(expiry_code)
    cutoff_dt = expiry_dt - timedelta(hours=1)
    return int(cutoff_dt.timestamp() * 1_000_000)


def _fee_usd(mark_btc: float, spot_usd: float) -> float:
    fee_btc = min(FEE_RATE_BTC, FEE_CAP_RATIO * mark_btc)
    return fee_btc * spot_usd


def _ts_to_str(ts_us: int) -> str:
    dt = datetime.fromtimestamp(ts_us / 1_000_000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _contract_label(expiry: str, strike: float, is_call: bool) -> str:
    return f"{expiry} {int(strike)} {'C' if is_call else 'P'}"


def _build_entry_snapshot(date_str: str, hour: int) -> tuple[pd.DataFrame, int] | None:
    df = _load_merged(date_str)
    if df is None:
        return None

    entry_date = date.fromisoformat(date_str)
    target_dt  = datetime(entry_date.year, entry_date.month, entry_date.day,
                          hour, 0, 0, tzinfo=timezone.utc)
    target_us  = int(target_dt.timestamp() * 1_000_000)

    ts_vals = df["timestamp"].unique()
    snap_ts = int(ts_vals[np.abs(ts_vals - target_us).argmin()])
    snap    = df[df["timestamp"] == snap_ts].copy()
    if snap.empty:
        return None

    exp_codes    = snap["expiry"].unique().tolist()
    exp_date_map = {code: ou.parse_expiry(code).date() for code in exp_codes}
    snap["expiry_date"] = snap["expiry"].map(exp_date_map)
    snap["dte"]         = snap["expiry_date"].apply(lambda ed: (ed - entry_date).days)

    snap = snap[
        (snap["dte"]        >= DTE_MIN) &
        (snap["dte"]        <= DTE_MAX) &
        (snap["mark_price"] >  0) &
        (snap["ask_price"]  >  0) &
        (snap["bid_price"]  >  0) &
        (snap["spot_usd"]   >  0)
    ].copy()
    if snap.empty:
        return None

    snap["abs_delta"] = snap["delta"].abs()
    return snap, snap_ts


def _select_delta_targets(snap: pd.DataFrame) -> pd.DataFrame:
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
# Main scan  — core v2 logic
# ---------------------------------------------------------------------------

def main() -> None:
    all_dates  = ou.available_dates()
    scan_dates = [
        d for d in all_dates
        if DATE_START <= date.fromisoformat(d) <= DATE_END
    ]
    print(f"V2 scan: {len(scan_dates)} days  {scan_dates[0]} → {scan_dates[-1]}")
    print(f"Entry hours: all 24 UTC | Forward window: {FORWARD_HOURS}h | "
          f"Winner threshold: {WIN_FACTOR}x  | DTE {DTE_MIN}–{DTE_MAX}")
    print(f"Delta targets: {DELTA_TARGETS}")
    print()

    winner_rows:   list[dict] = []
    candidate_rows: list[dict] = []

    for di, date_str in enumerate(scan_dates, 1):
        if di % 10 == 0 or di == len(scan_dates):
            print(f"  [{di:3d}/{len(scan_dates)}]  {date_str}  "
                  f"— {len(winner_rows)} winners, {len(candidate_rows)} candidates so far")

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
                entry_bid_usd  = float(row["bid_usd"])

                cand_base = {
                    "entry_ts":       _ts_to_str(snap_ts_us),
                    "entry_ts_us":    snap_ts_us,
                    "contract":       _contract_label(expiry, strike, is_call),
                    "expiry":         expiry,
                    "strike":         strike,
                    "is_call":        is_call,
                    "dte_at_entry":   dte,
                    "delta_at_entry": round(entry_delta, 4),
                    "entry_ask_usd":  round(entry_ask_usd, 2),
                    "entry_ask_btc":  round(entry_ask_btc, 6),
                    "entry_bid_usd":  round(entry_bid_usd, 2),
                    "entry_iv":       round(entry_iv, 2),
                    "entry_spot_usd": round(entry_spot, 2),
                    "spread_pct":     round((entry_ask_usd - entry_bid_usd) / entry_ask_usd * 100, 3)
                                      if entry_ask_usd > 0 else None,
                }

                # Minimum entry price filter
                if entry_ask_usd < MIN_ENTRY_USD:
                    candidate_rows.append({**cand_base,
                                           "tradeable": False, "skip_reason": "ask_too_low",
                                           "peak_multiple_24h": None, "peak_hold_hours": None})
                    continue

                # Forward window: cap at 24h OR expiry cutoff, whichever is sooner
                cutoff_ts_us = _expiry_cutoff_ts_us(expiry)
                fwd_end_us   = snap_ts_us + int(FORWARD_HOURS * 3600 * 1_000_000)
                to_ts_us     = min(cutoff_ts_us, fwd_end_us)
                from_ts_us   = snap_ts_us + 5 * 60 * 1_000_000   # first bar after entry

                if from_ts_us >= to_ts_us:
                    # Option expires within the next 5 minutes — skip
                    candidate_rows.append({**cand_base,
                                           "tradeable": False, "skip_reason": "past_cutoff",
                                           "peak_multiple_24h": None, "peak_hold_hours": None})
                    continue

                # Load all forward bars in window — O(1) index lookup + O(288) slice
                fwd = _option_forward_rows(expiry, strike, is_call, from_ts_us, to_ts_us)
                # fwd columns: [timestamp, bid_usd, spot_usd, mark_price]

                if fwd is None or len(fwd) == 0:
                    candidate_rows.append({**cand_base,
                                           "tradeable": False, "skip_reason": "no_forward_data",
                                           "peak_multiple_24h": 0.0, "peak_hold_hours": None})
                    continue

                # ── V2 core: find 24h peak bid (not just first hit at 1.2×) ──
                peak_idx     = int(np.argmax(fwd[:, 1]))   # col 1 = bid_usd
                peak_bid_usd = float(fwd[peak_idx, 1])
                peak_ts_us   = int(fwd[peak_idx, 0])
                peak_spot    = float(fwd[peak_idx, 2])
                peak_mark    = float(fwd[peak_idx, 3])

                peak_multiple   = peak_bid_usd / entry_ask_usd
                peak_hold_hours = (peak_ts_us - snap_ts_us) / 1_000_000 / 3600
                spot_move_pct   = (peak_spot / entry_spot - 1) * 100
                abs_spot_move   = abs(spot_move_pct)

                tradeable = peak_multiple >= WIN_FACTOR

                candidate_rows.append({
                    **cand_base,
                    "tradeable":        tradeable,
                    "skip_reason":      None if tradeable else "peak_below_2x",
                    "peak_multiple_24h": round(peak_multiple, 4),
                    "peak_hold_hours":  round(peak_hold_hours, 2),
                    "peak_spot_usd":    round(peak_spot, 2),
                    "spot_move_pct":    round(spot_move_pct, 3),
                    "abs_spot_move_pct": round(abs_spot_move, 3),
                })

                if not tradeable:
                    continue

                # ── Winner: compute net P&L at peak exit ──
                entry_fee_usd = _fee_usd(entry_mark_btc, entry_spot)
                exit_fee_usd  = _fee_usd(peak_mark,      peak_spot)
                rt_fee_usd    = entry_fee_usd + exit_fee_usd
                net_pnl_usd   = peak_bid_usd - entry_ask_usd - rt_fee_usd

                winner_rows.append({
                    **cand_base,
                    "tradeable":         True,
                    "peak_multiple_24h": round(peak_multiple, 4),
                    "peak_hold_hours":   round(peak_hold_hours, 2),
                    "peak_bid_usd":      round(peak_bid_usd, 2),
                    "peak_spot_usd":     round(peak_spot, 2),
                    "spot_move_pct":     round(spot_move_pct, 3),
                    "abs_spot_move_pct": round(abs_spot_move, 3),
                    "entry_fee_usd":     round(entry_fee_usd, 2),
                    "exit_fee_usd":      round(exit_fee_usd, 2),
                    "rt_fee_usd":        round(rt_fee_usd, 2),
                    "net_pnl_usd":       round(net_pnl_usd, 2),
                })

    # ---------------------------------------------------------------------------
    # Write outputs
    # ---------------------------------------------------------------------------
    n_cands   = len(candidate_rows)
    n_winners = len(winner_rows)
    base_rate = 100 * n_winners / n_cands if n_cands else 0.0

    print()
    print("Done.")
    print(f"  Candidates evaluated : {n_cands:,}")
    print(f"  2x winners (24h)     : {n_winners:,}")
    print(f"  Base rate            : {base_rate:.1f}%")

    df_cands   = pd.DataFrame(candidate_rows)
    df_winners = pd.DataFrame(winner_rows)

    out_c = HERE / "candidates_1h.parquet"
    out_w = HERE / "winners_2x_1h.parquet"
    df_cands.to_parquet(out_c, index=False)
    df_winners.to_parquet(out_w, index=False)
    print(f"\nWrote {out_c}  ({len(df_cands):,} rows)")
    print(f"Wrote {out_w}  ({len(df_winners):,} rows)")

    # DTE / delta breakdown of winners
    if not df_winners.empty:
        print("\nWinners by DTE:")
        print(df_winners["dte_at_entry"].value_counts().sort_index().to_string())
        print("\nWinners by abs delta bucket:")
        bins   = [0, 0.20, 0.25, 0.30, 0.35, 0.40, 1.0]
        labels = ["<0.20", "0.20-0.25", "0.25-0.30", "0.30-0.35", "0.35-0.40", ">0.40"]
        df_winners["delta_bin"] = pd.cut(df_winners["delta_at_entry"].abs(),
                                         bins=bins, labels=labels)
        print(df_winners["delta_bin"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(line_buffering=True)   # live progress when piped
    main()
