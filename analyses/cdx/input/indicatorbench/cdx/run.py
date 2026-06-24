"""
run.py v2 — CDX NA IG signal search, iteration, final charts.
Added: G_fade_capped, H_two_phase, I_regime_fade; Calmar ratio; spike trade log.
"""
from __future__ import annotations
import itertools, warnings, os
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.dates as mdates
from matplotlib.patches import Patch

from signals import (
    sig_zscore_fade, sig_zscore_peak_fade,
    sig_spike_onset, sig_bb_fade,
    sig_rsi_fade, sig_ou_continuous,
    sig_zscore_fade_capped, sig_two_phase, sig_regime_fade,
    sig_tail_hold, sig_crisis_ride,
)
from backtest import run, grid_search, Result

# ── palette ───────────────────────────────────────────────────────────────────
DARK  = "#0e1117"; GRID  = "#2a2d35"
BLUE  = "#4c9be8"; AMBER = "#f0a500"
RED   = "#e05252"; GREEN = "#52b788"
PURPLE= "#a78bfa"; TEAL  = "#2dd4bf"
GREY  = "#6b7280"; LITE  = "#c8cdd6"
ORANGE= "#f97316"; PINK  = "#f472b6"

LEMON  = "#d4f542"
STEEL  = "#94a3b8"

STRATEGY_COLORS = {
    "A_zscore_fade":   BLUE,
    "A2_peak_fade":    TEAL,
    "B_spike_onset":   AMBER,
    "C_bb_fade":       RED,
    "D_rsi_fade":      PURPLE,
    "E_ou_continuous": GREEN,
    "G_fade_capped":   ORANGE,
    "H_two_phase":     PINK,
    "I_regime_fade":   "#06b6d4",
    "J_tail_hold":     LEMON,
    "K_crisis_ride":   STEEL,
}

def calmar(r: Result) -> float:
    return r.cagr_pct / abs(r.max_dd_pct) if r.max_dd_pct != 0 else 0.0

os.makedirs("results", exist_ok=True)

# ── Load data ─────────────────────────────────────────────────────────────────
df = pd.read_csv("cdx_na_ig_clean.csv", parse_dates=["date"])
df = df.sort_values("date").reset_index(drop=True)
s  = df.set_index("date")["cdx_na_ig"]
print(f"Data: {s.index[0].date()} → {s.index[-1].date()}  ({len(s):,} obs)\n")


def expand_grid(**kwargs):
    keys, vals = zip(*kwargs.items())
    return [dict(zip(keys, combo)) for combo in itertools.product(*vals)]


# ══════════════════════════════════════════════════════════════════════════════
# GRID SEARCHES
# ══════════════════════════════════════════════════════════════════════════════

grid_A = expand_grid(
    z_window=[42,63,126], z_enter=[2.0,2.5,3.0],
    z_exit=[0.0,0.5,1.0], z_stop=[4.0,5.0], confirm=[1,2,3],
)
print(f"A  z-score fade    : {len(grid_A):3d} configs … ", end="", flush=True)
res_A = grid_search(sig_zscore_fade, grid_A, s)
print(f"Sharpe={res_A['sharpe'].iloc[0]:.3f}  Calmar={res_A['cagr%'].iloc[0]/abs(res_A['max_dd%'].iloc[0]):.3f}")

grid_A2 = expand_grid(
    z_window=[42,63,126], z_enter=[2.0,2.5,3.0],
    z_exit=[0.0,0.5,1.0], z_stop=[4.0,5.0],
)
print(f"A2 peak fade       : {len(grid_A2):3d} configs … ", end="", flush=True)
res_A2 = grid_search(sig_zscore_peak_fade, grid_A2, s)
print(f"Sharpe={res_A2['sharpe'].iloc[0]:.3f}  Calmar={res_A2['cagr%'].iloc[0]/abs(res_A2['max_dd%'].iloc[0]):.3f}")

grid_B = expand_grid(
    move_thresh=[4.0,5.0,6.0,8.0,10.0,12.0],
    hold_days=[2,3,5,8,12],
    vol_filter=[True,False],
    calm_mult=[1.5,2.0],
)
print(f"B  spike onset     : {len(grid_B):3d} configs … ", end="", flush=True)
res_B = grid_search(sig_spike_onset, grid_B, s)
print(f"Sharpe={res_B['sharpe'].iloc[0]:.3f}  Calmar={res_B['cagr%'].iloc[0]/abs(res_B['max_dd%'].iloc[0]):.3f}")

grid_C = expand_grid(
    period=[15,20,30,40], mult=[1.5,2.0,2.5,3.0], fade_only=[True,False],
)
print(f"C  BB fade         : {len(grid_C):3d} configs … ", end="", flush=True)
res_C = grid_search(sig_bb_fade, grid_C, s)
print(f"Sharpe={res_C['sharpe'].iloc[0]:.3f}  Calmar={res_C['cagr%'].iloc[0]/abs(res_C['max_dd%'].iloc[0]):.3f}")

grid_D = expand_grid(
    period=[7,10,14,21], rsi_enter=[65.0,70.0,75.0,80.0], rsi_exit=[45.0,50.0,55.0],
)
print(f"D  RSI fade        : {len(grid_D):3d} configs … ", end="", flush=True)
res_D = grid_search(sig_rsi_fade, grid_D, s)
print(f"Sharpe={res_D['sharpe'].iloc[0]:.3f}  Calmar={res_D['cagr%'].iloc[0]/abs(res_D['max_dd%'].iloc[0]):.3f}")

grid_E = expand_grid(
    z_window=[42,63,126,252], z_thresh=[0.5,1.0,1.5,2.0],
)
print(f"E  OU continuous   : {len(grid_E):3d} configs … ", end="", flush=True)
res_E = grid_search(sig_ou_continuous, grid_E, s)
print(f"Sharpe={res_E['sharpe'].iloc[0]:.3f}  Calmar={res_E['cagr%'].iloc[0]/abs(res_E['max_dd%'].iloc[0]):.3f}")

grid_G = expand_grid(
    z_window=[42,63,126], z_enter=[2.0,2.5], z_exit=[0.0,0.5],
    z_stop=[4.0,5.0], confirm=[1,2], max_hold=[20,30,40,60],
)
print(f"G  fade capped     : {len(grid_G):3d} configs … ", end="", flush=True)
res_G = grid_search(sig_zscore_fade_capped, grid_G, s)
print(f"Sharpe={res_G['sharpe'].iloc[0]:.3f}  Calmar={res_G['cagr%'].iloc[0]/abs(res_G['max_dd%'].iloc[0]):.3f}")

grid_H = expand_grid(
    move_thresh=[6.0,8.0,10.0], onset_hold=[3,5,8],
    z_window=[42,63], z_enter=[1.5,2.0,2.5],
    fade_hold=[20,30,45], z_exit=[0.5], z_stop=[4.5],
)
print(f"H  two-phase       : {len(grid_H):3d} configs … ", end="", flush=True)
res_H = grid_search(sig_two_phase, grid_H, s)
print(f"Sharpe={res_H['sharpe'].iloc[0]:.3f}  Calmar={res_H['cagr%'].iloc[0]/abs(res_H['max_dd%'].iloc[0]):.3f}")

grid_I = expand_grid(
    z_window=[42,63,126], z_enter=[1.5,2.0,2.5],
    z_exit=[0.0,0.5], z_stop=[4.0,5.0],
    confirm=[1,2], min_level=[60.0,70.0,80.0],
)
print(f"I  regime fade     : {len(grid_I):3d} configs … ", end="", flush=True)
res_I = grid_search(sig_regime_fade, grid_I, s)
print(f"Sharpe={res_I['sharpe'].iloc[0]:.3f}  Calmar={res_I['cagr%'].iloc[0]/abs(res_I['max_dd%'].iloc[0]):.3f}")

grid_J = expand_grid(
    move_thresh=[6.0,8.0,10.0,12.0],
    trail_pct=[0.15,0.20,0.30,0.40],
    max_hold=[30,60,90],
    vol_filter=[True,False],
    calm_mult=[2.0],
    max_level=[70.0,90.0,9999.0],
)
print(f"J  tail hold       : {len(grid_J):3d} configs … ", end="", flush=True)
res_J = grid_search(sig_tail_hold, grid_J, s)
print(f"Sharpe={res_J['sharpe'].iloc[0]:.3f}  Calmar={res_J['cagr%'].iloc[0]/abs(res_J['max_dd%'].iloc[0]):.3f}  N={res_J['n_trades'].iloc[0]}")

grid_K = expand_grid(
    move_thresh=[6.0,8.0,10.0],
    vol_filter=[True,False],
    calm_mult=[2.0],
    max_hold=[90,120,180],
    revert_mult=[1.0,1.05,1.10,1.20],
    max_level=[70.0,90.0,9999.0],
)
print(f"K  crisis ride     : {len(grid_K):3d} configs … ", end="", flush=True)
res_K = grid_search(sig_crisis_ride, grid_K, s)
print(f"Sharpe={res_K['sharpe'].iloc[0]:.3f}  Calmar={res_K['cagr%'].iloc[0]/abs(res_K['max_dd%'].iloc[0]):.3f}  N={res_K['n_trades'].iloc[0]}")


# ══════════════════════════════════════════════════════════════════════════════
# WINNERS
# ══════════════════════════════════════════════════════════════════════════════

_res_map = [res_A, res_A2, res_B, res_C, res_D, res_E, res_G, res_H, res_I, res_J, res_K]
_sig_map = [
    sig_zscore_fade, sig_zscore_peak_fade, sig_spike_onset, sig_bb_fade,
    sig_rsi_fade, sig_ou_continuous, sig_zscore_fade_capped, sig_two_phase, sig_regime_fade,
    sig_tail_hold, sig_crisis_ride,
]
_keys = ["A_zscore_fade","A2_peak_fade","B_spike_onset","C_bb_fade",
         "D_rsi_fade","E_ou_continuous","G_fade_capped","H_two_phase","I_regime_fade",
         "J_tail_hold","K_crisis_ride"]

winners: dict[str, Result] = {}
for key, fn, res in zip(_keys, _sig_map, _res_map):
    winners[key] = run(s, fn(s, **res["params"].iloc[0]), name=key)


# ══════════════════════════════════════════════════════════════════════════════
# LEADERBOARD
# ══════════════════════════════════════════════════════════════════════════════

rows = []
for key, r in winners.items():
    d = r.summary()
    d["calmar"] = round(calmar(r), 3)
    rows.append(d)
summary_df = pd.DataFrame(rows).sort_values("sharpe", ascending=False).reset_index(drop=True)

print("\n" + "="*110)
print("LEADERBOARD (sorted by Sharpe, no transaction costs)")
print("="*110)
disp = ["name","sharpe","calmar","cagr%","ann_vol%","max_dd%","n_trades","avg_hold_d","win_rate%","in_mkt%"]
print(summary_df[disp].to_string(index=False))

print("\n--- Top-3 per family ---")
for label, res_df, fn_name in zip(
    ["A z-score fade","A2 peak fade","B spike onset","C BB fade","D RSI fade",
     "E OU continuous","G fade capped","H two-phase","I regime fade",
     "J tail hold","K crisis ride"],
    _res_map, [fn.__name__ for fn in _sig_map],
):
    print(f"\n{fn_name} — {label}")
    cols = ["sharpe","cagr%","max_dd%","n_trades","avg_hold_d","win_rate%","in_mkt%","params"]
    print(res_df[cols].head(3).to_string(index=False))


# ── Spike onset trade log ─────────────────────────────────────────────────────
print("\n" + "="*70)
print("B — SPIKE ONSET: individual trades")
print("="*70)
best_B = res_B["params"].iloc[0]
pos_B  = sig_spike_onset(s, **best_B)
pct    = s.pct_change() * 100

trade_log = []
pos_arr, idx_arr = pos_B.values, pos_B.index
i = 0
while i < len(pos_arr):
    if pos_arr[i] == 1:
        j = i + 1
        while j < len(pos_arr) and pos_arr[j] == 1:
            j += 1
        pnl_slice = (pos_B.shift(1) * s.pct_change()).iloc[i + 1: j + 1]
        trade_log.append({
            "entry_date":  idx_arr[i].date(),
            "level_bps":   round(float(s.iloc[i]), 1),
            "trigger_%":   round(float(pct.iloc[i]), 1),
            "hold_days":   j - i,
            "trade_ret_%": round(float(pnl_slice.sum() * 100), 2),
        })
        i = j
    else:
        i += 1

trade_df = pd.DataFrame(trade_log)
trade_df["win"] = trade_df["trade_ret_%"] > 0
print(f"Params: {best_B}")
print(trade_df.drop(columns=["win"]).to_string(index=False))
print(f"\nWin rate: {trade_df['win'].mean()*100:.0f}%  |  Avg ret/trade: {trade_df['trade_ret_%'].mean():.2f}%")


def make_trade_log(pos: pd.Series, name: str) -> pd.DataFrame:
    """Generic trade log for long-only positional signals."""
    rows = []
    pos_v, idx_v = pos.values, pos.index
    i = 0
    n = len(pos_v)
    while i < n:
        if pos_v[i] == 1:
            j = i + 1
            while j < n and pos_v[j] == 1:
                j += 1
            pnl_sl = (pos.shift(1) * s.pct_change()).iloc[i + 1: j + 1]
            rows.append({
                "entry_date":  idx_v[i].date(),
                "level_bps":   round(float(s.iloc[i]), 1),
                "trigger_%":   round(float(pct.iloc[i]), 1),
                "hold_days":   j - i,
                "trade_ret_%": round(float(pnl_sl.sum() * 100), 2),
            })
            i = j
        else:
            i += 1
    df = pd.DataFrame(rows)
    if not df.empty:
        df["win"] = df["trade_ret_%"] > 0
    return df


print("\n" + "="*70)
print("J — TAIL HOLD: individual trades (best params)")
print("="*70)
best_J = res_J["params"].iloc[0]
pos_J  = sig_tail_hold(s, **best_J)
tlog_J = make_trade_log(pos_J, "J")
print(f"Params: {best_J}")
if tlog_J.empty:
    print("  (no trades)")
else:
    print(tlog_J.drop(columns=["win"]).to_string(index=False))
    print(f"\nN={len(tlog_J)}  WR={tlog_J['win'].mean()*100:.0f}%  Avg={tlog_J['trade_ret_%'].mean():.2f}%  Median={tlog_J['trade_ret_%'].median():.2f}%")

print("\n" + "="*70)
print("K — CRISIS RIDE: individual trades (best params)")
print("="*70)
best_K = res_K["params"].iloc[0]
pos_K  = sig_crisis_ride(s, **best_K)
tlog_K = make_trade_log(pos_K, "K")
print(f"Params: {best_K}")
if tlog_K.empty:
    print("  (no trades)")
else:
    print(tlog_K.drop(columns=["win"]).to_string(index=False))
    print(f"\nN={len(tlog_K)}  WR={tlog_K['win'].mean()*100:.0f}%  Avg={tlog_K['trade_ret_%'].mean():.2f}%  Median={tlog_K['trade_ret_%'].median():.2f}%")


# ══════════════════════════════════════════════════════════════════════════════
# STYLE HELPER
# ══════════════════════════════════════════════════════════════════════════════

def style_ax(ax, title="", ylabel="", ts=True):
    ax.set_facecolor(DARK)
    ax.tick_params(colors=LITE, labelsize=7.5)
    ax.spines[["top","right"]].set_visible(False)
    ax.spines[["left","bottom"]].set_color(GRID)
    ax.grid(axis="y", color=GRID, lw=0.5, ls="--", alpha=0.7)
    ax.grid(axis="x", color=GRID, lw=0.3, ls=":", alpha=0.5)
    if title:  ax.set_title(title, color=LITE, fontsize=9, pad=5)
    if ylabel: ax.set_ylabel(ylabel, color=LITE, fontsize=8)
    if ts:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.xaxis.set_major_locator(mdates.YearLocator())


# ══════════════════════════════════════════════════════════════════════════════
# CHART 1 — signal overlay (top 6 by Sharpe)
# ══════════════════════════════════════════════════════════════════════════════

# Always include J and K in the signal chart regardless of Sharpe rank
top6_keys = summary_df["name"].head(4).tolist()
for _xtra in ["J_tail_hold", "K_crisis_ride"]:
    if _xtra not in top6_keys:
        top6_keys.append(_xtra)
top6 = {k: winners[k] for k in top6_keys}

fig1, axes = plt.subplots(
    len(top6) + 1, 1,
    figsize=(22, 4 + len(top6) * 2.4),
    facecolor=DARK,
    gridspec_kw={"height_ratios": [2.5] + [1.0] * len(top6)},
)
fig1.suptitle("CDX NA IG — Entry/Exit Signals (top 6 by Sharpe, best params)",
              fontsize=13, color="white", fontweight="bold", y=0.997)

ax0 = axes[0]
ax0.plot(s.index, s.values, color=BLUE, lw=0.9, alpha=0.9, label="CDX NA IG")
ax0.plot(s.rolling(63).mean().index, s.rolling(63).mean(),
         color=AMBER, lw=1.2, ls="--", alpha=0.7, label="63d SMA")
for d in trade_df["entry_date"]:
    ax0.axvline(pd.Timestamp(d), color=AMBER, lw=0.8, alpha=0.45)
ax0.set_ylim(bottom=0)
ax0.legend(fontsize=7.5, facecolor="#1a1d26", labelcolor=LITE, edgecolor=GRID, framealpha=0.85)
style_ax(ax0, title="Spread (bps) — amber lines = spike onset events", ylabel="bps")

for idx, (key, result) in enumerate(top6.items()):
    ax  = axes[idx + 1]
    col = STRATEGY_COLORS.get(key, GREY)
    pos = result.positions

    ax.fill_between(pos.index, 0, 1, where=(pos > 0),
                    color=GREEN, alpha=0.5, transform=ax.get_xaxis_transform())
    ax.fill_between(pos.index, 0, 1, where=(pos < 0),
                    color=RED,   alpha=0.4, transform=ax.get_xaxis_transform())
    ax2 = ax.twinx()
    ax2.plot(s.index, s.values, color=col, lw=0.5, alpha=0.3)
    ax2.set_facecolor(DARK)
    ax2.tick_params(colors=LITE, labelsize=6)
    ax2.spines[["top","right"]].set_color(GRID)
    ax2.set_ylabel("bps", color=LITE, fontsize=7)

    handles = [Patch(color=GREEN, alpha=0.6, label="Long"),
               Patch(color=RED,   alpha=0.5, label="Short")]
    ax.legend(handles=handles, loc="upper left", fontsize=6,
              facecolor="#1a1d26", labelcolor=LITE, edgecolor=GRID, framealpha=0.8)
    sh, cal, wr, nt = result.sharpe, calmar(result), result.win_rate_pct, result.n_trades
    style_ax(ax, title=f"{key}   Sh={sh:.2f}  Calmar={cal:.3f}  WR={wr:.0f}%  N={nt}", ylabel="pos")
    ax.set_yticks([])

plt.tight_layout(rect=[0,0,1,0.996])
fig1.savefig("cdx_signals.svg", format="svg", bbox_inches="tight", facecolor=DARK)
print("\nChart saved: cdx_signals.svg")


# ══════════════════════════════════════════════════════════════════════════════
# CHART 2 — equity curves + drawdowns
# ══════════════════════════════════════════════════════════════════════════════

fig2 = plt.figure(figsize=(22, 16), facecolor=DARK)
fig2.suptitle("CDX NA IG — Equity Curves & Drawdowns (best params, no costs)",
              fontsize=13, color="white", fontweight="bold", y=0.997)
gs2 = gridspec.GridSpec(2, 1, figure=fig2, height_ratios=[2,1], hspace=0.38)
ax_eq = fig2.add_subplot(gs2[0])
ax_dd = fig2.add_subplot(gs2[1])

for key, result in sorted(winners.items(), key=lambda x: -x[1].sharpe):
    col = STRATEGY_COLORS.get(key, GREY)
    eq  = result.equity
    dd  = (eq - eq.cummax()) / eq.cummax() * 100
    lbl = f"{key}  Sh={result.sharpe:.2f}  Cal={calmar(result):.3f}  CAGR={result.cagr_pct:.1f}%  MaxDD={result.max_dd_pct:.1f}%"
    ax_eq.plot(eq.index, eq.values, color=col, lw=1.5, alpha=0.9, label=lbl)
    ax_dd.plot(dd.index, dd.values, color=col, lw=0.9, alpha=0.8)

ax_eq.axhline(1.0, color=GREY, lw=0.6, ls="--")
style_ax(ax_eq, title="Equity Curves (1.0 = start)", ylabel="Equity")
ax_eq.legend(fontsize=7, facecolor="#1a1d26", labelcolor=LITE,
             edgecolor=GRID, framealpha=0.9, loc="upper left")
ax_dd.axhline(0, color=GREY, lw=0.5)
style_ax(ax_dd, title="Drawdown from Peak (%)", ylabel="DD %")

plt.tight_layout(rect=[0,0,1,0.996])
fig2.savefig("cdx_equity.svg", format="svg", bbox_inches="tight", facecolor=DARK)
print("Chart saved: cdx_equity.svg")


# ══════════════════════════════════════════════════════════════════════════════
# CHART 3 — Sharpe / Calmar scatter
# ══════════════════════════════════════════════════════════════════════════════

fig3, (ax3a, ax3b) = plt.subplots(1, 2, figsize=(16, 6), facecolor=DARK)
fig3.suptitle("CDX NA IG — Sharpe vs Calmar across all grid configs",
              fontsize=12, color="white", fontweight="bold")

all_grid = pd.concat(
    [r.assign(family=f) for r, f in zip(_res_map, _keys)], ignore_index=True
)
all_grid["calmar_val"] = all_grid["cagr%"] / all_grid["max_dd%"].abs().replace(0, np.nan)
fam_colors = {k: list(STRATEGY_COLORS.values())[i] for i, k in enumerate(_keys)}

for ax in (ax3a, ax3b):
    ax.set_facecolor(DARK)
    ax.tick_params(colors=LITE, labelsize=8)
    ax.spines[["top","right"]].set_visible(False)
    ax.spines[["left","bottom"]].set_color(GRID)
    ax.grid(color=GRID, lw=0.5, ls="--", alpha=0.6)

for fam, grp in all_grid.groupby("family"):
    col = fam_colors.get(fam, GREY)
    ax3a.scatter(grp["sharpe"], grp["cagr%"],    color=col, alpha=0.4, s=12, label=fam)
    ax3b.scatter(grp["sharpe"], grp["calmar_val"], color=col, alpha=0.4, s=12, label=fam)

for ax, ylabel, title in [
    (ax3a, "CAGR %",                  "Sharpe vs CAGR%"),
    (ax3b, "Calmar (CAGR/|MaxDD|)",   "Sharpe vs Calmar"),
]:
    ax.axvline(0, color=GREY, lw=0.6, ls="--")
    ax.set_xlabel("Sharpe", color=LITE, fontsize=9)
    ax.set_ylabel(ylabel,   color=LITE, fontsize=9)
    ax.set_title(title,     color=LITE, fontsize=10, pad=5)
    ax.legend(fontsize=7.5, facecolor="#1a1d26", labelcolor=LITE, edgecolor=GRID, framealpha=0.85)

plt.tight_layout()
fig3.savefig("cdx_scatter.svg", format="svg", bbox_inches="tight", facecolor=DARK)
print("Chart saved: cdx_scatter.svg")


# ── Save CSVs ─────────────────────────────────────────────────────────────────
summary_df.to_csv("results/best_per_family.csv", index=False)
trade_df.to_csv("results/spike_onset_trades.csv", index=False)
tlog_J.to_csv("results/tail_hold_trades.csv", index=False)
tlog_K.to_csv("results/crisis_ride_trades.csv", index=False)
all_grid.drop(columns=["name"], errors="ignore").to_csv("results/grid_results_v3.csv", index=False)
print("\nResults saved to results/")
print("Done.")



