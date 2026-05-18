"""08_recent_check.py — Section-F condition check on the 3 most recent weeks.

Re-uses build_features / add_outcomes from 06, restricts to
2026-04-26 → 2026-05-17.  Indicators still computed over the full warmup
period so they're properly initialised; only the analysis window changes.

Usage:
    python3 research/long_tradable_options/08_recent_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO / "pineforge"))

import numpy as np
import pandas as pd

import pineforge.data as pfdata

# ── Import shared helpers from 06 ────────────────────────────────────────────
# (add 06's directory to path so we can import it as a module)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib.util, types

_06_path = Path(__file__).resolve().parent / "06_v2_spot_signals.py"
_spec = importlib.util.spec_from_file_location("sig06", _06_path)
sig06 = types.ModuleType("sig06")
sig06.__file__ = str(_06_path)
sig06.__spec__ = _spec
_spec.loader.exec_module(sig06)  # type: ignore[union-attr]

build_features = sig06.build_features
add_outcomes   = sig06.add_outcomes
THRESHOLDS     = sig06.THRESHOLDS
PRIMARY        = sig06.PRIMARY
FWD_BARS       = sig06.FWD_BARS

# ── Config ────────────────────────────────────────────────────────────────────
LOAD_FROM   = "2024-01-01"       # warmup for indicators
WINDOW_START = "2026-04-26"      # 3 weeks back from ~May 17
WINDOW_END   = "2026-05-17"

def _tstr(t: float) -> str:
    return f"_{t:.1f}".replace(".", "p")

def _hdr(title: str) -> None:
    print(); print("=" * 72); print(f"  {title}"); print("=" * 72)

def _sub(title: str) -> None:
    print(f"\n--- {title} ---")


def main() -> None:
    print("Loading BTCUSDT 1h …")
    df_raw = pfdata.load("BTCUSDT", "1h")
    df_raw = df_raw[df_raw.index >= pd.Timestamp(LOAD_FROM, tz="UTC")]
    print(f"  {len(df_raw):,} bars  {df_raw.index[0].date()} → {df_raw.index[-1].date()}")

    print("Computing features …")
    df = build_features(df_raw)
    df = add_outcomes(df)

    # Restrict to analysis window AFTER feature computation
    df = df[df.index >= pd.Timestamp(WINDOW_START, tz="UTC")]
    df = df[df.index <= pd.Timestamp(WINDOW_END,   tz="UTC")]

    t_p = _tstr(PRIMARY)
    df = df.dropna(subset=[f"mag_win{t_p}"])

    if len(df) < 10:
        print("ERROR: too few bars after dropna — check parquet coverage.")
        return

    print(f"  Analysis window: {df.index[0]} → {df.index[-1]}  ({len(df):,} bars)")

    days_total  = (df.index[-1] - df.index[0]).days
    weeks_total = max(days_total / 7, 0.5)   # avoid /0

    t_labels = [f"{t:.1f}".replace(".", "p") for t in THRESHOLDS]
    ts_p     = f"{PRIMARY:.1f}".replace(".", "p")

    base_call = df[f"call_win{t_p}"].mean()
    base_put  = df[f"put_win{t_p}"].mean()

    # ── Base rates ────────────────────────────────────────────────────────────
    _hdr("BASE RATES  (3-week window)")
    print(f"  {'Target':<18}  {'Thresh':>6}  {'WinRate':>8}  {'N':>6}")
    print("  " + "-" * 45)
    for thresh in THRESHOLDS:
        t = _tstr(thresh)
        for tgt in ["mag_win", "call_win", "put_win"]:
            col = f"{tgt}{t}"
            print(f"  {col:<18}  {thresh:>5.1f}%  {df[col].mean():>7.1%}  {int(df[col].sum()):>6,}")

    # ── Condition table ───────────────────────────────────────────────────────
    _hdr("SECTION F CONDITIONS  (3-week window)")

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
    no_sat     = (dow != 5)
    us_open    = hr.isin(range(13, 18))
    asia       = hr.isin(range(0, 5))

    _th_hdr = "  ".join(f"{t:.1f}%" for t in THRESHOLDS)
    print(f"\n  {'Condition':<55}  fw/wk  N  {_th_hdr}   call   put  type")
    print("  " + "-" * 125)

    def add(label: str, mask: pd.Series) -> None:
        sub = df[mask]
        n = len(sub)
        if n < 2:
            print(f"  {label:<55}  {'—':>5}  {n:>3}  (no fires)")
            return
        fpw = round(n / weeks_total, 1)
        mags = "  ".join(f"{sub[f'mag_win{_tstr(t)}'].mean():>5.0%}" for t in THRESHOLDS)
        c_val = sub[f"call_win{t_p}"].mean()
        p_val = sub[f"put_win{t_p}"].mean()
        skew  = c_val / p_val if p_val > 0.001 else 2.0
        if skew > 1.20 and c_val > base_call * 1.10:
            stype = "calls"
        elif skew < 0.83 and p_val > base_put * 1.10:
            stype = "puts"
        else:
            stype = "straddle"
        print(f"  {label:<55}  {fpw:>5.1f}  {n:>3}  {mags}   {c_val:>4.0%}  {p_val:>4.0%}  {stype}")

    add("BASELINE  (all bars)",                        pd.Series(True, index=df.index))
    add("BASELINE  (no Saturday)",                     no_sat)
    print("  " + "-" * 125)

    _sub("Vol regime")
    add("rv_rank >= 0.60",                             rv >= 0.60)
    add("rv_rank >= 0.75",                             rv >= 0.75)
    add("rv_rank >= 0.60  +  no Saturday",            (rv >= 0.60) & no_sat)
    add("rv_rank < 0.25   (low vol, reference)",       rv < 0.25)

    _sub("Vol spike + regime")
    add("vol_z >= 1.5  +  rv_rank >= 0.60",           (vz >= 1.5) & (rv >= 0.60))
    add("vol_z >= 2.0  +  rv_rank >= 0.60",           (vz >= 2.0) & (rv >= 0.60))
    add("rv>=0.60  +  vol_z>=1.5  +  range>=1.5",    (rv >= 0.60) & (vz >= 1.5) & (rr >= 1.5))
    add("rv>=0.60  +  rv_trend>0  +  range>=1.5",    (rv >= 0.60) & (rvt > 0) & (rr >= 1.5))

    _sub("BB width")
    add("bb_width >= 75th pct  (wide)",                bb_pct >= 0.75)
    add("bb_width >= 90th pct  (very wide)",           bb_pct >= 0.90)
    add("bb_width <= 25th pct  (squeeze)",             bb_pct <= 0.25)

    _sub("MTF momentum  [key sweet-spot conditions]")
    add("4h >= +1%  +  1h <= -0.5%  (calls pullback)",
        (r4h >= 1.0) & (r1h <= -0.5))
    add("4h <= -1%  +  1h >= +0.5%  (puts pullback)",
        (r4h <= -1.0) & (r1h >= 0.5))
    add("EITHER MTF pullback  +  rv >= 0.60",
        (((r4h >= 1.0) & (r1h <= -0.5)) | ((r4h <= -1.0) & (r1h >= 0.5))) & (rv >= 0.60))
    add("4h >= +1%  +  1h <= -0.5%  +  rv >= 0.60",
        (r4h >= 1.0) & (r1h <= -0.5) & (rv >= 0.60))
    add("4h <= -1%  +  1h >= +0.5%  +  rv >= 0.60",
        (r4h <= -1.0) & (r1h >= 0.5) & (rv >= 0.60))

    _sub("Directional — CALLS")
    add("ret_4h > +0.5%  +  rv >= 0.60",              (r4h > 0.5) & (rv >= 0.60))
    add("ema168_dev < -2%  +  rv >= 0.60",            (ema168_dev < -2.0) & (rv >= 0.60))
    add("ret_1d < -2%  +  rv >= 0.60  (bounce)",      (r1d < -2.0) & (rv >= 0.60))

    _sub("Directional — PUTS")
    add("ret_4h < -0.5%  +  rv >= 0.60",              (r4h < -0.5) & (rv >= 0.60))
    add("ret_4h < -0.5%  +  vol_z >= 1.5  +  rv >= 0.60",
        (r4h < -0.5) & (vz >= 1.5) & (rv >= 0.60))
    add("ema168_dev > +3%  +  rv >= 0.60",            (ema168_dev > 3.0) & (rv >= 0.60))

    _sub("Session overlay")
    add("US open (13–17 UTC)",                         us_open)
    add("US open  +  rv_rank >= 0.60",                 us_open & (rv >= 0.60))
    add("vol_z >= 1.5  +  rv >= 0.60  +  US open",   (vz >= 1.5) & (rv >= 0.60) & us_open)

    print(f"\nDone.  ({len(df):,} bars in window, {weeks_total:.1f} weeks)")


if __name__ == "__main__":
    main()
