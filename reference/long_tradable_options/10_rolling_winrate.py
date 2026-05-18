"""10_rolling_winrate.py — Rolling 12-week win-rate stability for named conditions.

For each named entry condition, compute win rate (mag_win @ 2.5%) over every
rolling 12-week window, shifted by 1 week, across the full analysis window
(2025-01-01 → 2026-05-15).

Produces:
  - Console table: rolling estimates with Wilson 95% CI
  - 10_rolling_winrate.svg   — time-series stability chart (6-panel)
  - 10_rolling_current.svg   — trailing-12wk vs full-period summary bar chart

Statistical notes
-----------------
  * Wilson score interval used throughout (better than normal approximation at
    extreme proportions or small N).
  * Windows with N < MIN_FIRES are flagged "too few" and drawn dotted.
  * Trend arrow: slope of OLS line through the last 8 reliable windows.
"""
from __future__ import annotations

import sys, types, importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import matplotlib.patches as mpatches

_REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO / "pineforge"))

# ── Import build_features / add_outcomes from 06 ─────────────────────────────
_06_path = Path(__file__).resolve().parent / "06_v2_spot_signals.py"
_spec = importlib.util.spec_from_file_location("sig06", _06_path)
sig06 = types.ModuleType("sig06")
sig06.__file__ = str(_06_path)
sig06.__spec__ = _spec
_spec.loader.exec_module(sig06)  # type: ignore[union-attr]

build_features = sig06.build_features
add_outcomes   = sig06.add_outcomes
PRIMARY        = sig06.PRIMARY

import pineforge.data as pfdata

HERE = Path(__file__).resolve().parent

# ── Config ────────────────────────────────────────────────────────────────────
LOAD_FROM     = "2024-01-01"
DATE_START    = "2025-01-01"
DATE_END      = "2026-05-15"
WINDOW_WEEKS  = 12        # rolling window length
STEP_WEEKS    = 1         # slide interval
MIN_FIRES     = 8         # min fires for a reliable estimate; below → dotted line
TREND_WINDOWS = 8         # last N reliable windows used for OLS trend slope

# ── Palette ───────────────────────────────────────────────────────────────────
BG     = "#1c1c1e"; CARD   = "#2c2c2e"; FG     = "#f2f2f7"; SUBTLE = "#8e8e93"
GREEN  = "#30d158"; YELLOW = "#ffd60a"; ORANGE = "#ff9f0a"; RED    = "#ff453a"
BLUE   = "#0a84ff"; TEAL   = "#5ac8fa"; PURPLE = "#bf5af2"; PINK   = "#ff375f"

# ── Helpers ───────────────────────────────────────────────────────────────────
def _tstr(t: float) -> str:
    return f"_{t:.1f}".replace(".", "p")

def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval. Returns (lower, upper) as fractions."""
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    denom  = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)

def ols_slope(y: np.ndarray) -> float:
    """Slope of OLS fit through y (x = 0,1,…,n-1). Returns slope per window."""
    n = len(y)
    if n < 2:
        return 0.0
    x = np.arange(n, dtype=float)
    x -= x.mean()
    return float(np.dot(x, y) / np.dot(x, x))

def trend_arrow(slope: float, threshold: float = 0.005) -> str:
    if slope >  threshold: return "↑ improving"
    if slope < -threshold: return "↓ degrading"
    return "→ stable"

# ── Named conditions ──────────────────────────────────────────────────────────
# Each entry: (id, label_short, label_long, color, mask_fn(df))
# mask_fn receives the full df with features already computed.

def _masks(df: pd.DataFrame) -> list[tuple[str, str, str, str, pd.Series]]:
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
    no_sat     = (dow != 5)
    bb_pct     = bb.rank(pct=True)

    mtf_calls = (r4h >= 1.0) & (r1h <= -0.5)
    mtf_puts  = (r4h <= -1.0) & (r1h >= 0.5)

    TRUE = pd.Series(True, index=df.index)

    return [
        ("baseline",     "Baseline",        "Baseline  (no Saturday)",                   SUBTLE, no_sat),
        ("vol_regime",   "vol_regime",      "vol_regime  (rv_rank≥0.60 + no Sat)",       BLUE,   (rv >= 0.60) & no_sat),
        ("vol_burst",    "vol_burst",       "vol_burst  (vol_z≥1.5 + rv≥0.60)",         YELLOW, (vz >= 1.5) & (rv >= 0.60)),
        ("vol_surge",    "vol_surge",       "vol_surge  (vol_z≥2.0 + rv≥0.60)",         ORANGE, (vz >= 2.0) & (rv >= 0.60)),
        ("pullback",     "pullback",        "pullback  (EITHER MTF + rv≥0.60)",          GREEN,  (mtf_calls | mtf_puts) & (rv >= 0.60)),
        ("bull_pullback","bull_pullback",   "bull_pullback  (4h≥+1% + 1h≤-0.5% + rv≥0.60)", TEAL, mtf_calls & (rv >= 0.60)),
        ("bear_pullback","bear_pullback",   "bear_pullback  (4h≤-1% + 1h≥+0.5% + rv≥0.60)", PINK, mtf_puts & (rv >= 0.60)),
        ("bear_burst",   "bear_burst",      "bear_burst  (4h<-0.5% + vol_z≥1.5 + rv≥0.60)", PURPLE, (r4h < -0.5) & (vz >= 1.5) & (rv >= 0.60)),
    ]


# ── Rolling computation ────────────────────────────────────────────────────────
def compute_rolling(df: pd.DataFrame, masks: list) -> dict[str, pd.DataFrame]:
    """
    For each named condition, compute rolling WINDOW_WEEKS win-rate statistics.
    Returns dict: cond_id → DataFrame with columns
        [window_end, n_fires, win_rate, ci_lo, ci_hi, call_wr, put_wr]
    """
    t_p  = _tstr(PRIMARY)
    mag_col  = f"mag_win{t_p}"
    call_col = f"call_win{t_p}"
    put_col  = f"put_win{t_p}"

    # Build list of (window_start, window_end) timestamps
    start_ts = pd.Timestamp(DATE_START, tz="UTC")
    end_ts   = pd.Timestamp(DATE_END,   tz="UTC")
    step     = pd.Timedelta(weeks=STEP_WEEKS)
    wlen     = pd.Timedelta(weeks=WINDOW_WEEKS)

    windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    w = start_ts
    while True:
        we = w + wlen
        if we > end_ts:
            break
        windows.append((w, we))
        w += step

    results: dict[str, pd.DataFrame] = {}

    for cond_id, _, _, _, mask in masks:
        rows = []
        sub_all = df[mask]          # apply condition mask once
        for ws, we in windows:
            sub = sub_all[(sub_all.index >= ws) & (sub_all.index < we)]
            n   = len(sub)
            if n == 0:
                rows.append({"window_end": we, "n_fires": 0,
                             "win_rate": np.nan, "ci_lo": np.nan, "ci_hi": np.nan,
                             "call_wr": np.nan, "put_wr": np.nan})
                continue
            k       = int(sub[mag_col].sum())
            wr      = k / n
            lo, hi  = wilson_ci(k, n)
            call_wr = sub[call_col].mean()
            put_wr  = sub[put_col].mean()
            rows.append({"window_end": we, "n_fires": n,
                         "win_rate": wr, "ci_lo": lo, "ci_hi": hi,
                         "call_wr": call_wr, "put_wr": put_wr})
        results[cond_id] = pd.DataFrame(rows)

    return results


# ── Console output ─────────────────────────────────────────────────────────────
def print_rolling_table(results: dict[str, pd.DataFrame], masks: list,
                        df: pd.DataFrame) -> None:
    t_p = _tstr(PRIMARY)
    mag_col = f"mag_win{t_p}"

    print()
    print("=" * 80)
    print(f"  ROLLING {WINDOW_WEEKS}-WEEK WIN RATES  (mag_win @ {PRIMARY}%,  step={STEP_WEEKS}wk)")
    print("  Showing last 10 windows + summary.  CI = Wilson 95%.")
    print("=" * 80)

    for cond_id, _, label_long, _, mask in masks:
        rdf = results[cond_id]
        full_sub = df[mask]
        full_n   = len(full_sub)
        full_wr  = full_sub[mag_col].mean() if full_n > 0 else np.nan
        full_lo, full_hi = wilson_ci(int(full_sub[mag_col].sum()), full_n)

        # Trailing 12-week (last window)
        last_valid = rdf[rdf["n_fires"] >= MIN_FIRES].tail(1)

        print(f"\n  {label_long}")
        print(f"  {'Window end':<12}  {'N':>5}  {'WinRate':>8}  {'CI 95%':>18}  {'call':>6}  {'put':>6}")
        print("  " + "-" * 64)

        recent = rdf.tail(10)
        for _, r in recent.iterrows():
            n = int(r["n_fires"])
            if n < MIN_FIRES:
                flag = "  (n<8)"
                wr_s = ci_s = c_s = p_s = "   —  "
            else:
                flag = ""
                wr_s = f"{r['win_rate']:>7.1%}"
                ci_s = f"[{r['ci_lo']:>5.1%}–{r['ci_hi']:>5.1%}]"
                c_s  = f"{r['call_wr']:>5.1%}"
                p_s  = f"{r['put_wr']:>5.1%}"
            dt = r["window_end"].strftime("%Y-%m-%d")
            print(f"  {dt:<12}  {n:>5}  {wr_s}  {ci_s:>18}  {c_s}  {p_s}{flag}")

        # OLS trend over last TREND_WINDOWS reliable windows
        reliable = rdf[rdf["n_fires"] >= MIN_FIRES]["win_rate"].dropna().values
        slope = ols_slope(reliable[-TREND_WINDOWS:]) if len(reliable) >= 2 else 0.0
        t12_wr  = last_valid.iloc[0]["win_rate"]  if len(last_valid) > 0 else np.nan
        t12_lo  = last_valid.iloc[0]["ci_lo"]     if len(last_valid) > 0 else np.nan
        t12_hi  = last_valid.iloc[0]["ci_hi"]     if len(last_valid) > 0 else np.nan

        print(f"\n  Full-period:    N={full_n:>5,}  WR={full_wr:.1%}  CI=[{full_lo:.1%}–{full_hi:.1%}]")
        if not np.isnan(t12_wr):
            print(f"  Trailing 12wk:  N={int(last_valid.iloc[0]['n_fires']):>5}  WR={t12_wr:.1%}  CI=[{t12_lo:.1%}–{t12_hi:.1%}]")
        print(f"  Trend ({TREND_WINDOWS} windows): slope={slope:+.4f}/wk  {trend_arrow(slope)}")


# ── Chart 1: Rolling win-rate time series (6-panel) ──────────────────────────
def chart_rolling_timeseries(results: dict[str, pd.DataFrame], masks: list,
                             df: pd.DataFrame) -> None:
    t_p    = _tstr(PRIMARY)
    mag_col = f"mag_win{t_p}"

    # 6-panel: skip vol_surge and bull_pullback in main chart (low N, too noisy)
    panel_ids = ["pullback", "bear_pullback", "vol_burst", "bear_burst",
                 "vol_regime", "baseline"]
    panel_data = {m[0]: m for m in masks}

    fig, axes = plt.subplots(2, 3, figsize=(15, 9), facecolor=BG)
    fig.suptitle(
        f"Rolling {WINDOW_WEEKS}-week Win Rate (mag_win @ {PRIMARY}%)  |  step = {STEP_WEEKS} week\n"
        "Shaded band = Wilson 95% CI   |   Dotted = N < 8 fires   |   Dashed = full-period WR",
        color=FG, fontsize=11, y=0.98)

    for ax, cond_id in zip(axes.flat, panel_ids):
        ax.set_facecolor(CARD)
        for sp in ax.spines.values():
            sp.set_edgecolor(SUBTLE)
        ax.tick_params(colors=FG, labelsize=8)

        cond_id, _, label_long, color, mask = panel_data[cond_id]
        rdf = results[cond_id]

        # Full-period win rate (horizontal reference)
        full_sub = df[mask]
        full_wr  = full_sub[mag_col].mean() if len(full_sub) > 0 else np.nan
        ax.axhline(full_wr, color=color, linewidth=1.0, linestyle="--",
                   alpha=0.55, label=f"full-period {full_wr:.0%}", zorder=2)

        # Baseline reference
        if cond_id != "baseline":
            base_wr = df[df["day_of_week"] != 5][mag_col].mean()
            ax.axhline(base_wr, color=SUBTLE, linewidth=0.8, linestyle=":",
                       alpha=0.6, zorder=2)

        # Split into reliable vs unreliable windows
        dates  = [r["window_end"] for _, r in rdf.iterrows()]
        wrs    = rdf["win_rate"].values
        ci_lo  = rdf["ci_lo"].values
        ci_hi  = rdf["ci_hi"].values
        ns     = rdf["n_fires"].values

        reliable = ns >= MIN_FIRES

        # Reliable: solid line + CI band
        rel_dates = [d for d, r in zip(dates, reliable) if r]
        rel_wr    = wrs[reliable]
        rel_lo    = ci_lo[reliable]
        rel_hi    = ci_hi[reliable]

        if len(rel_dates) > 0:
            ax.plot(rel_dates, rel_wr, color=color, linewidth=1.8, zorder=4)
            ax.fill_between(rel_dates, rel_lo, rel_hi,
                            color=color, alpha=0.15, zorder=3)

        # Unreliable: dotted + no band
        for i, (d, r, wr) in enumerate(zip(dates, reliable, wrs)):
            if not r and not np.isnan(wr):
                ax.plot([d], [wr], "o", color=SUBTLE, markersize=3,
                        alpha=0.5, zorder=3)

        # Shade the "recent 3 weeks" region
        recent_start = pd.Timestamp("2026-04-26", tz="UTC")
        ax.axvspan(recent_start, pd.Timestamp(DATE_END, tz="UTC"),
                   color=ORANGE, alpha=0.07, zorder=1, label="recent 3wk")

        # Y-axis
        ax.set_ylim(0.0, 1.05)
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
        ax.yaxis.set_major_locator(matplotlib.ticker.MultipleLocator(0.10))
        ax.grid(axis="y", color=SUBTLE, alpha=0.2, zorder=1)

        # Legend: full-period WR label
        n_total = int(rdf["n_fires"].sum())
        ax.set_title(label_long, color=FG, fontsize=8.5, pad=6)
        ax.text(0.02, 0.04, f"total fires: {n_total:,}",
                transform=ax.transAxes, color=SUBTLE, fontsize=7.5)

        # Format x ticks (just quarter labels)
        ax.xaxis.set_major_locator(matplotlib.dates.MonthLocator(bymonth=[1, 4, 7, 10]))
        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %Y"))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=25, ha="right", fontsize=7.5)

    # Legend for shaded region
    orange_patch = mpatches.Patch(color=ORANGE, alpha=0.3, label="recent 3 weeks")
    fig.legend(handles=[orange_patch], loc="lower right",
               framealpha=0.2, labelcolor=FG, fontsize=8,
               facecolor=CARD, edgecolor=SUBTLE)

    fig.tight_layout(rect=[0, 0.0, 1, 0.96])
    path = HERE / "10_rolling_winrate.svg"
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  Saved 10_rolling_winrate.svg")


# ── Chart 2: Trailing-12wk vs full-period summary bar chart ──────────────────
def chart_rolling_current(results: dict[str, pd.DataFrame], masks: list,
                          df: pd.DataFrame) -> None:
    t_p    = _tstr(PRIMARY)
    mag_col = f"mag_win{t_p}"

    cond_order = ["baseline", "vol_regime", "vol_burst", "vol_surge",
                  "pullback", "bull_pullback", "bear_pullback", "bear_burst"]

    mask_by_id = {m[0]: m for m in masks}
    labels, full_wrs, t12_wrs, t12_los, t12_his, colors = [], [], [], [], [], []

    for cid in cond_order:
        _, short_lbl, _, color, mask = mask_by_id[cid]
        rdf  = results[cid]
        sub  = df[mask]
        full_wr = sub[mag_col].mean() if len(sub) > 0 else np.nan

        last = rdf[rdf["n_fires"] >= MIN_FIRES].tail(1)
        if len(last) == 0:
            t12_wr = np.nan; t12_lo = np.nan; t12_hi = np.nan
        else:
            t12_wr = last.iloc[0]["win_rate"]
            t12_lo = last.iloc[0]["ci_lo"]
            t12_hi = last.iloc[0]["ci_hi"]

        labels.append(short_lbl)
        full_wrs.append(full_wr)
        t12_wrs.append(t12_wr)
        t12_los.append(t12_lo)
        t12_his.append(t12_hi)
        colors.append(color)

    n   = len(labels)
    x   = np.arange(n)
    w   = 0.36

    fig, ax = plt.subplots(figsize=(13, 6.5), facecolor=BG)
    ax.set_facecolor(CARD)
    for sp in ax.spines.values():
        sp.set_edgecolor(SUBTLE)
    ax.tick_params(colors=FG, labelsize=9)

    # Full-period bars
    ax.bar(x - w/2, full_wrs, width=w, color=[c for c in colors],
           alpha=0.45, label="Full period  (Jan 2025 → May 2026)", zorder=3)

    # Trailing-12wk bars with CI error bars
    t12_err_lo = [wr - lo if not np.isnan(wr) else 0 for wr, lo in zip(t12_wrs, t12_los)]
    t12_err_hi = [hi - wr if not np.isnan(wr) else 0 for wr, hi in zip(t12_wrs, t12_his)]
    valid_t12  = [wr if not np.isnan(wr) else 0.0 for wr in t12_wrs]

    for i, (wr, lo_err, hi_err, col) in enumerate(
            zip(valid_t12, t12_err_lo, t12_err_hi, colors)):
        if wr == 0.0:
            ax.bar(x[i] + w/2, 0.01, width=w, color=SUBTLE, alpha=0.3, zorder=3)
            ax.text(x[i] + w/2, 0.015, "n/a", ha="center", color=SUBTLE, fontsize=7)
        else:
            ax.bar(x[i] + w/2, wr, width=w, color=col, alpha=0.85, zorder=3)
            ax.errorbar(x[i] + w/2, wr,
                        yerr=[[lo_err], [hi_err]],
                        fmt="none", color=FG, capsize=4, linewidth=1.2, zorder=5)

    # Value labels on top of bars
    for i, wr in enumerate(full_wrs):
        if not np.isnan(wr):
            ax.text(x[i] - w/2, wr + 0.012, f"{wr:.0%}",
                    ha="center", color=FG, fontsize=7.5)
    for i, wr in enumerate(t12_wrs):
        if not np.isnan(wr):
            ax.text(x[i] + w/2, wr + 0.012, f"{wr:.0%}",
                    ha="center", color=FG, fontsize=7.5)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9.5, color=FG)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("mag_win @ 2.5%", color=FG, fontsize=10)
    ax.set_title(
        f"Trailing {WINDOW_WEEKS}-Week Win Rate vs Full-Period  (mag_win @ {PRIMARY}%)\n"
        "Error bars = Wilson 95% CI on trailing estimate  |  n/a = fewer than 8 fires in window",
        color=FG, fontsize=11, pad=12)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.grid(axis="y", color=SUBTLE, alpha=0.25, zorder=1)

    # Legend
    full_patch  = mpatches.Patch(color=SUBTLE, alpha=0.5,
                                  label=f"Full period  (Jan 2025 → May 2026)")
    trail_patch = mpatches.Patch(color=GREEN, alpha=0.85,
                                  label=f"Trailing {WINDOW_WEEKS} weeks  (most recent window ≥ 8 fires)")
    ax.legend(handles=[full_patch, trail_patch], loc="upper right",
              framealpha=0.2, labelcolor=FG, fontsize=8.5,
              facecolor=CARD, edgecolor=SUBTLE)

    fig.tight_layout()
    path = HERE / "10_rolling_current.svg"
    fig.savefig(path, format="svg", bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  Saved 10_rolling_current.svg")


# ── Summary table ─────────────────────────────────────────────────────────────
def print_summary(results: dict[str, pd.DataFrame], masks: list,
                  df: pd.DataFrame) -> None:
    t_p    = _tstr(PRIMARY)
    mag_col = f"mag_win{t_p}"

    print()
    print("=" * 80)
    print(f"  SUMMARY — Full-period vs Trailing {WINDOW_WEEKS}-week  (mag_win @ {PRIMARY}%)")
    print("=" * 80)
    print(f"  {'Condition':<22}  {'Full WR':>7}  {'Full CI':>14}  "
          f"{'Trail WR':>8}  {'Trail CI':>14}  {'Trend':>14}  {'fw/wk':>6}")
    print("  " + "-" * 92)

    for cond_id, short_lbl, _, _, mask in masks:
        rdf     = results[cond_id]
        sub     = df[mask]
        full_n  = len(sub)
        full_k  = int(sub[mag_col].sum())
        full_wr = full_k / full_n if full_n > 0 else np.nan
        f_lo, f_hi = wilson_ci(full_k, full_n)

        reliable = rdf[rdf["n_fires"] >= MIN_FIRES]
        last     = reliable.tail(1)
        if len(last) == 0:
            t_wr_s = "  n/a  "; t_ci_s = "      n/a     "; t_n = 0
        else:
            t_wr = last.iloc[0]["win_rate"]
            t_lo = last.iloc[0]["ci_lo"]
            t_hi = last.iloc[0]["ci_hi"]
            t_n  = int(last.iloc[0]["n_fires"])
            t_wr_s = f"{t_wr:.1%}"
            t_ci_s = f"[{t_lo:.1%}–{t_hi:.1%}]"

        # OLS trend
        rel_wrs = reliable["win_rate"].dropna().values
        slope   = ols_slope(rel_wrs[-TREND_WINDOWS:]) if len(rel_wrs) >= 2 else 0.0

        # fw/wk (full analysis window)
        days = (df.index[-1] - df.index[0]).days
        fpw  = len(sub) / (days / 7)

        print(f"  {short_lbl:<22}  {full_wr:>7.1%}  [{f_lo:.1%}–{f_hi:.1%}]  "
              f"{t_wr_s:>8}  {t_ci_s:>14}  {trend_arrow(slope):>14}  {fpw:>5.1f}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    print("Loading BTCUSDT 1h …")
    df_raw = pfdata.load("BTCUSDT", "1h")
    df_raw = df_raw[df_raw.index >= pd.Timestamp(LOAD_FROM, tz="UTC")]
    print(f"  {len(df_raw):,} bars  {df_raw.index[0].date()} → {df_raw.index[-1].date()}")

    print("Computing features …")
    df = build_features(df_raw)
    df = add_outcomes(df)

    t_p = _tstr(PRIMARY)
    df  = df[df.index >= pd.Timestamp(DATE_START, tz="UTC")]
    df  = df[df.index <= pd.Timestamp(DATE_END,   tz="UTC")]
    df  = df.dropna(subset=[f"mag_win{t_p}"])
    print(f"  Analysis window: {df.index[0].date()} → {df.index[-1].date()}  ({len(df):,} bars)")

    masks = _masks(df)

    print(f"\nComputing rolling {WINDOW_WEEKS}-week statistics …")
    results = compute_rolling(df, masks)

    print_rolling_table(results, masks, df)
    print_summary(results, masks, df)

    print("\nGenerating charts …")
    chart_rolling_timeseries(results, masks, df)
    chart_rolling_current(results, masks, df)

    print("\nDone.")


if __name__ == "__main__":
    main()
