"""08_mtf_momentum.py — Phase 1: Multi-timeframe momentum alignment

Uses candidates_enriched.parquet (from script 07) — no expensive data loading.

Analyses (tight-spread subset, calls and puts separately):
  1. 4h × 1h momentum cross-tabulation heatmap — does alignment compound the signal?
  2. "Both aligned" combination table: 4h ≥ X AND 1h ≥ Y, various thresholds
  3. DTE interaction: is aligned momentum stronger at DTE 4–5?
  4. Hour-of-day interaction: is the signal stronger in the US session (12–20 UTC)?
  5. 30m momentum stacked on top of 4h+1h alignment — does adding 30m help further?

All analyses split calls and puts. Tight-spread filter = spread_pct ≤ 10%.

Outputs:
  phase1_heatmap_calls.csv     — 4h×1h cross-tab: base_rate and n for calls
  phase1_heatmap_puts.csv      — same for puts
  phase1_both_aligned.csv      — "both aligned" threshold grid
  phase1_structural.csv        — DTE and hour interaction results
  phase1_overview.svg          — heatmaps + combination chart + structural charts
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SPREAD_THRESHOLD = 10.0

# 5-bucket coarse bins for the 2-D heatmap (readable cell counts)
COARSE_BINS   = [-np.inf, -1.5, -0.5, 0.5, 1.5, np.inf]
COARSE_LABELS = ["str.down\n<-1.5%", "sl.down\n-1.5–-0.5%",
                 "neutral\n±0.5%",
                 "sl.up\n+0.5–+1.5%", "str.up\n>+1.5%"]

ALIGNED_4H = [0.3, 0.5, 1.0, 1.5, 2.0]
ALIGNED_1H = [0.0, 0.2, 0.5, 1.0]          # 0.0 = 4h-only baseline

DTE_BEST    = [4, 5]
HOUR_US     = [12, 16, 20]                   # US-session entry hours (out of [0,4,8,12,16,20])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bucket(series: pd.Series) -> pd.Series:
    return pd.cut(series, bins=COARSE_BINS, labels=COARSE_LABELS)


def _base_rate(df: pd.DataFrame) -> tuple[int, int, float]:
    n   = len(df)
    n_t = int(df["tradeable"].sum())
    br  = round(n_t / n * 100, 1) if n > 0 else np.nan
    return n, n_t, br


# ---------------------------------------------------------------------------
# 1. 4h × 1h cross-tabulation heatmap
# ---------------------------------------------------------------------------

def _heatmap_crosstab(df_side: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (base_rate_pivot, n_pivot) — rows=4h bucket, cols=1h bucket."""
    df  = df_side.copy()
    df["b4h"] = _bucket(df["spot_4h_chg_pct"])
    df["b1h"] = _bucket(df["spot_1h_chg_pct"])

    records = []
    for b4, grp4 in df.groupby("b4h", observed=True):
        for b1, grp41 in grp4.groupby("b1h", observed=True):
            n, n_t, br = _base_rate(grp41)
            records.append({"b4h": b4, "b1h": b1, "n": n, "base_rate": br})

    tbl   = pd.DataFrame(records)
    br_pv = tbl.pivot(index="b4h", columns="b1h", values="base_rate")
    n_pv  = tbl.pivot(index="b4h", columns="b1h", values="n")
    return br_pv, n_pv


# ---------------------------------------------------------------------------
# 2. "Both aligned" combination table
# ---------------------------------------------------------------------------

def _both_aligned(df_calls: pd.DataFrame, df_puts: pd.DataFrame,
                  n_days: int) -> pd.DataFrame:
    rows = []
    for thr_4h in ALIGNED_4H:
        for thr_1h in ALIGNED_1H:
            calls_aln = df_calls[
                (df_calls["spot_4h_chg_pct"] >=  thr_4h) &
                (df_calls["spot_1h_chg_pct"] >=  thr_1h)
            ]
            puts_aln = df_puts[
                (df_puts["spot_4h_chg_pct"]  <= -thr_4h) &
                (df_puts["spot_1h_chg_pct"]  <= -thr_1h)
            ]
            combined = pd.concat([calls_aln, puts_aln])
            n, n_t, br = _base_rate(combined)
            n_win = combined["entry_ts"].nunique()
            rows.append({
                "4h_thr": f"≥{thr_4h:.1f}%",
                "1h_thr": f"≥{thr_1h:.1f}%" if thr_1h > 0 else "(4h only)",
                "n_options":      n,
                "n_tradeable":    n_t,
                "base_rate_pct":  br,
                "windows_per_day": round(n_win / n_days, 2),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3. Structural interactions
# ---------------------------------------------------------------------------

def _structural_interaction(df_calls: pd.DataFrame, df_puts: pd.DataFrame,
                             n_days: int) -> pd.DataFrame:
    """Base rate for aligned (4h ≥ 1%) vs overall, split by DTE group and entry hour."""
    rows = []

    def _row(label: str, subset_calls: pd.DataFrame, subset_puts: pd.DataFrame,
             aligned_only: bool) -> dict:
        if aligned_only:
            sc = subset_calls[subset_calls["spot_4h_chg_pct"] >=  1.0]
            sp = subset_puts[ subset_puts["spot_4h_chg_pct"]  <= -1.0]
        else:
            sc, sp = subset_calls, subset_puts
        comb = pd.concat([sc, sp])
        n, n_t, br = _base_rate(comb)
        n_win = comb["entry_ts"].nunique()
        return {
            "segment":         label,
            "aligned_filter":  "4h≥1%+spread≤10%" if aligned_only else "spread≤10% only",
            "n_options":       n,
            "base_rate_pct":   br,
            "windows_per_day": round(n_win / n_days, 2),
        }

    # DTE groups
    for dte_group, dte_vals in [("DTE 4–5", DTE_BEST), ("DTE 1–3,6–7", None)]:
        if dte_vals is not None:
            sc = df_calls[df_calls["dte_at_entry"].isin(dte_vals)]
            sp = df_puts[ df_puts["dte_at_entry"].isin(dte_vals)]
        else:
            sc = df_calls[~df_calls["dte_at_entry"].isin(DTE_BEST)]
            sp = df_puts[ ~df_puts["dte_at_entry"].isin(DTE_BEST)]
        rows.append(_row(dte_group, sc, sp, aligned_only=False))
        rows.append(_row(dte_group, sc, sp, aligned_only=True))

    # Hour groups
    df_calls["entry_hour"] = df_calls["entry_ts"].str[11:13].astype(int)
    df_puts["entry_hour"]  = df_puts["entry_ts"].str[11:13].astype(int)
    for hour_group, hours in [("US session (12/16/20 UTC)", HOUR_US),
                               ("Non-US (00/04/08 UTC)", [0, 4, 8])]:
        sc = df_calls[df_calls["entry_hour"].isin(hours)]
        sp = df_puts[ df_puts["entry_hour"].isin(hours)]
        rows.append(_row(hour_group, sc, sp, aligned_only=False))
        rows.append(_row(hour_group, sc, sp, aligned_only=True))

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _draw_heatmap(ax, br_pv: pd.DataFrame, n_pv: pd.DataFrame,
                  title: str, vmin: float = 40, vmax: float = 100) -> None:
    cmap  = plt.cm.RdYlGn
    norm  = mcolors.Normalize(vmin=vmin, vmax=vmax)
    data  = br_pv.values.astype(float)
    im    = ax.imshow(data, cmap=cmap, norm=norm, aspect="auto")
    ax.set_xticks(range(len(br_pv.columns)))
    ax.set_xticklabels(br_pv.columns, fontsize=7)
    ax.set_yticks(range(len(br_pv.index)))
    ax.set_yticklabels(br_pv.index, fontsize=7)
    ax.set_xlabel("1h prior momentum", fontsize=9)
    ax.set_ylabel("4h prior momentum", fontsize=9)
    ax.set_title(title, fontsize=9.5)
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            br_val = data[i, j]
            n_val  = int(n_pv.values[i, j]) if not np.isnan(n_pv.values[i, j]) else 0
            if not np.isnan(br_val):
                color = "white" if br_val < 52 or br_val > 82 else "black"
                ax.text(j, i, f"{br_val:.0f}%\nn={n_val}",
                        ha="center", va="center", fontsize=6.5, color=color)
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="Base rate %")


def _draw_aligned_chart(ax, df_both: pd.DataFrame, overall_br: float) -> None:
    """Line chart: base rate vs 4h threshold, one line per 1h threshold."""
    for thr_1h_label in df_both["1h_thr"].unique():
        sub = df_both[df_both["1h_thr"] == thr_1h_label].copy()
        sub["x"] = range(len(sub))
        ax.plot(sub["x"], sub["base_rate_pct"], "o-", lw=2,
                label=thr_1h_label, alpha=0.85)
    x_vals = list(range(len(ALIGNED_4H)))
    ax.set_xticks(x_vals)
    ax.set_xticklabels([f"4h≥{t:.1f}%" for t in ALIGNED_4H], fontsize=8)
    ax.set_xlabel("4h aligned threshold", fontsize=9)
    ax.set_ylabel("Base Rate (%)", fontsize=9)
    ax.set_title("Both-aligned filter: base rate by threshold\n(calls+puts, tight-spread)",
                 fontsize=9.5)
    ax.axhline(overall_br, color="gray", ls="--", lw=1.2,
               label=f"4h-only avg {overall_br:.1f}%", zorder=2)
    ax.set_ylim(50, 100)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7.5, title="1h add-on", title_fontsize=7.5)


def _draw_structural(ax, df_struct: pd.DataFrame, label_col: str,
                     overall_br: float, title: str) -> None:
    segments = df_struct[label_col].unique()
    x        = np.arange(len(segments))
    w        = 0.38
    br_base  = [df_struct[(df_struct[label_col] == s) & (df_struct["aligned_filter"].str.startswith("spread"))
                         ]["base_rate_pct"].values[0] for s in segments]
    br_aln   = [df_struct[(df_struct[label_col] == s) & (df_struct["aligned_filter"].str.startswith("4h"))
                         ]["base_rate_pct"].values[0] for s in segments]
    ax.bar(x - w/2, br_base, width=w, label="spread≤10% only", color="#76b7b2", alpha=0.85)
    ax.bar(x + w/2, br_aln,  width=w, label="+ 4h aligned≥1%", color="#59a14f", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(segments, fontsize=8)
    ax.set_ylabel("Base Rate (%)", fontsize=9)
    ax.set_title(title, fontsize=9.5)
    ax.axhline(overall_br, color="gray", ls="--", lw=1.2,
               label=f"Tight-spread avg {overall_br:.1f}%")
    ax.set_ylim(40, 90)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = pd.read_parquet(HERE / "candidates_enriched.parquet")
    print(f"Loaded {len(df):,} candidates from candidates_enriched.parquet")

    df_tight = df[df["spread_pct"] <= SPREAD_THRESHOLD].copy()
    n_days   = df_tight["entry_date"].nunique()
    overall_br = df_tight["tradeable"].mean() * 100
    print(f"Tight-spread: {len(df_tight):,} candidates, {n_days} trading days, {overall_br:.1f}% base rate")

    df_calls = df_tight[df_tight["is_call"] == True].copy()   # noqa: E712
    df_puts  = df_tight[df_tight["is_call"] == False].copy()  # noqa: E712

    # 1. Heatmaps
    print("\nBuilding 4h×1h cross-tabulations ...")
    br_calls, n_calls = _heatmap_crosstab(df_calls)
    br_puts,  n_puts  = _heatmap_crosstab(df_puts)

    # Save CSVs
    br_calls.to_csv(HERE / "phase1_heatmap_calls.csv")
    br_puts.to_csv(HERE  / "phase1_heatmap_puts.csv")
    print("Heatmap CSVs saved.")

    print("\n4h×1h heatmap — CALLS (base rate %):")
    print(br_calls.to_string())
    print("\n4h×1h heatmap — PUTS (base rate %):")
    print(br_puts.to_string())

    # 2. Both-aligned combination table
    print("\nBuilding both-aligned combination table ...")
    df_both = _both_aligned(df_calls, df_puts, n_days)
    df_both.to_csv(HERE / "phase1_both_aligned.csv", index=False)
    print("\nBoth-aligned filter:")
    print(df_both.to_string(index=False))

    # 3. Structural interactions
    print("\nBuilding structural interaction table ...")
    df_struct = _structural_interaction(df_calls, df_puts, n_days)
    df_struct.to_csv(HERE / "phase1_structural.csv", index=False)
    print("\nStructural interactions:")
    print(df_struct.to_string(index=False))

    # 4h-only baseline for the "both aligned" chart (1h_thr = 0)
    br_4h_only = df_both[df_both["1h_thr"] == "(4h only)"]["base_rate_pct"].mean()

    # ===== CHARTS =====
    fig, axes = plt.subplots(2, 3, figsize=(18, 11))
    fig.suptitle(
        "Phase 1 — Multi-timeframe momentum alignment  "
        f"(tight-spread ≤ {SPREAD_THRESHOLD}%,  n={len(df_tight):,})",
        fontsize=13, fontweight="bold"
    )

    _draw_heatmap(axes[0][0], br_calls, n_calls,
                  "4h × 1h momentum — CALLS\n(base rate, tight-spread)")
    _draw_heatmap(axes[0][1], br_puts,  n_puts,
                  "4h × 1h momentum — PUTS\n(base rate, tight-spread)")
    _draw_aligned_chart(axes[0][2], df_both, br_4h_only)

    # Structural: DTE
    dte_struct = df_struct[df_struct["segment"].isin(["DTE 4–5", "DTE 1–3,6–7"])].copy()
    _draw_structural(axes[1][0], dte_struct, "segment", overall_br,
                     "DTE group: base rate with/without 4h alignment")

    # Structural: hour
    hour_struct = df_struct[df_struct["segment"].isin(
        ["US session (12/16/20 UTC)", "Non-US (00/04/08 UTC)"])].copy()
    _draw_structural(axes[1][1], hour_struct, "segment", overall_br,
                     "Session: base rate with/without 4h alignment")

    # 30m on top of both-aligned ≥1%: separate analysis
    best_4h = 1.0
    for thr_30m, label in [(0.0, "(none)"), (0.3, "≥0.3%"), (0.5, "≥0.5%"), (1.0, "≥1.0%")]:
        calls_f = df_calls[df_calls["spot_4h_chg_pct"] >= best_4h]
        puts_f  = df_puts[ df_puts["spot_4h_chg_pct"]  <= -best_4h]
        if thr_30m > 0:
            calls_f = calls_f[calls_f["spot_30m_chg_pct"] >=  thr_30m]
            puts_f  = puts_f[ puts_f["spot_30m_chg_pct"]  <= -thr_30m]
        comb = pd.concat([calls_f, puts_f])
        n, n_t, br = _base_rate(comb)
        n_win = comb["entry_ts"].nunique()

    ax30m = axes[1][2]
    rows_30m = []
    for thr_30m in [0.0, 0.2, 0.3, 0.5, 0.8, 1.0, 1.5]:
        calls_f = df_calls[df_calls["spot_4h_chg_pct"] >= best_4h]
        puts_f  = df_puts[ df_puts["spot_4h_chg_pct"]  <= -best_4h]
        if thr_30m > 0:
            calls_f = calls_f[calls_f["spot_30m_chg_pct"] >=  thr_30m]
            puts_f  = puts_f[ puts_f["spot_30m_chg_pct"]  <= -thr_30m]
        comb    = pd.concat([calls_f, puts_f])
        n, n_t, br = _base_rate(comb)
        n_win   = comb["entry_ts"].nunique()
        rows_30m.append({
            "30m_thr": f"≥{thr_30m:.1f}%" if thr_30m > 0 else "(none)",
            "base_rate_pct": br,
            "windows_per_day": round(n_win / n_days, 2),
            "n_options": n,
        })
    df_30m = pd.DataFrame(rows_30m)
    x30    = np.arange(len(df_30m))
    ax30m2 = ax30m.twinx()
    bars   = ax30m.bar(x30, df_30m["base_rate_pct"], color="#b07aa1", alpha=0.85, zorder=3)
    ax30m2.plot(x30, df_30m["windows_per_day"], "o-", color="#f28e2b", lw=2, zorder=4,
                label="Windows/day")
    ax30m.set_xticks(x30)
    ax30m.set_xticklabels(df_30m["30m_thr"], fontsize=8)
    ax30m.set_xlabel("30m aligned threshold  (stacked on 4h≥1%)", fontsize=9)
    ax30m.set_ylabel("Base Rate (%)", fontsize=9)
    ax30m2.set_ylabel("Entry windows per day", fontsize=9, color="#f28e2b")
    ax30m2.tick_params(axis="y", colors="#f28e2b")
    ax30m.set_title("30m momentum on top of 4h≥1%\nBase rate (bars) | frequency (line)", fontsize=9.5)
    ax30m.axhline(br_4h_only, color="gray", ls="--", lw=1.2,
                  label=f"4h-only avg {br_4h_only:.1f}%")
    ax30m.set_ylim(50, 100)
    ax30m.grid(axis="y", alpha=0.3)
    ax30m.legend(fontsize=8, loc="upper left")
    ax30m2.legend(fontsize=8, loc="upper right")

    plt.tight_layout()
    out_svg = HERE / "phase1_overview.svg"
    plt.savefig(out_svg, bbox_inches="tight")
    print(f"\nSaved {out_svg}")
    print("Done.")


if __name__ == "__main__":
    main()
