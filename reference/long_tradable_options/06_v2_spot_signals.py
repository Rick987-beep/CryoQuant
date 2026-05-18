"""06_v2_spot_signals.py — BTCUSD chart-based entry signal discovery.

Works entirely from BTCUSDT_1h.parquet (no options data).
Analysis window: 2025-01-01 → 2026-05-15.

Train: 2025-01-01 → 2025-09-30  (~6,500 bars)
Test:  2025-10-01 → 2026-05-15  (~5,400 bars, overlaps options analysis period)

Outcome variables (forward 24 bars from entry close):
    mag_win   — max(up_move, down_move) >= THRESH  (big move either direction)
    call_win  — fwd 24h high  >= close * (1 + THRESH/100)
    put_win   — fwd 24h low   <= close * (1 - THRESH/100)

Thresholds tested: 1.5%, 2.0%, 2.5%, 3.0%, 3.5%  (primary: 2.5%)

Sections
--------
  A   Base rates at each threshold (overall, train, test)
  B   Feature AUC table — Mann-Whitney, Bonferroni correction (train set)
  C   Bucket win rates  — 10 quantile bins per continuous feature (train set)
  D   Train/test validation — features that passed B re-evaluated on test set
  E   Session effects  — hour_utc and day_of_week win rates
  F   Combination conditions — top pre-defined condition table

Outputs (CSV alongside this script)
------------------------------------
  06_feature_auc.csv
  06_bucket_winrates.csv
  06_train_test_validation.csv
  06_conditions.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make pineforge importable when running from the repo root
_REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO / "pineforge"))

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

import pineforge.data as pfdata
import pineforge.ta as ta

HERE = Path(__file__).resolve().parent

# ── Config ──────────────────────────────────────────────────────────────────
LOAD_FROM      = "2024-01-01"   # extra warmup before analysis window
DATE_START     = "2025-01-01"   # analysis window start
DATE_END       = "2026-05-15"   # analysis window end
TRAIN_END      = "2025-09-30"   # train/test cut
TEST_START     = "2025-10-01"

FWD_BARS       = 24             # forward look window (hours)
THRESHOLDS     = [1.5, 2.0, 2.5, 3.0, 3.5]
PRIMARY        = 2.5            # primary threshold for detailed output

BB_LEN         = 20
BB_MULT        = 2.0
EMA_SHORT      = 24             # 24h EMA
EMA_LONG       = 168            # 7-day EMA
RV_BARS        = 24             # rolling window for realized vol
RV_RANK_BARS   = 720            # 30 days × 24h  (rolling percentile window)
VOL_Z_BARS     = 24
RANGE_BARS     = 24
BONFERRONI_K   = 12             # number of continuous features (for correction)
AUC_THRESH     = 0.55
PVAL_THRESH    = 0.005          # after Bonferroni: 0.05 / 12

CONT_FEATURES = [
    "ret_1h", "ret_4h", "ret_1d", "accel_1h",
    "close_vs_ema24", "close_vs_ema168",
    "rv_24h", "rv_rank", "rv_trend",
    "bb_width", "vol_z", "range_ratio",
]
CAT_FEATURES  = ["hour_utc", "day_of_week"]


# ── Feature builder ──────────────────────────────────────────────────────────

def build_features(df1h: pd.DataFrame) -> pd.DataFrame:
    """Build entry-time features from 1h OHLCV. All backward-looking — no lookahead.

    Bar timestamps are bar-OPEN (Binance convention): the bar at T covers T→T+1h.
    close[T] and volume[T] are therefore only known at T+1h.  All price-derived
    features are shifted by 1 bar before being returned so that feature[T]
    reflects only information available at T (i.e. from closed bars ≤ T-1).
    Session features (hour_utc, day_of_week) and raw OHLCV columns are unshifted.
    """
    close  = df1h["close"]
    high   = df1h["high"]
    low    = df1h["low"]
    volume = df1h["volume"]

    # ── 1h momentum
    ret_1h   = close.pct_change() * 100
    accel_1h = ret_1h - ret_1h.shift(1)

    # ── 4h momentum (closed-bar-safe HTF align)
    df4h          = pfdata.resample(df1h, "4h")
    ret_4h_htf    = df4h["close"].pct_change() * 100
    ret_4h_htf.name = "ret_4h"
    ret_4h        = pfdata.htf_align(df1h, ret_4h_htf, htf="4h")

    # ── 1d momentum
    df1d          = pfdata.resample(df1h, "1d")
    ret_1d_htf    = df1d["close"].pct_change() * 100
    ret_1d_htf.name = "ret_1d"
    ret_1d        = pfdata.htf_align(df1h, ret_1d_htf, htf="1d")

    # ── EMA distances
    ema24  = ta.ema(close, EMA_SHORT)
    ema168 = ta.ema(close, EMA_LONG)
    close_vs_ema24  = (close / ema24  - 1) * 100
    close_vs_ema168 = (close / ema168 - 1) * 100

    # ── Realized vol: 24-bar annualised std of log returns
    log_ret = np.log(close / close.shift(1))
    rv_24h  = (log_ret.rolling(RV_BARS, min_periods=RV_BARS).std()
               * np.sqrt(8760) * 100)   # % annualised

    # ── RV rank: rolling 30d percentile of rv_24h
    rv_rank = rv_24h.rolling(RV_RANK_BARS, min_periods=RV_RANK_BARS // 2).rank(pct=True)

    # ── RV trend: is volatility expanding into this entry?
    rv_trend = rv_24h - rv_24h.shift(24)

    # ── Bollinger Band width (squeeze detector)
    bb_width = ta.bbw(close, BB_LEN, BB_MULT)

    # ── Volume z-score (relative volume spike)
    vol_mean  = volume.rolling(VOL_Z_BARS, min_periods=VOL_Z_BARS // 2).mean()
    vol_std   = volume.rolling(VOL_Z_BARS, min_periods=VOL_Z_BARS // 2).std(ddof=0)
    vol_z     = (volume - vol_mean) / vol_std.replace(0, np.nan)

    # ── Range ratio (is current bar range larger than recent average?)
    bar_range_pct = (high - low) / close * 100
    range_avg     = bar_range_pct.rolling(RANGE_BARS, min_periods=RANGE_BARS // 2).mean()
    range_ratio   = bar_range_pct / range_avg.replace(0, np.nan)

    # ── Session
    hour_utc    = pd.Series(df1h.index.hour,       index=df1h.index, dtype="int8")
    day_of_week = pd.Series(df1h.index.dayofweek,  index=df1h.index, dtype="int8")

    # Shift all price-derived features by 1 bar so that feature[T] uses only
    # data available at T (bars 0…T-1 are closed; bar T's close is at T+1h).
    # Session and raw OHLCV columns are intentionally not shifted.
    return pd.DataFrame({
        "ret_1h":          ret_1h.shift(1),
        "ret_4h":          ret_4h.shift(1),
        "ret_1d":          ret_1d.shift(1),
        "accel_1h":        accel_1h.shift(1),
        "close_vs_ema24":  close_vs_ema24.shift(1),
        "close_vs_ema168": close_vs_ema168.shift(1),
        "rv_24h":          rv_24h.shift(1),
        "rv_rank":         rv_rank.shift(1),
        "rv_trend":        rv_trend.shift(1),
        "bb_width":        bb_width.shift(1),
        "vol_z":           vol_z.shift(1),
        "range_ratio":     range_ratio.shift(1),
        "hour_utc":        hour_utc,       # timestamp-based, no shift
        "day_of_week":     day_of_week,    # timestamp-based, no shift
        "close":           close,          # raw OHLCV for outcome labelling
        "high":            high,
        "low":             low,
        "volume":          volume,
    })


def add_outcomes(df: pd.DataFrame) -> pd.DataFrame:
    """Add forward-looking outcome columns (only used for labelling, never as features)."""
    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    # Forward 24-bar max high / min low (bars t+1 … t+24, inclusive)
    # rolling(24).max().shift(-24) at bar t = max(high[t+1 … t+24])
    fwd_max_high = high.rolling(FWD_BARS, min_periods=FWD_BARS).max().shift(-FWD_BARS)
    fwd_min_low  = low .rolling(FWD_BARS, min_periods=FWD_BARS).min().shift(-FWD_BARS)

    move_up_pct = (fwd_max_high - close) / close * 100
    move_dn_pct = (close - fwd_min_low)  / close * 100

    for thresh in THRESHOLDS:
        t = f"_{thresh:.1f}".replace(".", "p")
        df[f"call_win{t}"] = (move_up_pct >= thresh).astype("int8")
        df[f"put_win{t}"]  = (move_dn_pct >= thresh).astype("int8")
        df[f"mag_win{t}"]  = ((move_up_pct >= thresh) | (move_dn_pct >= thresh)).astype("int8")

    df["move_up_pct"] = move_up_pct
    df["move_dn_pct"] = move_dn_pct
    return df


# ── Statistics helpers ───────────────────────────────────────────────────────

def mw_auc(feature: np.ndarray, label: np.ndarray) -> tuple[float, float]:
    """Mann-Whitney AUC and two-sided p-value. Returns (nan, nan) if too few samples."""
    valid = ~(np.isnan(feature) | np.isnan(label.astype(float)))
    x, y  = feature[valid], label[valid]
    pos, neg = x[y == 1], x[y == 0]
    if len(pos) < 10 or len(neg) < 10:
        return np.nan, np.nan
    stat, p = mannwhitneyu(pos, neg, alternative="two-sided")
    auc = stat / (len(pos) * len(neg))
    return float(auc), float(p)


def win_rate_buckets(df: pd.DataFrame, feature: str, target: str,
                     n_bins: int = 10) -> pd.DataFrame:
    """Win rate per decile bucket of `feature` vs binary `target`."""
    valid = df[[feature, target]].dropna()
    if len(valid) < n_bins * 5:
        return pd.DataFrame()
    valid = valid.copy()
    try:
        valid["bucket"] = pd.qcut(valid[feature], q=n_bins, duplicates="drop")
    except ValueError:
        return pd.DataFrame()
    grp = valid.groupby("bucket", observed=True)[target].agg(["mean", "count"]).reset_index()
    grp.columns = ["bucket", "win_rate", "n"]
    grp["feature"] = feature
    grp["target"]  = target
    return grp


def _tstr(thresh: float) -> str:
    return f"_{thresh:.1f}".replace(".", "p")


# ── Print helpers ─────────────────────────────────────────────────────────────

def _header(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def _subheader(title: str) -> None:
    print(f"\n--- {title} ---")


# =============================================================================
# Main
# =============================================================================

def main() -> None:

    # ── Load data ─────────────────────────────────────────────────────────────
    print("Loading BTCUSDT 1h data …")
    df_raw = pfdata.load("BTCUSDT", "1h")
    df_raw = df_raw[df_raw.index >= pd.Timestamp(LOAD_FROM, tz="UTC")]
    print(f"  {len(df_raw):,} bars  {df_raw.index[0].date()} → {df_raw.index[-1].date()}")

    # ── Build features ────────────────────────────────────────────────────────
    print("Computing features …")
    df = build_features(df_raw)
    df = add_outcomes(df)

    # Slice to analysis window AFTER feature computation (warmup is in LOAD_FROM gap)
    df = df[df.index >= pd.Timestamp(DATE_START, tz="UTC")]
    df = df[df.index <= pd.Timestamp(DATE_END,   tz="UTC")]
    # Drop bars where forward window is incomplete (last FWD_BARS bars)
    df = df.dropna(subset=[f"mag_win{_tstr(PRIMARY)}"])

    print(f"  Analysis window: {df.index[0].date()} → {df.index[-1].date()}  ({len(df):,} bars)")

    train = df[df.index <= pd.Timestamp(TRAIN_END, tz="UTC")]
    test  = df[df.index >= pd.Timestamp(TEST_START, tz="UTC")]
    print(f"  Train: {len(train):,} bars  |  Test: {len(test):,} bars")

    # =========================================================================
    # Section A — Base rates
    # =========================================================================
    _header("A — BASE RATES")
    print(f"  {'Target':<18}  {'Thresh':>6}  {'Overall':>8}  {'Train':>8}  {'Test':>8}  {'N_all':>7}")
    print("  " + "-" * 60)
    for thresh in THRESHOLDS:
        t = _tstr(thresh)
        for tgt in ["mag_win", "call_win", "put_win"]:
            col = f"{tgt}{t}"
            ov = df[col].mean()
            tr = train[col].mean()
            te = test[col].mean()
            n  = df[col].sum()
            print(f"  {col:<18}  {thresh:>5.1f}%  {ov:>7.1%}  {tr:>7.1%}  {te:>7.1%}  {n:>7,}")

    # =========================================================================
    # Section B — Feature AUC (train set)
    # =========================================================================
    _header(f"B — FEATURE AUC  (train set, primary threshold {PRIMARY}%)  "
            f"[Bonferroni k={BONFERRONI_K}, raw p<{BONFERRONI_K * PVAL_THRESH:.3f}]")
    print(f"  {'Feature':<20}  {'Target':<10}  {'AUC':>6}  {'p_raw':>10}  {'p_bonf':>10}  {'Pass':>5}")
    print("  " + "-" * 68)

    auc_rows = []
    for tgt in ["mag_win", "call_win", "put_win"]:
        col = f"{tgt}{_tstr(PRIMARY)}"
        label = train[col].to_numpy()
        for feat in CONT_FEATURES:
            vals = train[feat].to_numpy(dtype=float)
            auc, p_raw = mw_auc(vals, label)
            if np.isnan(auc):
                continue
            p_bonf = min(p_raw * BONFERRONI_K, 1.0)
            passes = (abs(auc - 0.5) >= (AUC_THRESH - 0.5)) and (p_bonf < 0.05)
            auc_rows.append({
                "feature": feat, "target": tgt, "threshold": PRIMARY,
                "auc": round(auc, 4), "p_raw": p_raw, "p_bonferroni": p_bonf,
                "significant": passes,
            })
            flag = "✓" if passes else ""
            print(f"  {feat:<20}  {tgt:<10}  {auc:>6.4f}  {p_raw:>10.2e}  {p_bonf:>10.2e}  {flag:>5}")

    auc_df = pd.DataFrame(auc_rows)
    auc_df.to_csv(HERE / "06_feature_auc.csv", index=False)
    print(f"\n  → Saved {len(auc_df)} rows to 06_feature_auc.csv")

    # Summary: which features passed for any target
    passed = auc_df[auc_df["significant"]]["feature"].unique().tolist()
    print(f"\n  Features passing threshold: {passed if passed else '(none)'}")

    # =========================================================================
    # Section C — Bucket win rates (train set, primary threshold)
    # =========================================================================
    _header(f"C — BUCKET WIN RATES  (train set, {PRIMARY}%,  10 deciles per feature)")

    bucket_rows = []
    for tgt in ["mag_win", "call_win", "put_win"]:
        col = f"{tgt}{_tstr(PRIMARY)}"
        for feat in CONT_FEATURES:
            bkt = win_rate_buckets(train, feat, col, n_bins=10)
            if bkt.empty:
                continue
            bkt["threshold"] = PRIMARY
            bucket_rows.append(bkt)

    if bucket_rows:
        bucket_df = pd.concat(bucket_rows, ignore_index=True)
        bucket_df.to_csv(HERE / "06_bucket_winrates.csv", index=False)
        print(f"  → Saved {len(bucket_df)} rows to 06_bucket_winrates.csv")
    else:
        bucket_df = pd.DataFrame()

    # Print top-3 and bottom-3 buckets for features that passed AUC
    for feat in passed:
        _subheader(f"Buckets: {feat}  (mag_win @ {PRIMARY}%)")
        col = f"mag_win{_tstr(PRIMARY)}"
        bkt = win_rate_buckets(train, feat, col, n_bins=10)
        if bkt.empty:
            print("    (no data)")
            continue
        base = train[col].mean()
        bkt["lift"] = bkt["win_rate"] / base
        bkt_s = bkt.sort_values("win_rate", ascending=False)
        print(f"    {'Bucket':<30}  {'N':>6}  {'WinRate':>8}  {'Lift':>6}")
        for _, r in bkt_s.iterrows():
            print(f"    {str(r['bucket']):<30}  {int(r['n']):>6}  {r['win_rate']:>7.1%}  {r['lift']:>6.2f}x")

    # Also show hour_utc and day_of_week in this section
    for cat in CAT_FEATURES:
        _subheader(f"Session: {cat}  (mag_win @ {PRIMARY}%)")
        col = f"mag_win{_tstr(PRIMARY)}"
        grp = train.groupby(cat)[col].agg(["mean", "count"]).reset_index()
        grp.columns = [cat, "win_rate", "n"]
        base = train[col].mean()
        grp["lift"] = grp["win_rate"] / base
        grp = grp.sort_values("win_rate", ascending=False)
        print(f"    {cat:<15}  {'N':>6}  {'WinRate':>8}  {'Lift':>6}")
        for _, r in grp.iterrows():
            lbl = int(r[cat])
            if cat == "day_of_week":
                lbl = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][lbl]
            print(f"    {str(lbl):<15}  {int(r['n']):>6}  {r['win_rate']:>7.1%}  {r['lift']:>6.2f}x")

    # =========================================================================
    # Section D — Train / test validation
    # =========================================================================
    _header("D — TRAIN / TEST VALIDATION  (features that passed B)")

    val_rows = []
    for feat in CONT_FEATURES:
        for tgt in ["mag_win", "call_win", "put_win"]:
            col = f"{tgt}{_tstr(PRIMARY)}"
            tr_auc, _ = mw_auc(train[feat].to_numpy(dtype=float), train[col].to_numpy())
            te_auc, _ = mw_auc(test[feat].to_numpy(dtype=float),  test[col].to_numpy())
            direction_holds = (
                np.isnan(tr_auc) or np.isnan(te_auc) or
                ((tr_auc - 0.5) * (te_auc - 0.5) > 0)  # same side of 0.5
            )
            val_rows.append({
                "feature": feat, "target": tgt,
                "train_auc": round(tr_auc, 4) if not np.isnan(tr_auc) else None,
                "test_auc":  round(te_auc, 4) if not np.isnan(te_auc) else None,
                "direction_holds": direction_holds,
            })

    val_df = pd.DataFrame(val_rows)
    val_df.to_csv(HERE / "06_train_test_validation.csv", index=False)
    print(f"  → Saved {len(val_df)} rows to 06_train_test_validation.csv\n")

    print(f"  {'Feature':<20}  {'Target':<10}  {'Train AUC':>10}  {'Test AUC':>10}  {'Dir OK?':>8}")
    print("  " + "-" * 64)
    for _, r in val_df.sort_values(["feature","target"]).iterrows():
        tr_s = f"{r['train_auc']:.4f}" if r["train_auc"] is not None else "  nan  "
        te_s = f"{r['test_auc']:.4f}"  if r["test_auc"]  is not None else "  nan  "
        flag = "✓" if r["direction_holds"] else "✗ FLIP"
        print(f"  {r['feature']:<20}  {r['target']:<10}  {tr_s:>10}  {te_s:>10}  {flag:>8}")

    # =========================================================================
    # Section E — Session deep-dive (all thresholds)
    # =========================================================================
    _header("E — SESSION EFFECTS  (full analysis window)")
    for tgt in ["mag_win", "call_win", "put_win"]:
        for thresh in THRESHOLDS:
            col = f"{tgt}{_tstr(thresh)}"
            base = df[col].mean()
            grp = df.groupby("hour_utc")[col].agg(["mean","count"]).reset_index()
            grp.columns = ["hour","wr","n"]
            top = grp.sort_values("wr", ascending=False).head(5)
            bot = grp.sort_values("wr").head(3)
            best = top.iloc[0]
            worst = bot.iloc[0]
            print(f"  {col:<18}  base={base:.1%}  "
                  f"best=UTC{int(best['hour']):02d}h {best['wr']:.1%}  "
                  f"worst=UTC{int(worst['hour']):02d}h {worst['wr']:.1%}")

    # =========================================================================
    # Section F — Combination conditions  (multi-threshold)
    # =========================================================================
    _header("F — COMBINATION CONDITIONS  (all thresholds, full analysis window)")

    days_total  = (df.index[-1] - df.index[0]).days
    weeks_total = days_total / 7
    t_p         = _tstr(PRIMARY)
    t_labels    = [f"{t:.1f}".replace(".", "p") for t in THRESHOLDS]   # "1p5","2p0",…
    ts_p        = f"{PRIMARY:.1f}".replace(".", "p")                    # "2p5"
    base_mag    = df[f"mag_win{t_p}"].mean()
    base_call   = df[f"call_win{t_p}"].mean()
    base_put    = df[f"put_win{t_p}"].mean()

    def _cond_multi(mask: pd.Series, label: str) -> dict:
        sub = df[mask]
        if len(sub) < 5:
            return {}
        row: dict = {
            "filter":         label,
            "n_hours":        len(sub),
            "fires_per_week": round(len(sub) / weeks_total, 1),
        }
        for thresh in THRESHOLDS:
            t  = _tstr(thresh)
            ts = f"{thresh:.1f}".replace(".", "p")
            row[f"wr_mag_{ts}"]  = round(sub[f"mag_win{t}"].mean(), 4)
            row[f"wr_call_{ts}"] = round(sub[f"call_win{t}"].mean(), 4)
            row[f"wr_put_{ts}"]  = round(sub[f"put_win{t}"].mean(), 4)
        wr_c   = row[f"wr_call_{ts_p}"]
        wr_p_v = row[f"wr_put_{ts_p}"]
        skew   = wr_c / wr_p_v if wr_p_v > 0.001 else 2.0
        if skew > 1.20 and wr_c > base_call * 1.10:
            stype = "calls"
        elif skew < 0.83 and wr_p_v > base_put * 1.10:
            stype = "puts"
        else:
            stype = "straddle"
        row["call_skew_2p5"] = round(skew, 2)
        row["signal_type"]   = stype
        return row

    cond_rows: list[dict] = []
    _th_hdr = "  ".join(f"{t:.1f}%" for t in THRESHOLDS)

    def add_f(label: str, mask: pd.Series) -> None:
        r = _cond_multi(mask, label)
        if not r:
            return
        cond_rows.append(r)
        mags  = "  ".join(f"{r[f'wr_mag_{ts}']:>5.0%}" for ts in t_labels)
        c_val = r[f"wr_call_{ts_p}"]
        p_val = r[f"wr_put_{ts_p}"]
        print(f"  {label:<55}  {r['fires_per_week']:>5.1f}  {mags}   {c_val:>4.0%}  {p_val:>4.0%}  {r['signal_type']}")

    # Convenience feature aliases
    rv         = df["rv_rank"]
    rvt        = df["rv_trend"]
    bb         = df["bb_width"]
    vz         = df["vol_z"]
    r4h        = df["ret_4h"]
    r1h        = df["ret_1h"]
    r1d        = df["ret_1d"]
    rr         = df["range_ratio"]
    hr         = df["hour_utc"]
    dow        = df["day_of_week"]
    ema168_dev = df["close_vs_ema168"]
    bb_pct     = bb.rank(pct=True)
    no_sat     = (dow != 5)               # exclude Saturday (12% base rate)
    us_open    = hr.isin(range(13, 18))
    asia       = hr.isin(range(0, 5))

    # Print column header
    print(f"\n  {'Condition':<55}  fw/wk  {_th_hdr}   call   put  type  (call/put @ {PRIMARY}%)")
    print("  " + "-" * 120)

    # ── Baseline ─────────────────────────────────────────────────────────────
    add_f("BASELINE  (all bars)",                        pd.Series(True, index=df.index))
    add_f("BASELINE  (no Saturday)",                     no_sat)
    print("  " + "-" * 120)

    # ── Vol regime ────────────────────────────────────────────────────────────
    print()
    _subheader("Vol regime")
    add_f("rv_rank >= 0.60",                             rv >= 0.60)
    add_f("rv_rank >= 0.75",                             rv >= 0.75)
    add_f("rv_rank >= 0.60  +  rv_trend > 0",           (rv >= 0.60) & (rvt > 0))
    add_f("rv_rank >= 0.60  +  no Saturday",            (rv >= 0.60) & no_sat)
    add_f("rv_rank < 0.25   (low vol, reference)",       rv < 0.25)

    # ── Vol spike + regime — frequency sweet spot ─────────────────────────────
    print()
    _subheader("Vol spike + regime  [SWEET SPOT: 3-7/wk]")
    add_f("vol_z >= 1.5  +  rv_rank >= 0.60",           (vz >= 1.5) & (rv >= 0.60))
    add_f("vol_z >= 2.0  +  rv_rank >= 0.60",           (vz >= 2.0) & (rv >= 0.60))
    add_f("vol_z >= 1.5  +  rv_rank >= 0.60  +  no Sat",(vz >= 1.5) & (rv >= 0.60) & no_sat)
    add_f("rv>=0.60  +  vol_z>=1.5  +  range>=1.5",    (rv >= 0.60) & (vz >= 1.5) & (rr >= 1.5))
    add_f("rv>=0.60  +  rv_trend>0  +  range>=1.5",    (rv >= 0.60) & (rvt > 0) & (rr >= 1.5))

    # ── BB width (high = volatile, low = squeeze) ─────────────────────────────
    print()
    _subheader("BB width  (wide = high vol; squeeze = low vol — shown for reference)")
    add_f("bb_width >= 75th pct  (wide)",                bb_pct >= 0.75)
    add_f("bb_width >= 90th pct  (very wide)",           bb_pct >= 0.90)
    add_f("bb_width <= 25th pct  (squeeze, reference)",  bb_pct <= 0.25)

    # ── MTF momentum — high win rate ──────────────────────────────────────────
    print()
    _subheader("MTF momentum  [HIGH WIN RATE — ~2/wk each; ~4/wk combined]")
    add_f("4h >= +1%  +  1h <= -0.5%  (calls pullback)",
          (r4h >= 1.0) & (r1h <= -0.5))
    add_f("4h <= -1%  +  1h >= +0.5%  (puts pullback)",
          (r4h <= -1.0) & (r1h >= 0.5))
    add_f("EITHER MTF pullback  +  rv >= 0.60",
          (((r4h >= 1.0) & (r1h <= -0.5)) | ((r4h <= -1.0) & (r1h >= 0.5))) & (rv >= 0.60))
    add_f("4h >= +1%  +  1h <= -0.5%  +  rv >= 0.60",
          (r4h >= 1.0) & (r1h <= -0.5) & (rv >= 0.60))
    add_f("4h <= -1%  +  1h >= +0.5%  +  rv >= 0.60",
          (r4h <= -1.0) & (r1h >= 0.5) & (rv >= 0.60))
    add_f("rv >= 0.75  +  4h >= +1%  +  1h <= -0.5%",
          (rv >= 0.75) & (r4h >= 1.0) & (r1h <= -0.5))

    # ── Directional — CALLS ───────────────────────────────────────────────────
    print()
    _subheader("Directional — CALLS  (seek wr_call >> wr_put)")
    add_f("ret_4h > +0.5%  +  rv >= 0.60",
          (r4h > 0.5) & (rv >= 0.60))
    add_f("ret_4h > +0.5%  +  vol_z >= 1.5  +  rv >= 0.60",
          (r4h > 0.5) & (vz >= 1.5) & (rv >= 0.60))
    add_f("ret_1d < -2%  +  rv >= 0.60  (oversold bounce)",
          (r1d < -2.0) & (rv >= 0.60))
    add_f("ema168_dev < -2%  +  rv >= 0.60  (crash extension)",
          (ema168_dev < -2.0) & (rv >= 0.60))
    add_f("ret_4h > +1%  +  rv_trend > 0  (momentum + expanding vol)",
          (r4h > 1.0) & (rvt > 0))

    # ── Directional — PUTS ────────────────────────────────────────────────────
    print()
    _subheader("Directional — PUTS  (seek wr_put >> wr_call)")
    add_f("ret_4h < -0.5%  +  rv >= 0.60",
          (r4h < -0.5) & (rv >= 0.60))
    add_f("ret_4h < -0.5%  +  vol_z >= 1.5  +  rv >= 0.60",
          (r4h < -0.5) & (vz >= 1.5) & (rv >= 0.60))
    add_f("ret_1d > +2%  +  rv >= 0.60  (overbought)",
          (r1d > 2.0) & (rv >= 0.60))
    add_f("ema168_dev > +3%  +  rv >= 0.60  (extended above EMA)",
          (ema168_dev > 3.0) & (rv >= 0.60))
    add_f("ret_4h < -1%  +  rv_trend > 0  (sell momentum + expanding vol)",
          (r4h < -1.0) & (rvt > 0))

    # ── Session overlay ────────────────────────────────────────────────────────
    print()
    _subheader("Session overlay")
    add_f("US open (13–17 UTC)",                         us_open)
    add_f("US open  +  rv_rank >= 0.60",                 us_open & (rv >= 0.60))
    add_f("vol_z >= 1.5  +  rv >= 0.60  +  US open",   (vz >= 1.5) & (rv >= 0.60) & us_open)
    add_f("Asia (00–04 UTC)",                            asia)

    # ── Save CSV ───────────────────────────────────────────────────────────────
    cond_df = pd.DataFrame(cond_rows)
    cond_df.to_csv(HERE / "06_conditions.csv", index=False)
    print(f"\n  → Saved {len(cond_df)} conditions to 06_conditions.csv")

    # ── Summary: sweet spot ───────────────────────────────────────────────────
    _header(f"SUMMARY — Sweet spot  (2–10 fires/week), by wr_mag @ {PRIMARY}%")
    sweet = (cond_df[(cond_df["fires_per_week"] >= 2.0) & (cond_df["fires_per_week"] <= 10.0)]
             .sort_values(f"wr_mag_{ts_p}", ascending=False))
    print(f"  {'Condition':<55}  fw/wk  {_th_hdr}   call   put  type")
    print("  " + "-" * 120)
    for _, r in sweet.iterrows():
        mags  = "  ".join(f"{r[f'wr_mag_{ts}']:>5.0%}" for ts in t_labels)
        c_val = r[f"wr_call_{ts_p}"]
        p_val = r[f"wr_put_{ts_p}"]
        print(f"  {r['filter']:<55}  {r['fires_per_week']:>5.1f}  {mags}   {c_val:>4.0%}  {p_val:>4.0%}  {r['signal_type']}")

    # ── Summary: high win-rate conditions ─────────────────────────────────────
    _header(f"SUMMARY — High win-rate (wr_mag >= 55% @ {PRIMARY}%), any frequency")
    highwr = (cond_df[cond_df[f"wr_mag_{ts_p}"] >= 0.55]
              .sort_values(f"wr_mag_{ts_p}", ascending=False))
    print(f"  {'Condition':<55}  fw/wk  {_th_hdr}   call   put  type")
    print("  " + "-" * 120)
    for _, r in highwr.iterrows():
        mags  = "  ".join(f"{r[f'wr_mag_{ts}']:>5.0%}" for ts in t_labels)
        c_val = r[f"wr_call_{ts_p}"]
        p_val = r[f"wr_put_{ts_p}"]
        print(f"  {r['filter']:<55}  {r['fires_per_week']:>5.1f}  {mags}   {c_val:>4.0%}  {p_val:>4.0%}  {r['signal_type']}")

    print("\nDone.")


if __name__ == "__main__":
    main()
