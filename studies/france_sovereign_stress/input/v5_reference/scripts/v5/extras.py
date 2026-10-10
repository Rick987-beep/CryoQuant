"""Extras for the v5 report: 40/+20 spread + CAC mixes on common paths, and an OOAT put at implied vs realized vol."""
import json
import math
import sys
from pathlib import Path

import numpy as np

V5 = Path(__file__).resolve().parent
OUT = V5.parents[1] / "data" / "v5"
sys.path.insert(0, str(V5))
sys.path.insert(0, str(V5.parent / "v4"))

import linear  # noqa: E402
import options  # noqa: E402
from history import STOCKS  # noqa: E402
from model import LEVELS, Calib, FutCalib, simulate  # noqa: E402

snap = options.load_snapshot()
cal, fc = Calib.load(), FutCalib.load()
SPREAD = ("spread", linear.Rule(40, 20, 0.0))
CAC = ("^FCHI", linear.Rule(12, 6, 0.0))
out = {"levels": {}}
for i, level in enumerate(list(LEVELS) + [None]):
    w = simulate(cal, snap.spread, snap.val_date, 10_000, level, 11 + i)
    fut, _ = linear.futures_sleeves(w, fc)
    st = {s.key: s for s in fut + linear.stock_sleeves(w, cal, STOCKS)}
    m = {k: linear.run(st[k], w, r, 10_000)[0] / 10_000 for k, r in (SPREAD, CAC)}
    row = {}
    for wa in (1.0, 0.75, 0.5, 0.0):
        x = wa * m["spread"] + (1 - wa) * m["^FCHI"]
        row[f"{wa:g}"] = {"mean": round(float(x.mean()), 2), "median": round(float(np.median(x)), 2),
                          "p_lost": round(float((x <= 0.1).mean()), 3), "p_5x": round(float((x >= 5).mean()), 3)}
    if level == 300:
        row["corr"] = round(float(np.corrcoef(m["spread"], m["^FCHI"])[0, 1]), 2)
    out["levels"][str(level)] = row


def b76_put(f, k, t, vol):
    d1 = (math.log(f / k) + 0.5 * vol * vol * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    n = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    return k * n(-d2) - f * n(-d1)


e = snap.expiries[("OOAT", "20/11/2026")]
q = e.quotes["P"][105.5]
dur = fc.duration["FOAT"]
iv = dict(e.ivs).get(105.5)
out["put"] = {"k": 105.5, "fwd": round(e.fwd, 2), "t": round(e.t, 3), "bid": q.bid, "ask": q.ask,
              "mid": round((q.bid + q.ask) / 2, 3), "iv": iv, "atm_iv": round(e.skew.atm, 4),
              "atm_bp": round(e.skew.atm / dur * 100 * 100, 0)}
for label, yv in (("realized_85", 0.0085), ("realized_73", 0.0073)):
    pv = yv * dur
    out["put"][label] = {"price_vol": round(pv, 4), "price": round(b76_put(e.fwd, 105.5, e.t, pv), 3)}
out["put"]["model_at_iv"] = round(b76_put(e.fwd, 105.5, e.t, iv), 3)
eur = fc.eur_per_bp["FOAT"] / 1000
for f_share in (0.0, 0.3, 0.6):
    oat_bp = (300 - snap.spread) * (1 - f_share)
    fut = e.fwd - oat_bp * eur
    out["put"][f"intrinsic_f{f_share:g}"] = round(max(105.5 - fut, 0), 2)
out["snapshot"] = snap.path.name
print(json.dumps(out["put"], indent=1))
(OUT / f"extras_{snap.path.stem.replace('eurex_', '')}.json").write_text(json.dumps(out, indent=1))
