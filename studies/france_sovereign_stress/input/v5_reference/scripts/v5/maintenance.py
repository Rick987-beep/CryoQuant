"""How much monitoring the v5 linear trades need: daily vs weekly checks, ladder vs stop only, and action counts.

Same engine as linear.run, but stops and adds are only acted on at check days, and a manual check fills at that
day's close (the whole gap through the stop is lost). Writes data/v5/maintenance_<stamp>.json.

    .venv/bin/python jobs/france-sovereign-stress/scripts/v5/maintenance.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import linear
import options
from history import STOCKS
from model import LEVELS, Calib, FutCalib, simulate

OUT = Path(__file__).resolve().parents[2] / "data" / "v5"


def run_checked(s, w, rule, budget, check, resting_stop):
    """Equity per path, adds per path, and action days per path (adds, stop, exit) for a given check calendar."""
    n = w.n
    X = s.X
    units = np.full(n, min(budget / rule.d, s.cap_units))
    eq = np.full(n, float(budget)) - units * s.tcost
    stop = np.full(n, -rule.d)
    anchor = np.zeros(n)
    alive = np.ones(n, bool)
    adds = np.zeros(n, int)
    rolls = set(s.rolls)
    for t in range(1, w.T + 1):
        act = alive & (t <= w.tc)
        if not act.any():
            break
        x, xp = X[:, t], X[:, t - 1]
        if resting_stop:
            hit = act & (x <= stop)
            fill = stop - s.slip - 0.5 * np.maximum(stop - s.slip - x, 0)
        else:
            hit = act & (x <= stop) & check[t]
            fill = x - s.slip
        eq = np.where(hit, eq + units * (fill - xp) - units * s.tcost, np.where(act, eq + units * (x - xp), eq))
        alive &= ~hit
        live = act & ~hit
        if t in rolls:
            eq = eq - np.where(live, units * 2 * s.tcost, 0)
        if rule.step is not None and check[t]:
            up = live & (x >= anchor + rule.step)
            if up.any():
                new = np.minimum((1 - rule.keep) * np.maximum(eq, 0) / rule.d, s.cap_units)
                eq = np.where(up, eq - np.abs(new - units) * s.tcost, eq)
                units = np.where(up, new, units)
                anchor = np.where(up, x, anchor)
                stop = np.where(up, x - rule.d, stop)
                adds += up
        done = live & (t == w.tc)
        eq = np.where(done, eq - units * s.tcost, eq)
        alive &= ~done
    return eq, adds


def main():
    snap = options.load_snapshot()
    cal, fc = Calib.load(), FutCalib.load()
    variants = {
        "daily_resting": ("Resting stop + daily check for adds (model)", "daily", True, True),
        "daily_close": ("Daily check after the close, stop and adds at the close", "daily", False, True),
        "weekly_adds": ("Resting stop, adds checked on Fridays only", "weekly", True, True),
        "weekly_all": ("Everything checked on Fridays only", "weekly", False, True),
        "stop_only": ("Resting stop, no ladder", "daily", True, False),
    }
    sleeves = {"spread": (linear.Rule(40, 20, 0.0), linear.Rule(40)), "^FCHI": (linear.Rule(12, 6, 0.0), linear.Rule(12))}
    out = {"snapshot": snap.path.name, "variants": {k: v[0] for k, v in variants.items()}, "results": {}}
    for i, level in enumerate(list(LEVELS) + [None]):
        w = simulate(cal, snap.spread, snap.val_date, 10_000, level, 11 + i)
        fut, _ = linear.futures_sleeves(w, fc)
        st = {s.key: s for s in fut + linear.stock_sleeves(w, cal, STOCKS)}
        daily = np.ones(w.T + 1, bool)
        weekly = np.array([d.weekday() == 4 for d in w.days])
        for key, (ladder, flat) in sleeves.items():
            for vk, (_, freq, resting, pyramid) in variants.items():
                eq, adds = run_checked(st[key], w, ladder if pyramid else flat, 10_000,
                                       daily if freq == "daily" else weekly, resting)
                m = eq / 10_000
                stopped = m <= 0.1
                r = {"mean": round(float(m.mean()), 2), "median": round(float(np.median(m)), 2),
                     "p_lost": round(float(stopped.mean()), 3), "adds_mean": round(float(adds.mean()), 2),
                     "adds_p90": int(np.percentile(adds, 90))}
                if level == 300 and pyramid:
                    r["adds_alive_mean"] = round(float(adds[~stopped].mean()), 2)
                out["results"].setdefault(key, {}).setdefault(vk, {})[str(level)] = r
        if level == 300:
            out["horizon_bdays"] = int(w.T)
    path = OUT / f"maintenance_{snap.path.stem.replace('eurex_', '')}.json"
    path.write_text(json.dumps(out, indent=1))
    for key, res in out["results"].items():
        print(key)
        for vk, lv in res.items():
            a, b = lv["300"], lv["None"]
            print(f"  {vk:14s} 300bp mean {a['mean']:6.2f} med {a['median']:6.2f} lost {a['p_lost']:.0%} adds "
                  f"{a['adds_mean']:.1f} (p90 {a['adds_p90']}, survivors {a.get('adds_alive_mean', '-')}) | 240 "
                  f"{lv['240']['mean']:.2f} 400 {lv['400']['mean']:.2f} | wrong mean {b['mean']:.2f} adds "
                  f"{b['adds_mean']:.1f}")
    print("wrote", path)


if __name__ == "__main__":
    main()
