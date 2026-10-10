"""Market snapshot from a fetched Eurex file: quotes, parity-implied futures, implied vols, skew."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
from scipy.optimize import brentq
from scipy.special import ndtr

JOB = Path(__file__).resolve().parents[2]
CHAINS = JOB / "data" / "chains"
R = 0.02


def num(x) -> Optional[float]:
    if x in (None, "", "-"):
        return None
    return float(str(x).replace(",", ""))


def b76(f, k, t, sig, call):
    f, k, t, sig = (np.asarray(x, dtype=float) for x in (f, k, t, sig))
    srt = sig * np.sqrt(t)
    d1 = (np.log(f / k) + 0.5 * srt * srt) / srt
    d2 = d1 - srt
    df = np.exp(-R * t)
    c = df * (f * ndtr(d1) - k * ndtr(d2))
    p = df * (k * ndtr(-d2) - f * ndtr(-d1))
    return np.where(call, c, p)


def implied_vol(price: float, f: float, k: float, t: float, call: bool) -> Optional[float]:
    intrinsic = max(f - k, 0) if call else max(k - f, 0)
    if price <= intrinsic * np.exp(-R * t) + 1e-4:
        return None
    try:
        return brentq(lambda s: float(b76(f, k, t, s, call)) - price, 0.005, 1.5)
    except ValueError:
        return None


@dataclass
class Quote:
    bid: Optional[float]
    ask: Optional[float]

    @property
    def mid(self) -> Optional[float]:
        if self.bid is None or self.ask is None or self.bid <= 0:
            return None
        return 0.5 * (self.bid + self.ask)


@dataclass
class Skew:
    """Implied vol as a quadratic in standardised moneyness m = ln(K/F)/sqrt(T), stored relative to ATM."""
    atm: float
    b: float
    c: float

    def vol(self, f, k, t, atm=None):
        m = np.log(np.asarray(k, dtype=float) / np.asarray(f, dtype=float)) / np.sqrt(t)
        ratio = np.clip(1 + self.b * m + self.c * m * m, 0.6, 2.5)
        return (self.atm if atm is None else atm) * ratio


@dataclass
class Expiry:
    product: str
    label: str
    date: date
    t: float
    quotes: Dict[str, Dict[float, Quote]]
    fwd: float
    skew: Skew
    ivs: list

    def cost(self, cp: str, k: float, side: int) -> Optional[float]:
        q = self.quotes[cp].get(k)
        if q is None:
            return None
        px = q.ask if side > 0 else q.bid
        return px if px and px > 0 else None


def parity_forward(quotes: dict, near: float) -> float:
    est = []
    for k, c in quotes["C"].items():
        p = quotes["P"].get(k)
        if p and c.mid and p.mid and abs(k - near) <= 2.5:
            est.append(k + c.mid - p.mid)
    return float(np.median(est))


def fit_skew(quotes: dict, f: float, t: float) -> Tuple[Skew, list]:
    pts = []
    for cp, side in (("P", False), ("C", True)):
        for k, q in quotes[cp].items():
            otm = k < f if cp == "P" else k >= f
            if otm and q.mid and q.ask - q.bid <= max(0.25, 0.6 * q.mid):
                iv = implied_vol(q.mid, f, k, t, side)
                if iv:
                    pts.append((k, np.log(k / f) / np.sqrt(t), iv))
    m = np.array([p[1] for p in pts])
    iv = np.array([p[2] for p in pts])
    c2, c1, c0 = np.polyfit(m, iv, 2)
    return Skew(atm=c0, b=c1 / c0, c=c2 / c0), [(round(k, 2), round(v, 4)) for k, _, v in sorted(pts)]


@dataclass
class Snapshot:
    path: Path
    fetched_at: datetime
    oat10: float
    bund10: float
    expiries: Dict[Tuple[str, str], Expiry]
    futures: dict

    @property
    def spread(self) -> float:
        return round((self.oat10 - self.bund10) * 100, 1)

    @property
    def val_date(self) -> date:
        return self.fetched_at.date()


def load(path: Optional[Path] = None) -> Snapshot:
    path = path or max(CHAINS.glob("eurex_*.json"))
    raw = json.loads(path.read_text())
    fetched = datetime.fromisoformat(raw["fetched_at"])
    exps = {}
    for product, chains in raw["chains"].items():
        for label, ch in chains.items():
            if not ch:
                continue
            d = datetime.strptime(label, "%d/%m/%Y").date()
            t = max((d - fetched.date()).days, 1) / 365
            quotes = {"P": {}, "C": {}}
            for cp, key in (("P", "put"), ("C", "call")):
                for r in ch[key]:
                    quotes[cp][num(r["strikePrice"])] = Quote(num(r["bid"]), num(r["ask"]))
            near = np.median(list(quotes["C"]))
            fwd = parity_forward(quotes, near)
            fwd = parity_forward(quotes, fwd)
            skew, ivs = fit_skew(quotes, fwd, t)
            exps[(product, label)] = Expiry(product, label, d, t, quotes, fwd, skew, ivs)
    y = raw["yields"]
    return Snapshot(path, fetched, y["oat10"], y["bund10"], exps, raw.get("futures", {}))


if __name__ == "__main__":
    s = load()
    print(s.path.name, s.fetched_at, "spread", s.spread)
    for (p, l), e in s.expiries.items():
        print(f"{p} {l}: T={e.t:.3f} F={e.fwd:.2f} ATM IV={e.skew.atm:.3f} b={e.skew.b:.3f} c={e.skew.c:.3f} n_iv={len(e.ivs)}")
        print("   ", [x for x in e.ivs if abs(x[0] - e.fwd) <= 6][::2])
