"""Phase 2d — Daily NAV simulator for multi-leg option books vs BTCUSD."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from cryoquant.data.sources import deribit_options as deribit

from .book import (
    BookPosition,
    BookSpec,
    RollPolicy,
    book_option_mtm_usd,
    mark_book,
    open_book,
    open_sleeve_legs,
)
from .fees import entry_fees_usd, exit_fees_usd
from .pricing import LegSpec, close_proceeds_usd, entry_cost_usd, load_daily_chain, spot_on_date
from .roll_rules import evaluate_rolls, pick_income_expiry, pick_protection_expiry

log = logging.getLogger(__name__)


SPEC_C1_COLLAR = BookSpec(
    name="C1_collar_reopener",
    protection_legs=[
        (LegSpec(is_call=False, strike_pct_otm=0.0), 1.0),
        (LegSpec(is_call=True, strike_pct_otm=0.13), -1.0),
        (LegSpec(is_call=True, strike_pct_otm=0.21), 1.0),
    ],
    protection_tenor_dte=90,
    roll_min_dte=14,
    roll_policy=RollPolicy(ratchet_pct=0.12, iv_ceiling_pct=55.0),
)

SPEC_C2_BUFFER = BookSpec(
    name="C2_put_spread_short_call",
    protection_legs=[
        (LegSpec(is_call=False, strike_pct_otm=0.0), 1.0),
        (LegSpec(is_call=False, strike_pct_otm=-0.10), -1.0),
        (LegSpec(is_call=True, strike_pct_otm=0.10), -1.0),
    ],
    protection_tenor_dte=45,
    roll_min_dte=7,
    roll_policy=RollPolicy(ratchet_pct=None, iv_ceiling_pct=60.0),
)

SPEC_C3_DIAGONAL = BookSpec(
    name="C3_skew_diagonal",
    protection_legs=[
        (LegSpec(is_call=False, strike_pct_otm=0.0), 1.0),
    ],
    income_legs=[
        (LegSpec(is_call=True, strike_pct_otm=0.07), -1.0),
    ],
    protection_tenor_dte=90,
    income_tenor_dte=12,
    roll_min_dte=14,
    income_roll_min_dte=2,
    roll_policy=RollPolicy(ratchet_pct=0.10, iv_ceiling_pct=55.0),
)

SPEC_C4_FOUR_LAYER = BookSpec(
    name="C4_four_layer",
    protection_legs=[
        (LegSpec(is_call=False, strike_pct_otm=0.0), 1.0),
        (LegSpec(is_call=False, strike_pct_otm=-0.19), -1.0),
        (LegSpec(is_call=False, strike_pct_otm=-0.06), -1.0),
        (LegSpec(is_call=False, strike_pct_otm=-0.19), 2.0),
    ],
    income_legs=[
        (LegSpec(is_call=True, strike_pct_otm=0.10), -1.0),
    ],
    protection_tenor_dte=105,
    income_tenor_dte=14,
    roll_min_dte=21,
    income_roll_min_dte=3,
    roll_policy=RollPolicy(ratchet_pct=0.12, iv_ceiling_pct=55.0),
)

SPEC_C6_TAIL = BookSpec(
    name="C6_tail_put",
    protection_legs=[
        (LegSpec(is_call=False, strike_pct_otm=-0.16), 1.0),
    ],
    protection_tenor_dte=90,
    roll_min_dte=14,
    roll_policy=RollPolicy(ratchet_pct=None, iv_ceiling_pct=65.0),
)

CANDIDATE_SPECS: dict[str, BookSpec] = {
    "C1_collar": SPEC_C1_COLLAR,
    "C2_buffer": SPEC_C2_BUFFER,
    "C3_diagonal": SPEC_C3_DIAGONAL,
    "C4_four_layer": SPEC_C4_FOUR_LAYER,
    "C6_tail": SPEC_C6_TAIL,
}


@dataclass
class NavResult:
    name: str
    nav: pd.Series
    btc: pd.Series
    rolls: pd.DataFrame
    metrics: dict


def _apply_roll(
    snap: pd.DataFrame,
    d: date,
    spec: BookSpec,
    *,
    roll_prot: bool,
    roll_inc: bool,
    pos: BookPosition | None,
    cash_usd: float,
    use_fees: bool,
) -> tuple[BookPosition | None, float, float]:
    """Close/open sleeves; return (position, cash, fees_usd)."""
    fees = 0.0

    if pos is None:
        prot_exp = pick_protection_expiry(snap, d, spec)
        if prot_exp is None:
            return None, cash_usd, 0.0
        inc_exp = pick_income_expiry(snap, d, spec) if spec.income_legs else None
        new_pos = open_book(snap, d, spec, protection_expiry=prot_exp, income_expiry=inc_exp)
        if new_pos is None:
            return None, cash_usd, 0.0
        cash_usd -= new_pos.entry_cost_usd
        if use_fees:
            f = entry_fees_usd(new_pos.legs)
            cash_usd -= f
            fees += f
        return new_pos, cash_usd, fees

    prot_legs = pos.protection_legs
    inc_legs = pos.income_legs
    prot_exp = pos.protection_expiry
    inc_exp = pos.income_expiry
    opened = pos.opened
    spot_open = pos.spot_at_open

    if roll_prot:
        cash_usd += close_proceeds_usd(prot_legs)
        if use_fees:
            f = exit_fees_usd(prot_legs)
            cash_usd -= f
            fees += f
        prot_exp = pick_protection_expiry(snap, d, spec)
        if prot_exp is None:
            return pos, cash_usd, fees
        new_prot = open_sleeve_legs(snap, d, spec.protection_legs, expiry=prot_exp)
        if new_prot is None:
            return pos, cash_usd, fees
        prot_legs = new_prot
        opened = d
        spot_open = prot_legs[0].spot
        cost = entry_cost_usd(prot_legs)
        cash_usd -= cost
        if use_fees:
            f = entry_fees_usd(prot_legs)
            cash_usd -= f
            fees += f

    if roll_inc and spec.income_legs:
        if inc_legs:
            cash_usd += close_proceeds_usd(inc_legs)
            if use_fees:
                f = exit_fees_usd(inc_legs)
                cash_usd -= f
                fees += f
        inc_exp = pick_income_expiry(snap, d, spec)
        if inc_exp is None:
            inc_legs = []
        else:
            new_inc = open_sleeve_legs(snap, d, spec.income_legs, expiry=inc_exp)
            if new_inc is None:
                return pos, cash_usd, fees
            inc_legs = new_inc
            cost = entry_cost_usd(inc_legs)
            cash_usd -= cost
            if use_fees:
                f = entry_fees_usd(inc_legs)
                cash_usd -= f
                fees += f

    new_pos = BookPosition(
        opened=opened,
        protection_expiry=prot_exp,
        protection_legs=prot_legs,
        income_expiry=inc_exp if spec.income_legs else None,
        income_legs=inc_legs,
        entry_cost_usd=entry_cost_usd(prot_legs + inc_legs),
        spot_at_open=spot_open,
    )
    return new_pos, cash_usd, fees


def simulate_book(
    spec: BookSpec,
    dates: list[date] | None = None,
    *,
    start: date | None = None,
    end: date | None = None,
    use_fees: bool = True,
    use_bid_ask: bool = True,
) -> NavResult:
    """Daily mark: NAV = (spot + option_mtm + cash_premiums) / spot0 for 1 BTC unit."""
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

    pos: BookPosition | None = None
    spot0: float | None = None
    cash_usd = 0.0
    total_fees = 0.0

    for i, d in enumerate(all_dates):
        snap = load_daily_chain(d)
        if snap is None or snap.empty:
            nav[i] = nav[i - 1] if i else 1.0
            btc[i] = btc[i - 1] if i else 1.0
            continue

        spot = spot_on_date(d, snap)
        if spot0 is None:
            spot0 = spot
        btc[i] = spot / spot0

        decision = evaluate_rolls(pos, d, snap, spec, spot)
        if decision.roll_protection or decision.roll_income:
            new_pos, cash_usd, roll_fees = _apply_roll(
                snap, d, spec,
                roll_prot=decision.roll_protection,
                roll_inc=decision.roll_income,
                pos=pos,
                cash_usd=cash_usd,
                use_fees=use_fees,
            )
            if new_pos is not None and new_pos is not pos:
                total_fees += roll_fees
                pos = new_pos
                roll_rows.append({
                    "date": str(d),
                    "protection_expiry": pos.protection_expiry,
                    "income_expiry": pos.income_expiry or "",
                    "reason": decision.reason,
                    "ratchet": decision.ratchet,
                    "iv_blocked": decision.iv_blocked,
                    "entry_cost_usd": pos.entry_cost_usd,
                    "spot": spot,
                    "n_legs": len(pos.legs),
                })

        opt_usd = 0.0
        if pos is not None:
            marked = mark_book(snap, pos, d)
            if marked:
                pos = marked
                opt_usd = book_option_mtm_usd(pos, use_bid_ask=use_bid_ask)

        nav[i] = (spot + opt_usd + cash_usd) / spot0

    nav_s = pd.Series(nav, index=nav_idx, name="nav")
    btc_s = pd.Series(btc, index=nav_idx, name="btc")
    metrics = _compute_metrics(nav_s, btc_s)
    metrics["n_rolls"] = len(roll_rows)
    metrics["total_fees_usd"] = total_fees
    metrics["use_fees"] = use_fees
    metrics["use_bid_ask"] = use_bid_ask
    return NavResult(name=spec.name, nav=nav_s, btc=btc_s, rolls=pd.DataFrame(roll_rows), metrics=metrics)


def _compute_metrics(nav: pd.Series, btc: pd.Series) -> dict:
    peak = nav.cummax()
    dd = (nav - peak) / peak
    btc_dd = (btc - btc.cummax()) / btc.cummax()

    nav_ret = nav.pct_change().dropna()
    btc_ret = btc.pct_change().dropna()
    aligned = pd.concat([nav_ret, btc_ret], axis=1, keys=["nav", "btc"]).dropna()

    up_mask = aligned["btc"] > 0
    down_mask = aligned["btc"] < 0
    cap_up = None
    cap_down = None
    if up_mask.any() and aligned.loc[up_mask, "btc"].sum() != 0:
        cap_up = float(aligned.loc[up_mask, "nav"].sum() / aligned.loc[up_mask, "btc"].sum())
    if down_mask.any() and aligned.loc[down_mask, "btc"].sum() != 0:
        cap_down = float(aligned.loc[down_mask, "nav"].sum() / aligned.loc[down_mask, "btc"].sum())

    return {
        "total_return": float(nav.iloc[-1] / nav.iloc[0] - 1),
        "btc_total_return": float(btc.iloc[-1] / btc.iloc[0] - 1),
        "max_drawdown": float(dd.min()),
        "btc_max_drawdown": float(btc_dd.min()),
        "upside_capture": cap_up,
        "downside_capture": cap_down,
        "n_days": len(nav),
    }
