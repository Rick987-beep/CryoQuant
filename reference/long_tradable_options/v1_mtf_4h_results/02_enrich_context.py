"""02_enrich_context.py — Add spot/IV context to tradeable_longs.parquet.

Reads tradeable_longs.parquet and adds:

  Time features:
    entry_date          — YYYY-MM-DD
    entry_hour_utc      — 0–23
    entry_day_of_week   — 0=Mon … 6=Sun (ISO)

  Prior spot moves (measured at entry vs N hours earlier):
    spot_1h_ago_usd     — spot close 1h before entry
    spot_4h_ago_usd     — spot close 4h before entry
    spot_24h_ago_usd    — spot close 24h before entry
    spot_1h_chg_pct     — % change from 1h ago to entry
    spot_4h_chg_pct     — % change from 4h ago to entry
    spot_24h_chg_pct    — % change from 24h ago to entry

  ATM IV at entry (nearest-to-spot call, lowest available DTE ≤ 3):
    atm_iv_at_entry     — mark_iv of ATM call at entry snapshot
    atm_dte_used        — which DTE was used for the lookup

  Directional context:
    direction_correct   — True if call+spot_up or put+spot_down (based on entry→exit move)
    abs_spot_move_pct   — abs(spot_move_entry_exit_pct)

Output:
  tradeable_longs_enriched.parquet
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "intraday_options"))
import option_utils as ou  # noqa: E402


# ---------------------------------------------------------------------------
# Spot lookups
# ---------------------------------------------------------------------------

def _spot_at_us(ts_us: int) -> float | None:
    """Return the BTC/USD spot close at the nearest 1-min bar for any µs timestamp."""
    dt       = datetime.fromtimestamp(ts_us / 1e6, tz=timezone.utc)
    date_str = dt.date().isoformat()
    try:
        df_spot = ou.load_spot_day(date_str)
    except FileNotFoundError:
        return None
    ts_vals = df_spot["timestamp"].values
    idx = int(np.abs(ts_vals - ts_us).argmin())
    return float(df_spot.iloc[idx]["close"])


def _str_to_us(ts_str: str) -> int:
    """Parse 'YYYY-MM-DD HH:MM UTC' back to µs epoch."""
    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000)


def _enrich_spot_context(df: pd.DataFrame) -> pd.DataFrame:
    """Add prior-spot-move columns.  Vectorised over groups by entry_date."""
    n = len(df)

    spot_1h_ago   = np.full(n, np.nan)
    spot_4h_ago   = np.full(n, np.nan)
    spot_24h_ago  = np.full(n, np.nan)

    for i, row in enumerate(df.itertuples(index=False)):
        ts_us = _str_to_us(row.entry_ts)
        for j, hours in enumerate([1, 4, 24]):
            prior_us = ts_us - hours * 3600 * 1_000_000
            val = _spot_at_us(prior_us)
            if j == 0:
                spot_1h_ago[i]  = val
            elif j == 1:
                spot_4h_ago[i]  = val
            else:
                spot_24h_ago[i] = val

        if (i + 1) % 1000 == 0:
            print(f"  spot context: {i+1}/{n}")

    spot_entry = df["entry_spot_usd"].values
    df = df.copy()
    df["spot_1h_ago_usd"]  = spot_1h_ago.round(2)
    df["spot_4h_ago_usd"]  = spot_4h_ago.round(2)
    df["spot_24h_ago_usd"] = spot_24h_ago.round(2)

    with np.errstate(invalid="ignore", divide="ignore"):
        df["spot_1h_chg_pct"]  = np.where(
            spot_1h_ago  > 0, (spot_entry / spot_1h_ago  - 1) * 100, np.nan
        ).round(4)
        df["spot_4h_chg_pct"]  = np.where(
            spot_4h_ago  > 0, (spot_entry / spot_4h_ago  - 1) * 100, np.nan
        ).round(4)
        df["spot_24h_chg_pct"] = np.where(
            spot_24h_ago > 0, (spot_entry / spot_24h_ago - 1) * 100, np.nan
        ).round(4)

    return df


# ---------------------------------------------------------------------------
# ATM IV lookup
# ---------------------------------------------------------------------------

def _atm_iv_at_entry(row: pd.Series) -> tuple[float | None, int | None]:
    """Return (atm_iv, dte_used) for the entry snapshot.

    Finds the nearest-to-spot call using DTE 1, 2, then 3 (whichever has data).
    """
    entry_date = row["entry_date"]
    entry_ts   = _str_to_us(row["entry_ts"])
    spot       = float(row["entry_spot_usd"])

    try:
        df_day = ou.load_day(entry_date)
    except FileNotFoundError:
        return None, None

    # Snap to nearest 5-min bar
    ts_vals = df_day["timestamp"].values
    snap_ts = int(ts_vals[np.abs(ts_vals - entry_ts).argmin()])
    snap    = df_day[df_day["timestamp"] == snap_ts].copy()

    if snap.empty:
        return None, None

    # Compute DTE for each row
    from datetime import date
    snap_date = datetime.fromtimestamp(snap_ts / 1e6, tz=timezone.utc).date()
    exp_map   = {c: ou.parse_expiry(c).date() for c in snap["expiry"].unique()}
    snap = snap.copy()
    snap["dte"] = snap["expiry"].map(exp_map).apply(lambda ed: (ed - snap_date).days)

    # Try DTE 1, 2, 3 in order
    for target_dte in [1, 2, 3]:
        sub = snap[
            (snap["dte"]        == target_dte) &
            (snap["is_call"]    == True) &         # noqa: E712
            (snap["mark_iv"]    >  0) &
            (snap["mark_price"] >  0)
        ]
        if sub.empty:
            continue
        # Nearest strike to spot
        nearest_idx = (sub["strike"] - spot).abs().values.argmin()
        iv = float(sub.iloc[nearest_idx]["mark_iv"])
        return iv, target_dte

    return None, None


def _enrich_atm_iv(df: pd.DataFrame) -> pd.DataFrame:
    n = len(df)
    atm_iv  = np.full(n, np.nan)
    atm_dte = np.full(n, np.nan)

    for i, row in enumerate(df.itertuples(index=False)):
        iv, dte = _atm_iv_at_entry(row._asdict())
        if iv is not None:
            atm_iv[i]  = iv
        if dte is not None:
            atm_dte[i] = dte

        if (i + 1) % 1000 == 0:
            print(f"  ATM IV: {i+1}/{n}")

    df = df.copy()
    df["atm_iv_at_entry"] = atm_iv.round(2)
    df["atm_dte_used"]    = atm_dte   # float64; NaN where not found, values 1/2/3
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    in_path  = HERE / "tradeable_longs.parquet"
    out_path = HERE / "tradeable_longs_enriched.parquet"

    df = pd.read_parquet(in_path)
    print(f"Loaded {len(df):,} tradeable trades from {in_path.name}")

    # --- time features ---
    print("Adding time features...")
    entry_dts = pd.to_datetime(df["entry_ts"].str.replace(" UTC", ""), utc=True)
    df["entry_date"]        = entry_dts.dt.strftime("%Y-%m-%d")
    df["entry_hour_utc"]    = entry_dts.dt.hour.astype("int8")
    df["entry_day_of_week"] = entry_dts.dt.dayofweek.astype("int8")  # 0=Mon

    # --- directional context ---
    print("Adding directional context...")
    move = df["spot_move_entry_exit_pct"].values
    df["abs_spot_move_pct"] = np.abs(move).round(4)
    df["direction_correct"] = (
        (df["is_call"] &  (move > 0)) |
        (~df["is_call"] & (move < 0))
    )

    # --- prior spot moves ---
    print(f"Adding prior spot context ({len(df):,} rows, ~{len(df)*3:,} lookups)...")
    df = _enrich_spot_context(df)

    # --- ATM IV at entry ---
    print("Adding ATM IV at entry...")
    df = _enrich_atm_iv(df)

    # --- write output ---
    df.to_parquet(out_path, index=False)
    print(f"\nWrote {out_path}")
    print(f"Shape: {df.shape}")

    # --- quick summary ---
    print("\n--- Enrichment summary ---")
    print(f"direction_correct: {df['direction_correct'].mean()*100:.1f}% of trades")
    print(f"abs_spot_move_pct: mean={df['abs_spot_move_pct'].mean():.2f}%  "
          f"median={df['abs_spot_move_pct'].median():.2f}%")
    print(f"hold_hours:        mean={df['hold_hours'].mean():.1f}h  "
          f"median={df['hold_hours'].median():.1f}h")
    print(f"atm_iv_at_entry:   mean={df['atm_iv_at_entry'].mean():.1f}%  "
          f"null={df['atm_iv_at_entry'].isna().sum()}")
    print(f"spot_4h_chg_pct:   mean={df['spot_4h_chg_pct'].mean():.2f}%  "
          f"null={df['spot_4h_chg_pct'].isna().sum()}")
    print("\nAll columns:")
    print(df.columns.tolist())


if __name__ == "__main__":
    main()
