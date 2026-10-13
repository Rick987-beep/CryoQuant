"""Black-76 option pricing, skew fit, and bid/ask costing for OOAT / OGBL / equity options.

Grounded in live Eurex chain quotes. Entry fills cross the spread (buy ask / sell bid).
Later rolls and exits use the observed half-spread for the moneyness / DTE bucket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

import numpy as np
from scipy.optimize import brentq
from scipy.special import ndtr

R = 0.02  # discount for Black-76 (matching v4/v5)
TICK = {"OOAT": 0.25, "OGBL": 0.5, "BNP": 0.05, "GLE": 0.05, "ACA": 0.05}
# Fallback half-spreads when the chain has no two-sided quote in the bucket (points).
# OOAT is thin; OGBL is tight. Equity defaults are conservative.
DEFAULT_HALF = {"OOAT": 0.09, "OGBL": 0.01, "BNP": 0.05, "GLE": 0.08, "ACA": 0.08}
# Swissquote Eurex options: publishable tariff not confirmed live; conservative €2.50/side.
# Flagged in RESULTS. Futures remain €2.00 (Lynx blotter).
OPT_FEE_EUR = 2.50
OPT_MULT = 1000.0  # € per futures point for OOAT/OGBL options
EQUITY_OPT_MULT = 100.0  # typical Eurex equity option multiplier


def num(x: Any) -> Optional[float]:
    if x in (None, "", "-"):
        return None
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def b76(f, k, t, sig, call: bool):
    """Black-76 price (futures options)."""
    f, k, t, sig = (np.asarray(x, dtype=float) for x in (f, k, t, sig))
    t = np.maximum(t, 1e-8)
    srt = np.maximum(sig, 1e-8) * np.sqrt(t)
    d1 = (np.log(np.maximum(f, 1e-12) / np.maximum(k, 1e-12)) + 0.5 * srt * srt) / srt
    d2 = d1 - srt
    df = np.exp(-R * t)
    c = df * (f * ndtr(d1) - k * ndtr(d2))
    p = df * (k * ndtr(-d2) - f * ndtr(-d1))
    return np.where(call, c, p)


def implied_vol(price: float, f: float, k: float, t: float, call: bool) -> Optional[float]:
    intrinsic = max(f - k, 0.0) if call else max(k - f, 0.0)
    floor = intrinsic * np.exp(-R * t) + 1e-4
    if price <= floor:
        return None
    try:
        return float(brentq(lambda s: float(b76(f, k, t, s, call)) - price, 0.005, 2.5))
    except ValueError:
        return None


@dataclass
class Quote:
    bid: Optional[float]
    ask: Optional[float]
    settle: Optional[float] = None
    open_int: Optional[float] = None
    volume: Optional[float] = None

    @property
    def mid(self) -> Optional[float]:
        if self.bid is None or self.ask is None or self.bid <= 0:
            return None
        return 0.5 * (self.bid + self.ask)

    @property
    def two_sided(self) -> bool:
        return (
            self.bid is not None
            and self.ask is not None
            and self.bid > 0
            and self.ask > self.bid
        )

    @property
    def half_spread(self) -> Optional[float]:
        if not self.two_sided:
            return None
        return 0.5 * (self.ask - self.bid)  # type: ignore[operator]


@dataclass
class Skew:
    """Implied vol as a quadratic in standardised moneyness m = ln(K/F)/sqrt(T)."""

    atm: float
    b: float
    c: float

    def vol(self, f, k, t, atm: float | None = None):
        f = np.asarray(f, dtype=float)
        k = np.asarray(k, dtype=float)
        t = np.maximum(np.asarray(t, dtype=float), 1e-8)
        m = np.log(np.maximum(k, 1e-12) / np.maximum(f, 1e-12)) / np.sqrt(t)
        ratio = np.clip(1.0 + self.b * m + self.c * m * m, 0.6, 2.5)
        return (self.atm if atm is None else atm) * ratio

    def to_dict(self) -> dict[str, float]:
        return {"atm": self.atm, "b": self.b, "c": self.c}


@dataclass
class Expiry:
    product: str
    label: str
    date: date
    t: float
    quotes: dict[str, dict[float, Quote]]
    fwd: float
    skew: Skew
    ivs: list
    half_spread_table: dict[str, float] = field(default_factory=dict)

    def cost(self, cp: str, k: float, side: int) -> Optional[float]:
        """Live fill: buy at ask (side>0), sell at bid (side<0). Two-sided required."""
        q = self.quotes.get(cp, {}).get(float(k))
        if q is None or not q.two_sided:
            return None
        px = q.ask if side > 0 else q.bid
        return px if px and px > 0 else None

    def half_spread(self, cp: str, k: float) -> float:
        q = self.quotes.get(cp, {}).get(float(k))
        if q and q.half_spread is not None:
            return float(q.half_spread)
        # Bucket by moneyness relative to forward.
        m = abs(float(k) - self.fwd)
        key = "near" if m <= 1.0 else ("mid" if m <= 3.0 else "far")
        if key in self.half_spread_table:
            return self.half_spread_table[key]
        return DEFAULT_HALF.get(self.product, 0.05)


def parity_forward(quotes: dict, near: float) -> float:
    est = []
    for k, c in quotes["C"].items():
        p = quotes["P"].get(k)
        if p and c.mid and p.mid and abs(k - near) <= 2.5:
            est.append(k + c.mid - p.mid)
    if not est:
        return float(near)
    return float(np.median(est))


def fit_skew(quotes: dict, f: float, t: float) -> tuple[Skew, list]:
    pts = []
    for cp, is_call in (("P", False), ("C", True)):
        for k, q in quotes[cp].items():
            otm = k < f if cp == "P" else k >= f
            if not (otm and q.mid and q.two_sided):
                continue
            if q.ask - q.bid > max(0.25, 0.6 * q.mid):  # type: ignore[operator]
                continue
            iv = implied_vol(q.mid, f, k, t, is_call)
            if iv:
                pts.append((k, np.log(k / f) / np.sqrt(t), iv))
    if len(pts) < 3:
        # Degenerate: ATM ~ 5% or whatever we can salvage.
        atm = float(np.median([p[2] for p in pts])) if pts else 0.08
        return Skew(atm=atm, b=0.0, c=0.0), [(round(k, 2), round(v, 4)) for k, _, v in sorted(pts)]
    m = np.array([p[1] for p in pts])
    iv = np.array([p[2] for p in pts])
    c2, c1, c0 = np.polyfit(m, iv, 2)
    return Skew(atm=float(c0), b=float(c1 / c0), c=float(c2 / c0)), [
        (round(k, 2), round(v, 4)) for k, _, v in sorted(pts)
    ]


def _half_spread_buckets(quotes: dict, f: float) -> dict[str, float]:
    buckets: dict[str, list[float]] = {"near": [], "mid": [], "far": []}
    for cp in ("P", "C"):
        for k, q in quotes[cp].items():
            hs = q.half_spread
            if hs is None:
                continue
            m = abs(k - f)
            key = "near" if m <= 1.0 else ("mid" if m <= 3.0 else "far")
            buckets[key].append(hs)
    return {k: float(np.median(v)) for k, v in buckets.items() if v}


@dataclass
class OptionSnapshot:
    path: str
    fetched_at: datetime
    oat10: float
    bund10: float
    expiries: dict[tuple[str, str], Expiry]
    futures: dict
    bank_expiries: dict[tuple[str, str], Expiry] = field(default_factory=dict)
    fee_note: str = (
        "Swissquote Eurex options fee assumed €2.50/contract/side "
        "(published tariff not confirmed live; sensitivity in RESULTS)."
    )

    @property
    def spread(self) -> float:
        return round((self.oat10 - self.bund10) * 100, 2)

    @property
    def val_date(self) -> date:
        return self.fetched_at.date()

    def best_front(self, product: str, *, min_days: int = 14) -> Expiry | None:
        """Nearest expiry with at least ``min_days`` to go and a fitted skew."""
        cands = [
            e
            for (p, _), e in self.expiries.items()
            if p == product and (e.date - self.val_date).days >= min_days
        ]
        if not cands:
            return None
        return min(cands, key=lambda e: e.date)


def _parse_chain_block(
    product: str,
    label: str,
    ch: dict,
    val_date: date,
) -> Expiry | None:
    if not ch:
        return None
    d = datetime.strptime(label, "%d/%m/%Y").date()
    t = max((d - val_date).days, 1) / 365.0
    quotes: dict[str, dict[float, Quote]] = {"P": {}, "C": {}}
    for cp, key in (("P", "put"), ("C", "call")):
        for r in ch.get(key) or []:
            k = num(r.get("strikePrice"))
            if k is None:
                continue
            quotes[cp][float(k)] = Quote(
                bid=num(r.get("bid")),
                ask=num(r.get("ask")),
                settle=num(r.get("dSettle")),
                open_int=num(r.get("openInt")),
                volume=num(r.get("volume")),
            )
    if not quotes["C"] and not quotes["P"]:
        return None
    strikes = list(quotes["C"]) or list(quotes["P"])
    near = float(np.median(strikes))
    fwd = parity_forward(quotes, near)
    fwd = parity_forward(quotes, fwd)
    skew, ivs = fit_skew(quotes, fwd, t)
    return Expiry(
        product=product,
        label=label,
        date=d,
        t=t,
        quotes=quotes,
        fwd=fwd,
        skew=skew,
        ivs=ivs,
        half_spread_table=_half_spread_buckets(quotes, fwd),
    )


def load_option_snapshot(raw: dict[str, Any], *, path: str = "") -> OptionSnapshot:
    """Build an OptionSnapshot from a snapshot JSON dict (eurex_*.json)."""
    fetched = datetime.fromisoformat(raw["fetched_at"].replace("Z", "+00:00"))
    if fetched.tzinfo is not None:
        fetched = fetched.replace(tzinfo=None)
    val = fetched.date()
    exps: dict[tuple[str, str], Expiry] = {}
    for product, chains in (raw.get("chains") or {}).items():
        for label, ch in chains.items():
            e = _parse_chain_block(product, label, ch, val)
            if e is not None:
                exps[(product, label)] = e
    bank_exps: dict[tuple[str, str], Expiry] = {}
    for product, chains in (raw.get("bank_chains") or {}).items():
        for label, ch in chains.items():
            e = _parse_chain_block(product, label, ch, val)
            if e is not None:
                bank_exps[(product, label)] = e
    y = raw["yields"]
    return OptionSnapshot(
        path=path,
        fetched_at=fetched,
        oat10=float(y["oat10"]),
        bund10=float(y["bund10"]),
        expiries=exps,
        futures=raw.get("futures") or {},
        bank_expiries=bank_exps,
    )


@dataclass(frozen=True)
class Leg:
    product: str
    cp: str  # "P" or "C"
    k: float
    q: int  # +1 long, -1 short

    @property
    def text(self) -> str:
        side = "Buy" if self.q > 0 else "Sell"
        kind = "put" if self.cp == "P" else "call"
        return f"{side} {abs(self.q)} {self.product} {self.k:g} {kind}"


@dataclass(frozen=True)
class Structure:
    name: str
    legs: tuple[Leg, ...]

    @property
    def product(self) -> str:
        return self.legs[0].product

    @property
    def n_contracts(self) -> int:
        return sum(abs(l.q) for l in self.legs)

    def live_cost(self, exp: Expiry) -> Optional[float]:
        total = 0.0
        for l in self.legs:
            # Cross-product structures need the matching expiry; single-product only here.
            if l.product != exp.product:
                return None
            px = exp.cost(l.cp, l.k, l.q)
            if px is None:
                return None
            total += px * l.q
        return total

    def model_cost(
        self,
        f: float | np.ndarray,
        t: float | np.ndarray,
        skew: Skew,
        atm: float | np.ndarray,
        *,
        half_spreads: dict[str, float] | None = None,
        strikes: list | None = None,
    ) -> np.ndarray:
        """Debit at mid ± half-spread for each leg (sign of q)."""
        half_spreads = half_spreads or {}
        out = 0.0
        for i, l in enumerate(self.legs):
            k = strikes[i] if strikes is not None else l.k
            mid = b76(f, k, t, skew.vol(f, k, t, atm), l.cp == "C")
            hs = half_spreads.get(l.product, DEFAULT_HALF.get(l.product, 0.05))
            out = out + l.q * mid + np.sign(l.q) * abs(l.q) * hs
        return np.asarray(out, dtype=float)

    def close_value(
        self,
        strikes: list,
        f: float | np.ndarray,
        t_rem: float | np.ndarray,
        skew: Skew,
        atm: float | np.ndarray,
        *,
        half_spreads: dict[str, float] | None = None,
    ) -> np.ndarray:
        half_spreads = half_spreads or {}
        t_rem = np.maximum(t_rem, 1 / 365)
        out = 0.0
        for l, k in zip(self.legs, strikes):
            mid = b76(f, k, t_rem, skew.vol(f, k, t_rem, atm), l.cp == "C")
            hs = half_spreads.get(l.product, DEFAULT_HALF.get(l.product, 0.05))
            # Long sold at mid − hs; short bought back at mid + hs → subtract |q|*hs
            out = out + l.q * mid - abs(l.q) * hs
        return np.maximum(np.asarray(out, dtype=float), 0.0)

    def payoff_at(self, strikes: list, f: float | np.ndarray) -> np.ndarray:
        out = 0.0
        for l, k in zip(self.legs, strikes):
            out = out + l.q * (
                np.maximum(k - f, 0) if l.cp == "P" else np.maximum(f - k, 0)
            )
        return np.asarray(out, dtype=float)

    def rolled_strikes(self, f_ref: float, f_new: np.ndarray) -> list[np.ndarray]:
        tick = TICK.get(self.product, 0.25)
        out = []
        for l in self.legs:
            k2 = np.round((f_new + (l.k - f_ref)) / tick) * tick
            out.append(k2)
        return out


def single(product: str, cp: str, k: float) -> Structure:
    kind = "put" if cp == "P" else "call"
    return Structure(f"{product} {k:g} {kind}", (Leg(product, cp, k, 1),))


def vertical(product: str, cp: str, k_long: float, k_short: float) -> Structure:
    kind = "put" if cp == "P" else "call"
    return Structure(
        f"{product} {k_long:g}/{k_short:g} {kind} spread",
        (Leg(product, cp, k_long, 1), Leg(product, cp, k_short, -1)),
    )


def eurex_expiry(year: int, month: int) -> date:
    """Last trading day of an Eurex bond-option contract month."""
    from datetime import timedelta

    holidays = {
        date(2026, 12, 24),
        date(2026, 12, 25),
        date(2026, 12, 31),
        date(2027, 1, 1),
        date(2027, 3, 26),
        date(2027, 3, 29),
        date(2027, 12, 24),
        date(2027, 12, 31),
    }

    def exchange_day(d: date) -> bool:
        return d.weekday() < 5 and d not in holidays

    first = date(year, month, 1)
    d = first - timedelta(days=1)
    while d.weekday() != 4:
        d -= timedelta(days=1)
    gap = sum(exchange_day(d + timedelta(days=i)) for i in range(1, (first - d).days))
    if gap < 2:
        d -= timedelta(days=7)
    while not exchange_day(d):
        d -= timedelta(days=1)
    return d


def roll_schedule(first: date, cadence_months: int, end: date) -> list[date]:
    """Cadence≈2 ≈ 8-week roll (second-nearest serial)."""
    months = [
        (first.year + (first.month - 1 + i) // 12, (first.month - 1 + i) % 12 + 1)
        for i in range(24)
    ]
    expiries = sorted({eurex_expiry(y, m) for y, m in months} | {first})
    expiries = [e for e in expiries if e >= first]
    out = [first]
    i = 0
    while out[-1] < end and i + cadence_months < len(expiries):
        i += cadence_months
        out.append(expiries[i])
    return out
