"""10_stop_calibration.py — Calibrate stop-loss parameters before backtesting

Two stop mechanisms under analysis:

  Stop A — Spot adverse excursion:
    Exit when BTC spot moves X% against the trade direction from entry.
    For calls: spot drops X%. For puts: spot rises X%.
    Calibration: measure the max adverse spot excursion (MAE) for every winner
    over [entry_ts, expiry-1h]. Distribution of MAE tells us:
      "At stop=-X%, what fraction of winners would be prematurely stopped out?"

  Stop B — Time gate:
    Exit after T hours if no 30%+ gain has been achieved.
    Calibration: for every winner, time_to_30pct (from hold_hours proxy) and
    time_to_peak_est show when gains materialise. Winners whose gain comes late
    must not be killed by an aggressive time gate.

  Loser check:
    For all candidates (winners + losers), compute post-entry spot move at +4h, +8h, +24h.
    "Adverse" = spot moved against the trade direction.
    Tells us: what % of losers had spot move adversely within N hours?
    → If 80% of losers see adverse move >1.5% within 8h, the stop captures most losses early.

Key outputs:
  stop_mae_distribution.csv   — MAE percentiles for winners (calls/puts split + TP category)
  stop_time_gate.csv          — CDF of hold_hours by peak_multiple category
  stop_loser_check.csv        — % losers and winners with adverse spot move > X% within T hours
  stop_joint_grid.csv         — joint (stop_pct, time_gate) simulation: % winners preserved
  stop_calibration.svg        — 4-panel chart with actionable recommendations
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "intraday_options"))
import option_utils as ou  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ADVERSE_STOPS  = [0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0]   # % adverse spot move
TIME_GATES     = [8, 12, 18, 24, 36, 48, 72]                  # hours
POST_ENTRY_HRS = [2, 4, 8, 12, 24]                            # for loser check


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@lru_cache(maxsize=10)
def _load_spot(date_str: str) -> pd.DataFrame | None:
    try:
        return ou.load_spot_day(date_str)
    except FileNotFoundError:
        return None


def _str_to_us(ts_str: str) -> int:
    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000)


def _expiry_cutoff_us(expiry_date_str: str) -> int:
    parts = expiry_date_str.split("-")
    dt    = datetime(int(parts[0]), int(parts[1]), int(parts[2]),
                     7, 0, 0, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000)


def _build_spot_array() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Load ALL spot data into sorted numpy arrays for fast searchsorted lookups."""
    print("Loading all spot data ...")
    frames = []
    for date_str in sorted(ou.available_dates()):
        df = _load_spot(date_str)
        if df is not None:
            frames.append(df[["timestamp", "open", "high", "low", "close"]])
    combined = pd.concat(frames).sort_values("timestamp")
    ts   = combined["timestamp"].values
    high = combined["high"].values
    low  = combined["low"].values
    close = combined["close"].values
    print(f"  {len(ts):,} spot rows spanning {len(frames)} days")
    return ts, high, low, close


def _spot_at(ts_us: int, spot_ts: np.ndarray, spot_close: np.ndarray) -> float | None:
    idx = np.searchsorted(spot_ts, ts_us, side="left")
    idx = min(idx, len(spot_ts) - 1)
    # Accept nearest within 5 minutes
    if abs(spot_ts[idx] - ts_us) < 5 * 60 * 1_000_000:
        return float(spot_close[idx])
    return None


# ---------------------------------------------------------------------------
# Stop A: Max Adverse Excursion for winners
# ---------------------------------------------------------------------------

def _compute_mae(df: pd.DataFrame,
                 spot_ts: np.ndarray, spot_high: np.ndarray,
                 spot_low: np.ndarray, spot_close: np.ndarray) -> pd.Series:
    """
    For each winner row, compute MAE = max adverse spot % move over [entry_ts_us, expiry_cutoff_us].
    Calls: use spot LOW  (BTC could have dropped to this)
    Puts:  use spot HIGH (BTC could have risen to this)
    Returns signed MAE: negative = adverse for call, positive = adverse for put.
    """
    print("Computing max adverse excursion (MAE) for winners ...")
    mae = np.full(len(df), np.nan, dtype=float)

    entry_ts_arr    = df["entry_ts_us"].values
    expiry_cut_arr  = df["expiry_cutoff_us"].values
    entry_spot_arr  = df["entry_spot_usd"].values
    is_call_arr     = df["is_call"].values

    for i in range(len(df)):
        t0 = entry_ts_arr[i]
        t1 = expiry_cut_arr[i]
        es = entry_spot_arr[i]
        if es <= 0 or np.isnan(es):
            continue

        i0 = np.searchsorted(spot_ts, t0, side="left")
        i1 = np.searchsorted(spot_ts, t1, side="right")
        if i1 <= i0:
            continue

        if is_call_arr[i]:
            # Adverse = spot drops. Use LOW for worst case.
            worst = np.min(spot_low[i0:i1])
            mae[i] = (worst - es) / es * 100   # negative = drop
        else:
            # Adverse = spot rises. Use HIGH for worst case.
            worst = np.max(spot_high[i0:i1])
            mae[i] = (worst - es) / es * 100   # positive = rise

        if (i + 1) % 2000 == 0:
            print(f"  MAE: {i+1}/{len(df)}")

    return pd.Series(mae, index=df.index, name="mae_pct")


# ---------------------------------------------------------------------------
# Stop B: Time gate from hold_hours
# ---------------------------------------------------------------------------

def _time_gate_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """CDF of hold_hours split by peak category."""
    rows = []
    categories = [
        ("peak ≥ 2.0×",  df["peak_multiple"] >= 2.0),
        ("peak 1.5–2.0×", (df["peak_multiple"] >= 1.5) & (df["peak_multiple"] < 2.0)),
        ("peak 1.2–1.5×", (df["peak_multiple"] >= 1.2) & (df["peak_multiple"] < 1.5)),
        ("all winners",   pd.Series(True, index=df.index)),
    ]
    for gate in TIME_GATES:
        for label, mask in categories:
            sub = df.loc[mask, "hold_hours"]
            if len(sub) == 0:
                continue
            pct_hit = (sub <= gate).mean() * 100
            rows.append({
                "time_gate_h":    gate,
                "category":       label,
                "n":              len(sub),
                "pct_hit_1.2x":  round(pct_hit, 1),  # % already showed first 1.2× sign
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Loser check: post-entry spot move for all candidates
# ---------------------------------------------------------------------------

def _loser_check(df_cands: pd.DataFrame,
                 spot_ts: np.ndarray, spot_close: np.ndarray) -> pd.DataFrame:
    """
    For each unique entry_ts, look up spot at +2h, +4h, +8h, +12h, +24h.
    For each candidate (call or put), determine if spot moved adversely and by how much.
    """
    print("Computing post-entry spot moves for all candidates ...")
    unique_ts = df_cands["entry_ts_us"].unique()
    spot_map: dict[int, dict[int, float]] = {}   # ts_us → {hrs: spot_close}

    for ts_us in unique_ts:
        row: dict[int, float] = {0: _spot_at(int(ts_us), spot_ts, spot_close) or np.nan}
        for hrs in POST_ENTRY_HRS:
            future_ts = int(ts_us) + hrs * 3600 * 1_000_000
            row[hrs]  = _spot_at(future_ts, spot_ts, spot_close) or np.nan
        spot_map[int(ts_us)] = row

    # Build per-candidate adverse move columns
    df = df_cands.copy()
    for hrs in POST_ENTRY_HRS:
        col = f"adv_move_{hrs}h_pct"
        df[col] = np.nan
        spot_now = df["entry_ts_us"].map(lambda x: spot_map.get(int(x), {}).get(0, np.nan))
        spot_fut = df["entry_ts_us"].map(lambda x: spot_map.get(int(x), {}).get(hrs, np.nan))
        pct_move = (spot_fut - spot_now) / spot_now * 100
        # Adverse for calls = negative move, for puts = positive move
        is_call_mask = df["is_call"] == True   # noqa: E712
        df.loc[is_call_mask, col]  = -pct_move[is_call_mask]   # positive = adverse for call
        df.loc[~is_call_mask, col] =  pct_move[~is_call_mask]  # positive = adverse for put

    # Compute summary table
    rows = []
    for adv_thr in ADVERSE_STOPS:
        for hrs in POST_ENTRY_HRS:
            col   = f"adv_move_{hrs}h_pct"
            valid = df[col].notna()
            win   = df["tradeable"] == True   # noqa: E712
            los   = df["tradeable"] == False  # noqa: E712

            pct_losers_stopped  = (df.loc[valid & los, col] >= adv_thr).mean() * 100
            pct_winners_stopped = (df.loc[valid & win, col] >= adv_thr).mean() * 100
            rows.append({
                "adverse_thr_pct": adv_thr,
                "hours_after_entry": hrs,
                "pct_losers_adverse":  round(pct_losers_stopped, 1),
                "pct_winners_adverse": round(pct_winners_stopped, 1),
                "stop_selectivity":    round(pct_losers_stopped - pct_winners_stopped, 1),
            })
    return pd.DataFrame(rows), df


# ---------------------------------------------------------------------------
# Joint grid: % of winners preserved under combined stop
# ---------------------------------------------------------------------------

def _joint_grid(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each (adverse_stop, time_gate) combo:
      % of winners NOT prematurely stopped.
    'Prematurely stopped' (conservative): |mae| > adverse_stop  OR  hold_hours > time_gate.
    Note: for winners already collected (peak_multiple >= TP), only the time gate matters
    if hold_hours < time_gate.
    """
    rows = []
    for adv in ADVERSE_STOPS:
        for tg in TIME_GATES:
            # Conservative: flag fired if EITHER condition met
            adv_stop_fires = df["abs_mae"].abs() >= adv
            time_gate_fires = df["hold_hours"] > tg
            either_fires = adv_stop_fires | time_gate_fires
            pct_preserved = (~either_fires).mean() * 100
            rows.append({
                "adverse_stop_pct": adv,
                "time_gate_h":      tg,
                "pct_winners_preserved": round(pct_preserved, 1),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _draw_charts(df_winners: pd.DataFrame, df_time: pd.DataFrame,
                 df_loser: pd.DataFrame, df_joint: pd.DataFrame,
                 out_path: Path) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(18, 11))
    fig.suptitle("Stop-loss calibration — Max Adverse Excursion + Time Gate Analysis",
                 fontsize=13, fontweight="bold")

    # --- [0,0] MAE histogram ---
    ax = axes[0][0]
    calls_mae = df_winners.loc[df_winners["is_call"] == True,  "abs_mae"].clip(upper=6)   # noqa
    puts_mae  = df_winners.loc[df_winners["is_call"] == False, "abs_mae"].clip(upper=6)   # noqa
    ax.hist(calls_mae, bins=50, alpha=0.6, label="Calls", color="#4e79a7")
    ax.hist(puts_mae,  bins=50, alpha=0.6, label="Puts",  color="#e15759")
    for x, c in [(1.0, "orange"), (1.5, "red"), (2.0, "darkred")]:
        ax.axvline(x, color=c, ls="--", lw=1.4, label=f"−{x:.1f}%")
    ax.set_xlabel("Max adverse spot excursion |MAE| (%)", fontsize=9)
    ax.set_ylabel("Count", fontsize=9)
    ax.set_title("MAE distribution for winners\n(calls and puts)", fontsize=9.5)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # --- [0,1] MAE survival curve ---
    ax = axes[0][1]
    thresholds = np.linspace(0, 5, 200)
    for grp, lbl, c in [
        (df_winners[df_winners["peak_multiple"] >= 2.0], "peak ≥ 2×", "#59a14f"),
        (df_winners[(df_winners["peak_multiple"] >= 1.5) & (df_winners["peak_multiple"] < 2.0)],
         "peak 1.5–2×", "#f28e2b"),
        (df_winners[df_winners["peak_multiple"] < 1.5], "peak < 1.5×", "#bab0ac"),
        (df_winners, "all winners", "#4e79a7"),
    ]:
        surv = [(grp["abs_mae"] < t).mean() * 100 for t in thresholds]
        ax.plot(thresholds, surv, lw=2, label=lbl, color=c)
    ax.set_xlabel("Adverse spot stop threshold (%)", fontsize=9)
    ax.set_ylabel("% of winners preserved", fontsize=9)
    ax.set_title("Survival: % winners NOT stopped out\nvs adverse spot threshold", fontsize=9.5)
    ax.axhline(90, color="gray", ls=":", lw=1, label="90% line")
    ax.axhline(80, color="gray", ls="--", lw=1, label="80% line")
    ax.legend(fontsize=7.5)
    ax.set_xlim(0, 5)
    ax.set_ylim(40, 102)
    ax.grid(alpha=0.3)

    # --- [0,2] Loser check ---
    ax = axes[0][2]
    sub = df_loser[(df_loser["hours_after_entry"] == 8)].copy()
    x   = np.arange(len(sub))
    w   = 0.38
    ax.bar(x - w/2, sub["pct_losers_adverse"],  width=w, label="Losers stopped",
           color="#e15759", alpha=0.85)
    ax.bar(x + w/2, sub["pct_winners_adverse"], width=w, label="Winners stopped",
           color="#4e79a7", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels([f"−{t:.1f}%" for t in sub["adverse_thr_pct"]], fontsize=8)
    ax.set_xlabel("Adverse spot stop threshold (check at +8h)", fontsize=9)
    ax.set_ylabel("% of candidates triggered", fontsize=9)
    ax.set_title("Losers vs winners stopped at each threshold\n(checked 8h after entry)", fontsize=9.5)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)

    # --- [1,0] Time gate CDF ---
    ax = axes[1][0]
    for cat, c in [("peak ≥ 2.0×", "#59a14f"), ("peak 1.5–2.0×", "#f28e2b"),
                   ("peak 1.2–1.5×", "#bab0ac"), ("all winners", "#4e79a7")]:
        sub = df_time[df_time["category"] == cat]
        if sub.empty:
            continue
        ax.plot(sub["time_gate_h"], sub["pct_hit_1.2x"], "o-", lw=2, label=cat, color=c)
    ax.set_xlabel("Time gate (hours)", fontsize=9)
    ax.set_ylabel("% winners showed 1.2× sign by this time", fontsize=9)
    ax.set_title("Time gate: % of winners already at 1.2×\nby each hour threshold", fontsize=9.5)
    ax.axhline(80, color="gray", ls="--", lw=1, label="80%")
    ax.axhline(90, color="gray", ls=":",  lw=1, label="90%")
    ax.legend(fontsize=8)
    ax.set_ylim(0, 102)
    ax.grid(alpha=0.3)

    # --- [1,1] Joint grid heatmap ---
    ax = axes[1][1]
    pivot = df_joint.pivot(index="adverse_stop_pct", columns="time_gate_h",
                           values="pct_winners_preserved")
    im = ax.imshow(pivot.values, cmap="RdYlGn", vmin=30, vmax=100, aspect="auto")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{h}h" for h in pivot.columns], fontsize=8)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([f"−{p:.1f}%" for p in pivot.index], fontsize=8)
    ax.set_xlabel("Time gate", fontsize=9)
    ax.set_ylabel("Adverse spot stop", fontsize=9)
    ax.set_title("% winners preserved\n(conservative: stop fires if EITHER condition met)",
                 fontsize=9.5)
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = pivot.values[i, j]
            if not np.isnan(v):
                clr = "white" if v < 55 or v > 85 else "black"
                ax.text(j, i, f"{v:.0f}%", ha="center", va="center",
                        fontsize=7.5, color=clr)
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    # --- [1,2] Stop selectivity summary ---
    ax = axes[1][2]
    sub8h = df_loser[df_loser["hours_after_entry"] == 8].copy()
    ax.plot(sub8h["adverse_thr_pct"], sub8h["pct_losers_adverse"],
            "o-", lw=2, label="Losers with adverse move >X%", color="#e15759")
    ax.plot(sub8h["adverse_thr_pct"], sub8h["pct_winners_adverse"],
            "s-", lw=2, label="Winners with adverse move >X%", color="#4e79a7")
    ax.fill_between(sub8h["adverse_thr_pct"],
                    sub8h["pct_winners_adverse"], sub8h["pct_losers_adverse"],
                    alpha=0.15, color="#59a14f", label="Selectivity gap")
    ax.set_xlabel("Adverse spot threshold (%)", fontsize=9)
    ax.set_ylabel("% of candidates", fontsize=9)
    ax.set_title("Stop selectivity: loser capture vs winner cost\n(8h window)", fontsize=9.5)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    ax.set_ylim(0, 100)

    plt.tight_layout()
    plt.savefig(out_path, bbox_inches="tight")
    print(f"Saved {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Load winners
    df_w = pd.read_parquet(HERE / "winner_peaks.parquet")
    print(f"Loaded {len(df_w):,} winner trades")

    # Parse derived fields
    df_w["expiry_date"]     = df_w["expiry"].apply(
        lambda x: datetime.strptime(x, "%d%b%y").date().isoformat()
    )
    df_w["entry_ts_us"]     = df_w["entry_ts"].apply(_str_to_us)
    df_w["expiry_cutoff_us"] = df_w["expiry_date"].apply(_expiry_cutoff_us)
    df_w["entry_date"]      = df_w["entry_ts"].str[:10]

    # Load all spot data as sorted numpy arrays (fast searchsorted)
    spot_ts, spot_high, spot_low, spot_close = _build_spot_array()

    # --- Stop A: MAE ---
    df_w["mae_pct"]  = _compute_mae(df_w, spot_ts, spot_high, spot_low, spot_close)
    df_w["abs_mae"]  = df_w["mae_pct"].abs()

    # MAE distribution summary
    print("\n=== Stop A: MAE distribution for winners ===")
    mae_rows = []
    for label, mask in [
        ("calls — peak ≥ 2×",   (df_w["is_call"]) & (df_w["peak_multiple"] >= 2.0)),
        ("calls — peak < 2×",   (df_w["is_call"]) & (df_w["peak_multiple"] <  2.0)),
        ("puts  — peak ≥ 2×",  (~df_w["is_call"]) & (df_w["peak_multiple"] >= 2.0)),
        ("puts  — peak < 2×",  (~df_w["is_call"]) & (df_w["peak_multiple"] <  2.0)),
        ("all winners",          pd.Series(True, index=df_w.index)),
    ]:
        sub = df_w.loc[mask, "abs_mae"].dropna()
        if len(sub) == 0:
            continue
        pcts_at_stop = {f"pct_safe_at_{s:.1f}%": round((sub < s).mean() * 100, 1)
                        for s in ADVERSE_STOPS}
        row = {"group": label, "n": len(sub),
               "mae_p25": round(sub.quantile(0.25), 2),
               "mae_p50": round(sub.median(), 2),
               "mae_p75": round(sub.quantile(0.75), 2),
               "mae_p90": round(sub.quantile(0.90), 2),
               **pcts_at_stop}
        mae_rows.append(row)
        print(f"  {label}: p50={row['mae_p50']:.2f}%  p75={row['mae_p75']:.2f}%  "
              f"p90={row['mae_p90']:.2f}%  | "
              f"safe at −1.0%: {row['pct_safe_at_1.0%']:.0f}%  "
              f"safe at −1.5%: {row['pct_safe_at_1.5%']:.0f}%  "
              f"safe at −2.0%: {row['pct_safe_at_2.0%']:.0f}%")
    mae_df = pd.DataFrame(mae_rows)
    mae_df.to_csv(HERE / "stop_mae_distribution.csv", index=False)

    # --- Stop B: Time gate ---
    print("\n=== Stop B: Time gate analysis ===")
    df_time = _time_gate_analysis(df_w)
    df_time.to_csv(HERE / "stop_time_gate.csv", index=False)
    for cat in ["all winners", "peak ≥ 2.0×"]:
        sub = df_time[df_time["category"] == cat]
        vals = dict(zip(sub["time_gate_h"], sub["pct_hit_1.2x"]))
        print(f"  {cat}: " +
              "  ".join(f"{h}h→{v:.0f}%" for h, v in vals.items()))

    # --- Joint grid ---
    df_w["abs_mae"] = df_w["abs_mae"].fillna(99.0)   # if no spot data → assume very large
    df_joint = _joint_grid(df_w)
    df_joint.to_csv(HERE / "stop_joint_grid.csv", index=False)
    print("\n=== Joint grid (% winners preserved at adverse+time gate) ===")
    pivot = df_joint.pivot(index="adverse_stop_pct", columns="time_gate_h",
                           values="pct_winners_preserved")
    print(pivot.to_string())

    # --- Loser check ---
    df_cands = pd.read_parquet(HERE / "candidates_enriched.parquet")
    df_cands["entry_ts_us"] = df_cands["entry_ts"].apply(_str_to_us)
    df_loser_summary, _ = _loser_check(df_cands, spot_ts, spot_close)
    df_loser_summary.to_csv(HERE / "stop_loser_check.csv", index=False)

    print("\n=== Loser check: adverse move 8h after entry ===")
    sub8 = df_loser_summary[df_loser_summary["hours_after_entry"] == 8]
    print(sub8[["adverse_thr_pct", "pct_losers_adverse",
                "pct_winners_adverse", "stop_selectivity"]].to_string(index=False))

    # --- Charts ---
    _draw_charts(df_w, df_time, df_loser_summary, df_joint,
                 HERE / "stop_calibration.svg")

    print("\n=== RECOMMENDATION ===")
    # Find sweet spot: adverse stop where ≥80% winners preserved AND high selectivity
    sub8_8h = df_loser_summary[df_loser_summary["hours_after_entry"] == 8].copy()
    for _, row in sub8_8h.iterrows():
        adv_stop = row["adverse_thr_pct"]
        pct_safe = mae_df.loc[
            mae_df["group"] == "all winners",
            f"pct_safe_at_{adv_stop:.1f}%"
        ].values
        if len(pct_safe) == 0:
            continue
        selectivity = row["stop_selectivity"]
        print(f"  Stop −{adv_stop:.1f}%:  "
              f"{pct_safe[0]:.0f}% winners safe  |  "
              f"loser capture {row['pct_losers_adverse']:.0f}%  "
              f"winner cost {row['pct_winners_adverse']:.0f}%  "
              f"(selectivity gap {selectivity:.0f}pp)")
    print("Done.")


if __name__ == "__main__":
    main()
