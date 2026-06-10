"""Deribit options taker fee model for hedged_btc NAV sim."""
from __future__ import annotations

from .pricing import PricedLeg

# Deribit taker schedule (per leg, per event) — see reference/long_tradable_options/
FEE_RATE_BTC = 0.0003   # 0.03% of 1 BTC underlying
FEE_CAP_RATIO = 0.125   # capped at 12.5% of option mark


def leg_fee_usd(mark_btc: float, spot_usd: float) -> float:
    """Fee for one leg on one event (entry or exit)."""
    if mark_btc <= 0:
        return 0.0
    fee_btc = min(FEE_RATE_BTC, FEE_CAP_RATIO * mark_btc)
    return fee_btc * spot_usd


def entry_fees_usd(legs: list[PricedLeg]) -> float:
    return sum(leg_fee_usd(leg.mark_btc, leg.spot) for leg in legs)


def exit_fees_usd(legs: list[PricedLeg]) -> float:
    return entry_fees_usd(legs)
