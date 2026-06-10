"""C7 — USD cash + long call participation sim vs BTCUSD buy-and-hold."""
from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from cryoquant.data.sources import deribit_options as deribit

from .cash_book import (
    CashBookPosition,
    CashParticipationSpec,
    book_mtm_usd,
    mark_cash_book,
    open_income_puts,
    pick_call_expiry,
    pick_put_expiry,
    scale_legs_to_budget,
    settle_expired_legs,
    should_roll_calls,
    should_roll_puts,
)
from .fees import entry_fees_usd, exit_fees_usd
from .nav_sim import NavResult, _compute_metrics
from .pricing import LegSpec, close_proceeds_usd, entry_cost_usd, load_daily_chain, spot_on_date

log = logging.getLogger(__name__)

_LEGS_ATM = [(LegSpec(is_call=True, strike_pct_otm=0.0), 1.0)]
_LEGS_OTM = [(LegSpec(is_call=True, strike_pct_otm=0.05), 1.0)]
_LEGS_SPREAD = [
    (LegSpec(is_call=True, strike_pct_otm=0.0), 1.0),
    (LegSpec(is_call=True, strike_pct_otm=0.15), -1.0),
]
_CSP = [(LegSpec(is_call=False, strike_pct_otm=-0.12), 1.0)]

SPEC_C7_ATM = CashParticipationSpec(name="C7_usd_atm_calls", participation_legs=_LEGS_ATM)
SPEC_C7_OTM = CashParticipationSpec(name="C7_usd_otm_calls", participation_legs=_LEGS_OTM)
SPEC_C7_SPREAD = CashParticipationSpec(name="C7_usd_call_spread", participation_legs=_LEGS_SPREAD)
SPEC_C7_ATM_CSP = CashParticipationSpec(
    name="C7_usd_atm_csp", participation_legs=_LEGS_ATM, income_legs=_CSP, income_put_qty=0.25,
)
SPEC_C7_OTM_CSP = CashParticipationSpec(
    name="C7_usd_otm_csp", participation_legs=_LEGS_OTM, income_legs=_CSP, income_put_qty=0.25,
)
SPEC_C7_SPREAD_CSP = CashParticipationSpec(
    name="C7_usd_spread_csp", participation_legs=_LEGS_SPREAD, income_legs=_CSP, income_put_qty=0.25,
)

C7_SPECS: dict[str, CashParticipationSpec] = {
    "C7_atm": SPEC_C7_ATM,
    "C7_otm": SPEC_C7_OTM,
    "C7_spread": SPEC_C7_SPREAD,
    "C7_atm_csp": SPEC_C7_ATM_CSP,
    "C7_otm_csp": SPEC_C7_OTM_CSP,
    "C7_spread_csp": SPEC_C7_SPREAD_CSP,
}


def _nav_usd(cash: float, pos: CashBookPosition | None, *, use_bid_ask: bool) -> float:
    opt = book_mtm_usd(pos, use_bid_ask=use_bid_ask) if pos else 0.0
    return cash + opt


def simulate_cash_participation(
    spec: CashParticipationSpec,
    dates: list[date] | None = None,
    *,
    start: date | None = None,
    end: date | None = None,
    use_fees: bool = True,
    use_bid_ask: bool = True,
) -> NavResult:
    """NAV = (USD cash + option MTM) / spot₀; benchmark BTC = spot/spot₀."""
    all_dates = dates or deribit.list_dates()
    if start:
        all_dates = [d for d in all_dates if d >= start]
    if end:
        all_dates = [d for d in all_dates if d <= end]
    if not all_dates:
        raise ValueError("No chain dates in range")

    nav_idx = pd.DatetimeIndex([pd.Timestamp(d) for d in all_dates], tz="UTC")
    nav = np.ones(len(all_dates), dtype=float)
    btc = np.ones(len(all_dates), dtype=float)
    roll_rows: list[dict] = []

    pos: CashBookPosition | None = None
    spot0: float | None = None
    cash_usd = 0.0
    total_fees = 0.0
    last_call_roll: date | None = None
    last_put_roll: date | None = None

    for i, d in enumerate(all_dates):
        snap = load_daily_chain(d)
        if snap is None or snap.empty:
            nav[i] = nav[i - 1] if i else 1.0
            btc[i] = btc[i - 1] if i else 1.0
            continue

        spot = spot_on_date(d, snap)
        if spot0 is None:
            spot0 = spot
            cash_usd = spot0

        btc[i] = spot / spot0

        if pos is not None:
            pos, cash_usd, sf = settle_expired_legs(pos, d, spot, cash_usd, use_fees)
            total_fees += sf

        roll_calls = should_roll_calls(pos, d, spec, last_call_roll)
        roll_puts = should_roll_puts(pos, d, spec, last_put_roll)
        open_puts = spec.income_legs and (roll_puts or (roll_calls and (pos is None or not pos.put_legs)))

        if roll_calls or open_puts:
            nav_now = _nav_usd(cash_usd, pos, use_bid_ask=use_bid_ask)
            budget = spec.call_budget_pct * nav_now
            fees_roll = 0.0

            call_legs: list = []
            put_legs: list = []
            call_exp: str | None = None
            put_exp: str | None = None
            opened = d

            if pos is not None:
                call_legs = list(pos.call_legs)
                put_legs = list(pos.put_legs)
                call_exp = pos.call_expiry
                put_exp = pos.put_expiry
                opened = pos.opened

            if roll_calls and call_legs:
                cash_usd += close_proceeds_usd(call_legs)
                if use_fees:
                    f = exit_fees_usd(call_legs)
                    cash_usd -= f
                    fees_roll += f
                call_legs = []
                call_exp = None

            if open_puts and put_legs:
                cash_usd += close_proceeds_usd(put_legs)
                if use_fees:
                    f = exit_fees_usd(put_legs)
                    cash_usd -= f
                    fees_roll += f
                put_legs = []
                put_exp = None

            if roll_calls:
                cexp = pick_call_expiry(snap, d, spec)
                if cexp:
                    new_calls = scale_legs_to_budget(
                        snap, d, spec.participation_legs, expiry=cexp, budget_usd=budget,
                    )
                    if new_calls:
                        cost = entry_cost_usd(new_calls)
                        cash_usd -= cost
                        if use_fees:
                            f = entry_fees_usd(new_calls)
                            cash_usd -= f
                            fees_roll += f
                        call_legs = new_calls
                        call_exp = cexp
                        last_call_roll = d

            if open_puts:
                pexp = pick_put_expiry(snap, d, spec)
                if pexp:
                    new_puts = open_income_puts(snap, d, spec, expiry=pexp)
                    if new_puts:
                        cash_usd -= entry_cost_usd(new_puts)
                        if use_fees:
                            f = entry_fees_usd(new_puts)
                            cash_usd -= f
                            fees_roll += f
                        put_legs = new_puts
                        put_exp = pexp
                        last_put_roll = d

            if call_legs or put_legs:
                pos = CashBookPosition(
                    opened=opened,
                    call_expiry=call_exp,
                    call_legs=call_legs,
                    put_expiry=put_exp,
                    put_legs=put_legs,
                )
                total_fees += fees_roll
                roll_rows.append({
                    "date": str(d),
                    "call_expiry": call_exp or "",
                    "put_expiry": put_exp or "",
                    "call_budget_usd": budget,
                    "cash_usd": cash_usd,
                    "spot": spot,
                    "n_call_legs": len(call_legs),
                    "n_put_legs": len(put_legs),
                })
            elif pos is not None and not call_legs and not put_legs:
                pos = None

        if pos is not None:
            marked = mark_cash_book(snap, pos, d)
            if marked:
                pos = marked

        nav[i] = _nav_usd(cash_usd, pos, use_bid_ask=use_bid_ask) / spot0

    nav_s = pd.Series(nav, index=nav_idx, name="nav")
    btc_s = pd.Series(btc, index=nav_idx, name="btc")
    metrics = _compute_metrics(nav_s, btc_s)
    metrics["n_rolls"] = len(roll_rows)
    metrics["total_fees_usd"] = total_fees
    metrics["call_budget_pct"] = spec.call_budget_pct
    metrics["base"] = "usd_cash"
    return NavResult(
        name=spec.name, nav=nav_s, btc=btc_s, rolls=pd.DataFrame(roll_rows), metrics=metrics,
    )
