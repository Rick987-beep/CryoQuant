"""02_v2_enrich.py — Enrich candidates_1h.parquet with entry-context features.

Features added
--------------
  entry_hour_utc     — hour of entry (0–23)
  entry_day_of_week  — 0=Mon … 6=Sun
  entry_date         — YYYY-MM-DD (kept for downstream grouping)
  spot_1h_chg_pct    — (spot_entry / spot_1h_ago − 1) × 100
  spot_4h_chg_pct    — (spot_entry / spot_4h_ago − 1) × 100
  spot_1h_accel      — spot_1h_chg_pct − prior_1h_chg_pct  (T−2h→T−1h)
  spot_vs_24h_ema    — (spot_entry / ewm_24h − 1) × 100
  atm_iv_at_entry    — mark_iv of nearest-to-spot call, DTE 1→2→3
  hv_1d              — annualised realised vol from last 24 hourly log-returns (%)
  iv_hv_ratio        — atm_iv_at_entry / hv_1d
  iv_30d_pct_rank    — fraction of prior 30-day daily IVs < atm_iv_at_entry

Output: candidates_1h_enriched.parquet (same rows, feature columns appended)
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
# Paths
# ---------------------------------------------------------------------------
IN_PATH  = HERE / "candidates_1h.parquet"
OUT_PATH = HERE / "candidates_1h_enriched.parquet"

HOUR_US = 3_600_000_000  # 1 hour in microseconds

# ---------------------------------------------------------------------------
# Spot helpers
# ---------------------------------------------------------------------------

@lru_cache(maxsize=20)
def _load_spot(date_str: str) -> tuple[np.ndarray, np.ndarray] | None:
    """Return (timestamps_us, closes) sorted ascending. Cached per day."""
    try:
        df = ou.load_spot_day(date_str)
    except FileNotFoundError:
        return None
    ts = df["timestamp"].values.astype(np.int64)
    cl = df["close"].values.astype(np.float64)
    order = np.argsort(ts)
    return ts[order], cl[order]


def _build_spot_window(date_str: str, days_back: int = 2) -> tuple[np.ndarray, np.ndarray] | None:
    """Concatenate spot arrays for [date − days_back .. date]. Returns (ts, close)."""
    d = date.fromisoformat(date_str)
    parts_ts, parts_cl = [], []
    for k in range(days_back, -1, -1):
        result = _load_spot((d - timedelta(days=k)).isoformat())
        if result is not None:
            parts_ts.append(result[0])
            parts_cl.append(result[1])
    if not parts_ts:
        return None
    ts = np.concatenate(parts_ts)
    cl = np.concatenate(parts_cl)
    order = np.argsort(ts)
    return ts[order], cl[order]


def _snap_spot_vec(query_us: np.ndarray, spot_ts: np.ndarray, spot_cl: np.ndarray) -> np.ndarray:
    """Vectorised nearest-bar lookup: for each query timestamp return the nearest close."""
    idx = np.searchsorted(spot_ts, query_us, side="left")
    idx = np.clip(idx, 0, len(spot_ts) - 1)
    left = np.maximum(idx - 1, 0)
    use_left = (idx > 0) & (np.abs(spot_ts[left] - query_us) <= np.abs(spot_ts[idx] - query_us))
    return spot_cl[np.where(use_left, left, idx)]


# ---------------------------------------------------------------------------
# EWM helper (vectorised, adjust=True equivalent)
# ---------------------------------------------------------------------------

def _ewm_last_vec(closes: np.ndarray, span: int) -> np.ndarray:
    """Return EWM(span, adjust=True) final value for each row of closes (N × T)."""
    alpha = 2.0 / (span + 1)
    T = closes.shape[1]
    # Weight for column t (0=oldest, T-1=newest): (1-alpha)^(T-1-t)
    k = np.arange(T - 1, -1, -1, dtype=np.float64)
    weights = (1.0 - alpha) ** k           # shape (T,)
    weights /= weights.sum()               # normalise → adjust=True
    return closes @ weights                # (N,)


# ---------------------------------------------------------------------------
# ATM IV — precompute per 5-min snap for an entire day
# ---------------------------------------------------------------------------

@lru_cache(maxsize=20)
def _atm_iv_snaps(date_str: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (snap_timestamps_us, atm_ivs) for every 5-min snap in one day.

    ATM IV = mark_iv of nearest-to-spot call, trying DTE 1 → 2 → 3.
    Returns two sorted numpy arrays; snap_timestamps_us is int64 µs.
    """
    try:
        df_opt  = ou.load_day(date_str)
        df_spot = ou.load_spot_day(date_str)
    except FileNotFoundError:
        return np.array([], dtype=np.int64), np.array([], dtype=np.float64)

    spot_ts = df_spot["timestamp"].values.astype(np.int64)
    spot_cl = df_spot["close"].values.astype(np.float64)
    order   = np.argsort(spot_ts)
    spot_ts, spot_cl = spot_ts[order], spot_cl[order]

    snap_date = date.fromisoformat(date_str)
    exp_to_dte = {
        c: (ou.parse_expiry(c).date() - snap_date).days
        for c in df_opt["expiry"].unique()
    }
    df_opt = df_opt.copy()
    df_opt["dte"] = df_opt["expiry"].map(exp_to_dte)

    snap_ts_list: list[int]    = []
    snap_iv_list: list[float]  = []

    for snap_ts_val, snap_df in df_opt.groupby("timestamp"):
        snap_ts_val = int(snap_ts_val)
        spot = float(_snap_spot_vec(np.array([snap_ts_val]), spot_ts, spot_cl)[0])

        for target_dte in [1, 2, 3]:
            sub = snap_df[
                (snap_df["dte"]        == target_dte) &
                (snap_df["is_call"]    == True)        &  # noqa: E712
                (snap_df["mark_iv"]    >  0)           &
                (snap_df["mark_price"] >  0)
            ]
            if sub.empty:
                continue
            nearest = int((sub["strike"] - spot).abs().values.argmin())
            snap_ts_list.append(snap_ts_val)
            snap_iv_list.append(float(sub.iloc[nearest]["mark_iv"]))
            break

    if not snap_ts_list:
        return np.array([], dtype=np.int64), np.array([], dtype=np.float64)

    arr_ts = np.array(snap_ts_list, dtype=np.int64)
    arr_iv = np.array(snap_iv_list, dtype=np.float64)
    order  = np.argsort(arr_ts)
    return arr_ts[order], arr_iv[order]


def _lookup_atm_iv_vec(entry_us: np.ndarray, snap_ts: np.ndarray, snap_iv: np.ndarray) -> np.ndarray:
    """Vectorised: for each entry_us return the ATM IV from the nearest snap."""
    if len(snap_ts) == 0:
        return np.full(len(entry_us), np.nan)
    idx  = np.searchsorted(snap_ts, entry_us, side="left")
    idx  = np.clip(idx, 0, len(snap_ts) - 1)
    left = np.maximum(idx - 1, 0)
    use_left = (idx > 0) & (np.abs(snap_ts[left] - entry_us) <= np.abs(snap_ts[idx] - entry_us))
    return snap_iv[np.where(use_left, left, idx)]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    c = pd.read_parquet(IN_PATH)
    print(f"Loaded {len(c):,} candidates from {IN_PATH.name}")
    n = len(c)

    # ── time features ────────────────────────────────────────────────────────
    print("Computing time features...")
    c["_entry_dt"]       = pd.to_datetime(c["entry_ts"].str.replace(" UTC", ""), utc=True)
    c["entry_hour_utc"]  = c["_entry_dt"].dt.hour.astype("int8")
    c["entry_day_of_week"] = c["_entry_dt"].dt.dayofweek.astype("int8")
    c["entry_date"]      = c["_entry_dt"].dt.strftime("%Y-%m-%d")
    c.drop(columns=["_entry_dt"], inplace=True)

    # Output arrays (indexed by row position in c, which has a clean RangeIndex)
    spot_1h_chg   = np.full(n, np.nan)
    spot_4h_chg   = np.full(n, np.nan)
    spot_1h_accel = np.full(n, np.nan)
    spot_ema24h   = np.full(n, np.nan)
    atm_iv_arr    = np.full(n, np.nan)
    hv_1d_arr     = np.full(n, np.nan)
    daily_atm_iv: dict[str, float] = {}   # date → daily reference IV (for iv_30d_pct_rank)

    # ── per-date group processing ─────────────────────────────────────────────
    dates_sorted = sorted(c["entry_date"].unique())
    print(f"Processing {len(dates_sorted)} unique dates...")

    for i_d, date_str in enumerate(dates_sorted):
        if (i_d + 1) % 20 == 0 or i_d == 0:
            print(f"  [{i_d+1:3d}/{len(dates_sorted)}] {date_str}  "
                  f"spot_cache={_load_spot.cache_info().currsize}  "
                  f"iv_cache={_atm_iv_snaps.cache_info().currsize}")

        group  = c[c["entry_date"] == date_str]
        ridx   = group.index.values                      # positions in c
        eu     = group["entry_ts_us"].values.astype(np.int64)
        es     = group["entry_spot_usd"].values.astype(np.float64)
        N      = len(eu)

        # ── spot window ───────────────────────────────────────────────────────
        sw = _build_spot_window(date_str, days_back=2)
        if sw is not None:
            sp_ts, sp_cl = sw

            # T−1h, T−2h, T−4h (vectorised)
            s1 = _snap_spot_vec(eu - 1 * HOUR_US, sp_ts, sp_cl)
            s2 = _snap_spot_vec(eu - 2 * HOUR_US, sp_ts, sp_cl)
            s4 = _snap_spot_vec(eu - 4 * HOUR_US, sp_ts, sp_cl)

            with np.errstate(invalid="ignore", divide="ignore"):
                chg1 = np.where(s1 > 0, (es / s1 - 1.0) * 100.0, np.nan)
                chg4 = np.where(s4 > 0, (es / s4 - 1.0) * 100.0, np.nan)
                p1   = np.where((s1 > 0) & (s2 > 0), (s1 / s2 - 1.0) * 100.0, np.nan)
                accel = chg1 - p1

            spot_1h_chg[ridx]   = np.round(chg1, 4)
            spot_4h_chg[ridx]   = np.round(chg4, 4)
            spot_1h_accel[ridx] = np.round(accel, 4)

            # 25-point hourly matrix: columns = T−24h … T−0h
            # Shape (N, 25)
            offsets   = np.arange(24, -1, -1, dtype=np.int64) * HOUR_US  # [24h, 23h, ..., 0]
            query_us  = eu[:, None] - offsets[None, :]                    # (N, 25)
            hourly_cl = _snap_spot_vec(query_us.ravel(), sp_ts, sp_cl).reshape(N, 25)

            # spot_vs_24h_ema: use last 24 hourly closes (cols 1..24 = T−23h..T−0h)
            closes24 = hourly_cl[:, 1:]    # (N, 24), oldest→newest
            valid_ema = (closes24 > 0).all(axis=1) & ~np.isnan(closes24).any(axis=1)
            if valid_ema.any():
                ema_vals = _ewm_last_vec(closes24[valid_ema], span=24)
                with np.errstate(invalid="ignore", divide="ignore"):
                    spot_ema24h[ridx[valid_ema]] = np.round(
                        (es[valid_ema] / ema_vals - 1.0) * 100.0, 4
                    )

            # hv_1d: std of 24 log-returns from 25 hourly closes (all cols)
            valid_hv = (hourly_cl > 0).all(axis=1) & ~np.isnan(hourly_cl).any(axis=1)
            if valid_hv.any():
                with np.errstate(invalid="ignore", divide="ignore"):
                    log_rets = np.log(hourly_cl[valid_hv, 1:] / hourly_cl[valid_hv, :-1])
                hv_vals = np.std(log_rets, axis=1) * np.sqrt(8760.0) * 100.0
                hv_1d_arr[ridx[valid_hv]] = np.round(hv_vals, 4)

        # ── ATM IV ────────────────────────────────────────────────────────────
        snap_ts, snap_iv = _atm_iv_snaps(date_str)
        if len(snap_ts) > 0:
            iv_vals = _lookup_atm_iv_vec(eu, snap_ts, snap_iv)
            atm_iv_arr[ridx] = np.round(iv_vals, 3)

            # Daily reference IV: median of ATM IVs on this date (for iv_30d_pct_rank)
            daily_atm_iv[date_str] = float(np.nanmedian(iv_vals))

    # ── iv_hv_ratio ──────────────────────────────────────────────────────────
    with np.errstate(invalid="ignore", divide="ignore"):
        iv_hv_ratio = np.where(hv_1d_arr > 0, atm_iv_arr / hv_1d_arr, np.nan)

    # ── iv_30d_pct_rank ──────────────────────────────────────────────────────
    print("Computing iv_30d_pct_rank...")
    entry_dates = c["entry_date"].values
    iv_30d_rank = np.full(n, np.nan)

    for i in range(n):
        iv_entry = atm_iv_arr[i]
        if np.isnan(iv_entry):
            continue
        d0 = date.fromisoformat(entry_dates[i])
        prior_ivs = []
        for k in range(1, 31):
            d_str = (d0 - timedelta(days=k)).isoformat()
            iv_d  = daily_atm_iv.get(d_str)
            if iv_d is not None and not np.isnan(iv_d):
                prior_ivs.append(iv_d)
        if len(prior_ivs) >= 10:  # require at least 10 days for a stable rank
            iv_30d_rank[i] = float(np.mean(np.array(prior_ivs) < iv_entry))

    # ── assemble output ──────────────────────────────────────────────────────
    print("Assembling output...")
    out = c.copy()
    out["spot_1h_chg_pct"]   = spot_1h_chg
    out["spot_4h_chg_pct"]   = spot_4h_chg
    out["spot_1h_accel"]     = spot_1h_accel
    out["spot_vs_24h_ema"]   = spot_ema24h
    out["atm_iv_at_entry"]   = atm_iv_arr
    out["hv_1d"]             = hv_1d_arr
    out["iv_hv_ratio"]       = iv_hv_ratio
    out["iv_30d_pct_rank"]   = iv_30d_rank

    out.to_parquet(OUT_PATH, index=False)
    print(f"\nWrote {OUT_PATH}")
    print(f"Shape: {out.shape}")

    # ── sanity check ─────────────────────────────────────────────────────────
    feat_cols = [
        "entry_hour_utc", "entry_day_of_week",
        "spot_1h_chg_pct", "spot_4h_chg_pct", "spot_1h_accel",
        "spot_vs_24h_ema", "atm_iv_at_entry", "hv_1d",
        "iv_hv_ratio", "iv_30d_pct_rank",
    ]
    print("\n--- Feature null counts ---")
    for col in feat_cols:
        null_n = out[col].isna().sum()
        pct    = null_n / n * 100
        print(f"  {col:25s}: {null_n:6,} nulls ({pct:.1f}%)")

    print("\n--- Feature distributions ---")
    for col in ["spot_1h_chg_pct", "spot_4h_chg_pct", "spot_1h_accel",
                "spot_vs_24h_ema", "atm_iv_at_entry", "hv_1d",
                "iv_hv_ratio", "iv_30d_pct_rank"]:
        s = out[col].dropna()
        if len(s) == 0:
            print(f"  {col:25s}: all null")
            continue
        print(f"  {col:25s}: n={len(s):,}  "
              f"mean={s.mean():.3f}  p25={s.quantile(.25):.3f}  "
              f"p50={s.median():.3f}  p75={s.quantile(.75):.3f}  "
              f"std={s.std():.3f}")

    # Quick lift check vs base rate
    base = out["tradeable"].mean()
    print(f"\n--- Quick lift check (base rate: {base:.3f}) ---")
    print("iv_30d_pct_rank deciles:")
    out["iv_rank_decile"] = pd.qcut(out["iv_30d_pct_rank"].dropna(),
                                    q=5, labels=False, duplicates="drop")
    valid = out[out["iv_30d_pct_rank"].notna()]
    valid = valid.copy()
    valid["q"] = pd.qcut(valid["iv_30d_pct_rank"], q=5, labels=False, duplicates="drop")
    print(valid.groupby("q")[["tradeable"]].mean().round(3).to_string())


if __name__ == "__main__":
    main()
