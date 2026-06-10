"""Phase 2a — Option leg pricing from daily Deribit chain snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cryoquant import config
from cryoquant.backtest.option_lookup import _best_leg, _load_chain_df, _to_deribit_expiry

from ._utils import chain_daily_snapshot, expiry_dte, nearest_strike, parse_deribit_expiry, pick_expiry_for_bucket


@dataclass(frozen=True)
class LegSpec:
    """How to select one option leg at entry."""

    is_call: bool
    strike_pct_otm: float | None = None  # e.g. -0.10 = 10% below spot for puts
    target_delta: float | None = None
    side: str = "long"  # long pays ask, short receives bid


@dataclass
class PricedLeg:
    as_of: date
    expiry: str
    strike: float
    is_call: bool
    qty: float
    spot: float
    mark_btc: float
    bid_btc: float
    ask_btc: float
    delta: float
    iv: float

    @property
    def mark_usd(self) -> float:
        return self.mark_btc * self.spot

    def _fill_btc(self, *, closing: bool) -> float:
        """Conservative fill: long entry=ask/exit=bid; short entry=bid/exit=ask."""
        if self.qty > 0:
            px = self.bid_btc if closing else self.ask_btc
        else:
            px = self.ask_btc if closing else self.bid_btc
        if px <= 0:
            px = self.mark_btc
        return px

    def mtm_usd(self, *, use_bid_ask: bool = True) -> float:
        """Mark-to-market per 1 BTC notional; bid/ask for conservative exit marks."""
        px = self._fill_btc(closing=True) if use_bid_ask else self.mark_btc
        return self.qty * px * self.spot

    def close_proceeds_usd(self) -> float:
        """Cash received (+) or paid (−) when closing at bid/ask."""
        return self.qty * self._fill_btc(closing=True) * self.spot


def load_daily_chain(d: date, chains_dir: Path | None = None) -> pd.DataFrame | None:
    chains_dir = chains_dir or config.CRYOBACKTESTER_DATA_DIR
    raw = _load_chain_df(chains_dir, d)
    if raw is None:
        return None
    return chain_daily_snapshot(raw)


def spot_on_date(d: date, snap: pd.DataFrame) -> float:
    return float(snap["underlying_price"].median())


def list_expiries(snap: pd.DataFrame, as_of: date, min_dte: int = 1) -> list[str]:
    exps = []
    for exp in snap["expiry"].astype(str).unique():
        if expiry_dte(exp, as_of) >= min_dte:
            exps.append(exp)
    return sorted(exps, key=lambda e: expiry_dte(e, as_of))


def pick_expiry_near_dte(snap: pd.DataFrame, as_of: date, target_dte: int, tol: int = 21) -> str | None:
    best: tuple[int, str] | None = None
    for exp in list_expiries(snap, as_of):
        dte = expiry_dte(exp, as_of)
        dist = abs(dte - target_dte)
        if dist <= tol and (best is None or dist < best[0]):
            best = (dist, exp)
    return best[1] if best else None


def _row_for_strike(snap: pd.DataFrame, expiry: str, strike: float, is_call: bool) -> pd.Series | None:
    sub = snap[(snap["expiry"] == expiry) & (snap["is_call"] == is_call)]
    if sub.empty:
        return None
    idx = (sub["strike"] - strike).abs().idxmin()
    row = sub.loc[idx]
    if float(row["mark_price"]) <= 0 and float(row["ask_price"]) <= 0:
        return None
    return row


def price_leg(
    snap: pd.DataFrame,
    as_of: date,
    *,
    expiry: str,
    spec: LegSpec,
    qty: float = 1.0,
    spot: float | None = None,
) -> PricedLeg | None:
    spot = spot or spot_on_date(as_of, snap)
    sub = snap[snap["expiry"] == expiry]
    if sub.empty:
        return None

    if spec.target_delta is not None:
        exp_date = parse_deribit_expiry(expiry)
        row = _best_leg(snap, exp_date, spec.target_delta, is_call=spec.is_call)
        if row is None:
            return None
    elif spec.strike_pct_otm is not None:
        if spec.is_call:
            target = spot * (1.0 + spec.strike_pct_otm)
        else:
            target = spot * (1.0 + spec.strike_pct_otm)  # negative pct = OTM put
        strike = nearest_strike(sub["strike"], target)
        row = _row_for_strike(snap, expiry, strike, spec.is_call)
        if row is None:
            return None
    else:
        strike = nearest_strike(sub["strike"], spot)
        row = _row_for_strike(snap, expiry, strike, spec.is_call)
        if row is None:
            return None

    mark = float(row["mark_price"]) if row["mark_price"] > 0 else float(row["ask_price"])
    bid = float(row["bid_price"])
    ask = float(row["ask_price"])
    sign = 1.0 if qty >= 0 else -1.0
    return PricedLeg(
        as_of=as_of,
        expiry=str(row["expiry"]),
        strike=float(row["strike"]),
        is_call=bool(row["is_call"]),
        qty=sign * abs(qty),
        spot=spot,
        mark_btc=mark,
        bid_btc=bid,
        ask_btc=ask,
        delta=float(row["delta"]),
        iv=float(row["mark_iv"]),
    )


def entry_cost_usd(legs: list[PricedLeg], *, use_ask_bid: bool = True) -> float:
    """Premium paid at entry (positive = net debit)."""
    total = 0.0
    for leg in legs:
        if use_ask_bid:
            px = leg._fill_btc(closing=False)
        else:
            px = leg.mark_btc
        total += leg.qty * px * leg.spot
    return total


def close_proceeds_usd(legs: list[PricedLeg]) -> float:
    """Net cash from closing all legs at bid/ask."""
    return sum(leg.close_proceeds_usd() for leg in legs)


def reprice_leg(snap: pd.DataFrame, leg: PricedLeg, as_of: date) -> PricedLeg | None:
    row = _row_for_strike(snap, leg.expiry, leg.strike, leg.is_call)
    if row is None:
        return None
    spot = spot_on_date(as_of, snap)
    mark = float(row["mark_price"]) if row["mark_price"] > 0 else float(row["ask_price"])
    return PricedLeg(
        as_of=as_of,
        expiry=leg.expiry,
        strike=leg.strike,
        is_call=leg.is_call,
        qty=leg.qty,
        spot=spot,
        mark_btc=mark,
        bid_btc=float(row["bid_price"]),
        ask_btc=float(row["ask_price"]),
        delta=float(row["delta"]),
        iv=float(row["mark_iv"]),
    )
