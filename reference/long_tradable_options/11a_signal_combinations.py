"""11a_signal_combinations.py — Signal combination characterisation.

Answers three questions before touching options data:
  1. Is `both` (pullback + vol_burst on same bar) meaningfully better than
     `pullback_only`?
  2. Is `vol_burst_only` good enough to trade independently?
  3. What is the natural cooldown period? (signal clustering behaviour)

Analysis window: 2025-01-01 → 2026-05-15  (full 06 window, for maximum fires)
Options window:  2026-01-01 → 2026-05-12  (fire counts for 11b/11c planning)

Primary signals:
  pullback  — (4h≥+1% + 1h≤-0.5%) OR (4h≤-1% + 1h≥+0.5%)  +  rv_rank≥0.60
  vol_burst — vol_z≥1.5  +  rv_rank≥0.60

Combination masks tested:
  pullback_only — pullback fires, vol_burst does not
  vol_burst_only — vol_burst fires, pullback does not
  both — both fire on same bar
  either — union (pullback OR vol_burst)

Sections
--------
  A  Individual signal baselines (all five named conditions)
  B  Combination win-rate table (all thresholds)
  C  Co-firing proximity: does vol_burst within ±Nh of pullback predict more?
  D  Cooldown simulation: how many entries survive a 4h cooldown per tier?
  E  Options-window fire counts (2026-01-01 → 2026-05-12)

Outputs
-------
  11a_signal_combinations.csv  — one row per combination × threshold
"""
from __future__ import annotations

import sys, types, importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO / "pineforge"))

# ── Import build_features / add_outcomes / config from 06 ────────────────────
_06_path = Path(__file__).resolve().parent / "06_v2_spot_signals.py"
_spec    = importlib.util.spec_from_file_location("sig06", _06_path)
sig06    = types.ModuleType("sig06")
sig06.__file__ = str(_06_path)
sig06.__spec__ = _spec
_spec.loader.exec_module(sig06)  # type: ignore[union-attr]

build_features = sig06.build_features
add_outcomes   = sig06.add_outcomes
PRIMARY        = sig06.PRIMARY
THRESHOLDS     = sig06.THRESHOLDS

import pineforge.data as pfdata

HERE = Path(__file__).resolve().parent

# ── Config ────────────────────────────────────────────────────────────────────
LOAD_FROM    = "2024-01-01"
DATE_START   = "2025-01-01"
DATE_END     = "2026-05-15"
OPT_START    = "2026-01-01"   # options data window
OPT_END      = "2026-05-12"
PROX_HOURS   = [2, 4, 8, 12]  # look-ahead/behind windows for co-firing proximity


# ── Helpers ───────────────────────────────────────────────────────────────────
def _tstr(t: float) -> str:
    return f"_{t:.1f}".replace(".", "p")

def _ts(t: float) -> str:
    return f"{t:.1f}".replace(".", "p")

def _header(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)

def _subheader(title: str) -> None:
    print(f"\n--- {title} ---")


def combo_stats(df: pd.DataFrame, mask: pd.Series, weeks_total: float,
                base_call: float, base_put: float) -> dict:
    """Compute N, fw/wk, win rates at all thresholds, and signal_type for a mask."""
    sub = df[mask]
    if len(sub) < 5:
        return {}
    ts_p = _ts(PRIMARY)
    row: dict = {
        "n_hours":        len(sub),
        "fires_per_week": round(len(sub) / weeks_total, 2),
    }
    for thresh in THRESHOLDS:
        ts = _ts(thresh)
        t  = _tstr(thresh)
        row[f"wr_mag_{ts}"]  = round(float(sub[f"mag_win{t}"].mean()), 4)
        row[f"wr_call_{ts}"] = round(float(sub[f"call_win{t}"].mean()), 4)
        row[f"wr_put_{ts}"]  = round(float(sub[f"put_win{t}"].mean()), 4)
    wr_c = row[f"wr_call_{ts_p}"]
    wr_p = row[f"wr_put_{ts_p}"]
    skew = wr_c / wr_p if wr_p > 0.001 else 2.0
    if skew > 1.20 and wr_c > base_call * 1.10:
        stype = "calls"
    elif skew < 0.83 and wr_p > base_put * 1.10:
        stype = "puts"
    else:
        stype = "straddle"
    row["call_skew_2p5"] = round(skew, 2)
    row["signal_type"]   = stype
    return row


def cooldown_count(mask: pd.Series, hours: int = 4) -> int:
    """Count entries remaining after applying a `hours`-hour cooldown."""
    fires = mask[mask].index
    if len(fires) == 0:
        return 0
    count = 0
    last_entry = pd.Timestamp("2000-01-01", tz="UTC")
    for ts in fires:
        if (ts - last_entry).total_seconds() / 3600 >= hours:
            count += 1
            last_entry = ts
    return count


# =============================================================================
# Main
# =============================================================================
def main() -> None:

    # ── Load data ─────────────────────────────────────────────────────────────
    print("Loading BTCUSDT 1h data …")
    df_raw = pfdata.load("BTCUSDT", "1h")
    df_raw = df_raw[df_raw.index >= pd.Timestamp(LOAD_FROM, tz="UTC")]

    # ── Build features + outcomes ─────────────────────────────────────────────
    print("Computing features …")
    df = build_features(df_raw)
    df = add_outcomes(df)
    df = df[df.index >= pd.Timestamp(DATE_START, tz="UTC")]
    df = df[df.index <= pd.Timestamp(DATE_END,   tz="UTC")]
    df = df.dropna(subset=[f"mag_win{_tstr(PRIMARY)}"])

    days_total  = (df.index[-1] - df.index[0]).days
    weeks_total = days_total / 7
    print(f"  {len(df):,} bars  {df.index[0].date()} → {df.index[-1].date()}  "
          f"({weeks_total:.1f} weeks)")

    # ── Feature aliases ───────────────────────────────────────────────────────
    rv  = df["rv_rank"]
    vz  = df["vol_z"]
    r4h = df["ret_4h"]
    r1h = df["ret_1h"]
    dow = df["day_of_week"]
    r1d = df["ret_1d"]
    no_sat = (dow != 5)

    mtf_calls = (r4h >= 1.0) & (r1h <= -0.5)
    mtf_puts  = (r4h <= -1.0) & (r1h >= 0.5)

    # Primary signal masks
    pullback_mask   = (mtf_calls | mtf_puts) & (rv >= 0.60)
    vol_burst_mask  = (vz >= 1.5) & (rv >= 0.60)

    # Combination masks
    pb_only    = pullback_mask & ~vol_burst_mask
    vb_only    = vol_burst_mask & ~pullback_mask
    both_mask  = pullback_mask & vol_burst_mask
    either_mask = pullback_mask | vol_burst_mask

    # Also define sub-signals for Section A
    bull_pb = mtf_calls & (rv >= 0.60)
    bear_pb = mtf_puts  & (rv >= 0.60)
    bear_burst = (r4h < -0.5) & (vz >= 1.5) & (rv >= 0.60)
    vol_surge  = (vz >= 2.0) & (rv >= 0.60)

    t_p    = _tstr(PRIMARY)
    ts_p   = _ts(PRIMARY)
    t_lbls = [_ts(t) for t in THRESHOLDS]

    base_mag  = float(df[f"mag_win{t_p}"].mean())
    base_call = float(df[f"call_win{t_p}"].mean())
    base_put  = float(df[f"put_win{t_p}"].mean())

    _th_hdr = "  ".join(f"{t:.1f}%" for t in THRESHOLDS)

    def print_row(label: str, mask: pd.Series) -> None:
        r = combo_stats(df, mask, weeks_total, base_call, base_put)
        if not r:
            print(f"  {label:<60}  (too few)")
            return
        mags  = "  ".join(f"{r[f'wr_mag_{ts}']:>5.0%}" for ts in t_lbls)
        c_val = r[f"wr_call_{ts_p}"]
        p_val = r[f"wr_put_{ts_p}"]
        print(f"  {label:<60}  {r['fires_per_week']:>5.1f}  {mags}   "
              f"{c_val:>4.0%}  {p_val:>4.0%}  {r['signal_type']}")
        return r

    col_hdr = f"  {'Condition':<60}  fw/wk  {_th_hdr}   call   put  type"

    # =========================================================================
    # Section A — Individual signal baselines
    # =========================================================================
    _header("A — INDIVIDUAL SIGNALS  (full analysis window, all thresholds)")
    print(col_hdr)
    print("  " + "-" * 120)
    print_row("BASELINE  (all bars, no Saturday)",        pd.Series(True, index=df.index) & no_sat)
    print("  " + "-" * 120)

    named: list[tuple[str, pd.Series]] = [
        ("pullback  (EITHER MTF + rv≥0.60)",              pullback_mask),
        ("  bull_pullback  (4h≥+1% + 1h≤-0.5% + rv≥0.60)", bull_pb),
        ("  bear_pullback  (4h≤-1% + 1h≥+0.5% + rv≥0.60)", bear_pb),
        ("vol_burst  (vol_z≥1.5 + rv≥0.60)",              vol_burst_mask),
        ("  vol_surge    (vol_z≥2.0 + rv≥0.60)",          vol_surge),
        ("  bear_burst   (4h<-0.5% + vol_z≥1.5 + rv≥0.60)", bear_burst),
    ]
    for label, mask in named:
        print_row(label, mask)

    # =========================================================================
    # Section B — Combination win-rate table
    # =========================================================================
    _header("B — COMBINATION MASKS  (pullback × vol_burst)")
    print(col_hdr)
    print("  " + "-" * 120)

    combo_defs: list[tuple[str, pd.Series]] = [
        ("pullback_only  (pullback fires, vol_burst does not)", pb_only),
        ("vol_burst_only  (vol_burst fires, pullback does not)", vb_only),
        ("both  (pullback AND vol_burst on same bar)",           both_mask),
        ("either  (pullback OR vol_burst)",                      either_mask),
    ]

    combo_rows: list[dict] = []
    for label, mask in combo_defs:
        r = combo_stats(df, mask, weeks_total, base_call, base_put)
        if not r:
            print(f"  {label:<60}  (too few)")
            continue
        r["combination"] = label
        combo_rows.append(r)
        mags  = "  ".join(f"{r[f'wr_mag_{ts}']:>5.0%}" for ts in t_lbls)
        c_val = r[f"wr_call_{ts_p}"]
        p_val = r[f"wr_put_{ts_p}"]
        print(f"  {label:<60}  {r['fires_per_week']:>5.1f}  {mags}   "
              f"{c_val:>4.0%}  {p_val:>4.0%}  {r['signal_type']}")

    # Overlap summary
    n_pb  = int(pullback_mask.sum())
    n_vb  = int(vol_burst_mask.sum())
    n_both = int(both_mask.sum())
    print()
    print(f"  Overlap: pullback fires={n_pb}  vol_burst fires={n_vb}  "
          f"simultaneous={n_both}  ({n_both/n_pb*100:.1f}% of pullback, "
          f"{n_both/n_vb*100:.1f}% of vol_burst)")

    # =========================================================================
    # Section C — Co-firing proximity analysis
    # =========================================================================
    _header("C — CO-FIRING PROXIMITY  (does vol_burst within ±Nh of pullback predict more?)")
    print(f"  Does having a vol_burst fire near a pullback entry improve outcome?\n")

    pb_idx = pullback_mask[pullback_mask].index
    col = f"mag_win{t_p}"

    print(f"  {'Proximity window':<30}  {'N pullback fires':>17}  "
          f"{'wr_mag@2.5% (nearby)':>22}  {'wr_mag@2.5% (no nearby)':>24}")
    print("  " + "-" * 100)

    prox_rows: list[dict] = []
    for h in PROX_HOURS:
        # For each pullback fire, check if any vol_burst fired within ±h hours
        nearby_flags = []
        for ts in pb_idx:
            window_start = ts - pd.Timedelta(hours=h)
            window_end   = ts + pd.Timedelta(hours=h)
            nearby = vol_burst_mask.loc[window_start:window_end].any()
            nearby_flags.append(nearby)
        nearby_series = pd.Series(nearby_flags, index=pb_idx, dtype=bool)

        # Win rates for near vs far pullback fires
        pb_fires = df.loc[pb_idx, col]
        near_wr  = pb_fires[nearby_series].mean()
        far_wr   = pb_fires[~nearby_series].mean()
        n_near   = int(nearby_series.sum())
        n_far    = int((~nearby_series).sum())

        label = f"± {h}h"
        print(f"  {label:<30}  n_near={n_near:>5}  n_far={n_far:>5}  "
              f"wr_near={near_wr:.1%}  wr_far={far_wr:.1%}  "
              f"lift={near_wr/far_wr:.2f}x" if far_wr > 0 else
              f"  {label:<30}  n_near={n_near:>5}  n_far={n_far:>5}  "
              f"wr_near={near_wr:.1%}  wr_far={far_wr:.1%}  lift=N/A")
        prox_rows.append({
            "prox_hours": h,
            "n_pullback_near": n_near,
            "n_pullback_far":  n_far,
            "wr_near": round(near_wr, 4) if not np.isnan(near_wr) else None,
            "wr_far":  round(far_wr,  4) if not np.isnan(far_wr)  else None,
        })

    # Also the symmetric: does pullback nearby improve vol_burst fires?
    print()
    _subheader("Symmetric: does pullback nearby improve vol_burst fires?")
    vb_idx = vol_burst_mask[vol_burst_mask].index
    print(f"  {'Proximity window':<30}  {'N vb fires':>12}  "
          f"{'wr_near':>10}  {'wr_far':>10}  {'lift':>8}")
    print("  " + "-" * 80)
    for h in PROX_HOURS:
        nearby_flags = []
        for ts in vb_idx:
            window_start = ts - pd.Timedelta(hours=h)
            window_end   = ts + pd.Timedelta(hours=h)
            nearby = pullback_mask.loc[window_start:window_end].any()
            nearby_flags.append(nearby)
        nearby_series = pd.Series(nearby_flags, index=vb_idx, dtype=bool)
        vb_fires = df.loc[vb_idx, col]
        near_wr  = vb_fires[nearby_series].mean()
        far_wr   = vb_fires[~nearby_series].mean()
        n_near   = int(nearby_series.sum())
        n_far    = int((~nearby_series).sum())
        lift     = near_wr / far_wr if far_wr > 0 else float("nan")
        label    = f"± {h}h"
        print(f"  {label:<30}  n_near={n_near:>5}  n_far={n_far:>5}  "
              f"wr_near={near_wr:.1%}  wr_far={far_wr:.1%}  lift={lift:.2f}x")

    # =========================================================================
    # Section D — Cooldown simulation
    # =========================================================================
    _header("D — COOLDOWN SIMULATION  (4h cooldown per tier)")
    print(f"  How many entries survive after applying a 4h cooldown to each signal tier?\n")
    print(f"  {'Signal':<40}  {'Raw fires':>10}  {'After 4h CD':>12}  {'Kept %':>8}  "
          f"{'After CD fw/wk':>15}")
    print("  " + "-" * 90)

    for label, mask in [
        ("pullback",       pullback_mask),
        ("vol_burst",      vol_burst_mask),
        ("either  (shared cooldown)", either_mask),
        ("both",           both_mask),
    ]:
        raw   = int(mask.sum())
        after = cooldown_count(mask, hours=4)
        kept  = after / raw if raw > 0 else 0.0
        fw_wk = after / weeks_total
        print(f"  {label:<40}  {raw:>10,}  {after:>12,}  {kept:>7.0%}  {fw_wk:>14.1f}")

    print()
    print(f"  Note: 'either (shared cooldown)' = one combined queue for both signals.")
    print(f"  'pullback' + 'vol_burst' run as independent queues = both rates above apply separately.")

    # 2h cooldown for comparison
    print()
    _subheader("Same table with 2h cooldown")
    print(f"  {'Signal':<40}  {'Raw fires':>10}  {'After 2h CD':>12}  {'Kept %':>8}  "
          f"{'After CD fw/wk':>15}")
    print("  " + "-" * 90)
    for label, mask in [
        ("pullback",       pullback_mask),
        ("vol_burst",      vol_burst_mask),
        ("either  (shared cooldown)", either_mask),
    ]:
        raw   = int(mask.sum())
        after = cooldown_count(mask, hours=2)
        kept  = after / raw if raw > 0 else 0.0
        fw_wk = after / weeks_total
        print(f"  {label:<40}  {raw:>10,}  {after:>12,}  {kept:>7.0%}  {fw_wk:>14.1f}")

    # =========================================================================
    # Section E — Options-window fire counts
    # =========================================================================
    _header(f"E — OPTIONS-WINDOW FIRE COUNTS  ({OPT_START} → {OPT_END})")
    opt_df = df[(df.index >= pd.Timestamp(OPT_START, tz="UTC")) &
                (df.index <= pd.Timestamp(OPT_END,   tz="UTC"))]
    opt_days  = (opt_df.index[-1] - opt_df.index[0]).days
    opt_weeks = opt_days / 7
    print(f"  {len(opt_df):,} bars  {opt_df.index[0].date()} → {opt_df.index[-1].date()}  "
          f"({opt_weeks:.1f} weeks)\n")

    opt_rv  = opt_df["rv_rank"]
    opt_vz  = opt_df["vol_z"]
    opt_r4h = opt_df["ret_4h"]
    opt_r1h = opt_df["ret_1h"]
    opt_dow = opt_df["day_of_week"]

    opt_mtf_calls = (opt_r4h >= 1.0) & (opt_r1h <= -0.5)
    opt_mtf_puts  = (opt_r4h <= -1.0) & (opt_r1h >= 0.5)
    opt_pb   = (opt_mtf_calls | opt_mtf_puts) & (opt_rv >= 0.60)
    opt_vb   = (opt_vz >= 1.5) & (opt_rv >= 0.60)
    opt_both = opt_pb & opt_vb
    opt_ei   = opt_pb | opt_vb

    print(f"  {'Signal':<45}  {'Fires':>8}  {'fw/wk':>7}  {'After 4h CD':>12}  "
          f"{'CD fw/wk':>10}")
    print("  " + "-" * 92)
    for label, mask in [
        ("pullback",              opt_pb),
        ("vol_burst",             opt_vb),
        ("both  (simultaneous)",  opt_both),
        ("either  (union)",       opt_ei),
    ]:
        raw   = int(mask.sum())
        after = cooldown_count(mask, hours=4)
        fw_raw = raw   / opt_weeks
        fw_cd  = after / opt_weeks
        print(f"  {label:<45}  {raw:>8,}  {fw_raw:>7.1f}  {after:>12,}  {fw_cd:>10.1f}")

    # =========================================================================
    # Save CSV
    # =========================================================================
    save_rows = []
    all_named = [
        ("baseline_no_sat",  no_sat),
        ("pullback",         pullback_mask),
        ("bull_pullback",    bull_pb),
        ("bear_pullback",    bear_pb),
        ("vol_burst",        vol_burst_mask),
        ("vol_surge",        vol_surge),
        ("bear_burst",       bear_burst),
        ("pullback_only",    pb_only),
        ("vol_burst_only",   vb_only),
        ("both",             both_mask),
        ("either",           either_mask),
    ]
    for name, mask in all_named:
        r = combo_stats(df, mask, weeks_total, base_call, base_put)
        if r:
            r["combination"] = name
            save_rows.append(r)

    out_df = pd.DataFrame(save_rows)
    out_df.to_csv(HERE / "11a_signal_combinations.csv", index=False)
    print(f"\n  → Saved {len(out_df)} rows to 11a_signal_combinations.csv")
    print("\nDone.")


if __name__ == "__main__":
    main()
