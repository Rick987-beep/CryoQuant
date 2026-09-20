"""Dollar account + futures instrument / execution model.

Designed for cash-settled index futures (VIX / Mini VIX) marked in dollars.
Execution quality (fees, bid/ask, slippage) is centralized so studies can start
at mid with zero costs and tighten realism later without rewriting simulators.

Public interface::

    InstrumentSpec, VXM, VX
    ExecutionModel
    AccountConfig
    apply_fill_price, futures_pnl_dollars
    build_futures_equity
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

import numpy as np
import pandas as pd

Side = Literal["long", "short"]
BuySell = Literal["buy", "sell"]


@dataclass(frozen=True)
class InstrumentSpec:
    """Exchange contract economics."""

    symbol: str
    multiplier: float  # dollars per index point
    tick_size: float
    name: str = ""

    @property
    def tick_value(self) -> float:
        return self.multiplier * self.tick_size


# Cboe Mini VIX (VXM): $100 × index; tick 0.01 → $1
VXM = InstrumentSpec(
    symbol="VXM",
    multiplier=100.0,
    tick_size=0.01,
    name="Mini Cboe Volatility Index futures",
)

# Cboe VIX (VX): $1,000 × index; tick 0.05 → $50
VX = InstrumentSpec(
    symbol="VX",
    multiplier=1000.0,
    tick_size=0.05,
    name="Cboe Volatility Index futures",
)


@dataclass(frozen=True)
class ExecutionModel:
    """Modeled execution quality — all knobs default to frictionless mid.

    Fill convention (when costs are non-zero)
    ----------------------------------------
    - Mid is the simulator's theoretical touch/open/close price.
    - ``spread_ticks``: full quoted spread in ticks; buyer pays +half, seller −half.
    - ``slippage_ticks``: additional adverse ticks beyond the half-spread.
    - ``fee_per_side``: commission + exchange fees in **dollars per contract per side**.
    """

    fee_per_side: float = 0.0
    spread_ticks: float = 0.0
    slippage_ticks: float = 0.0

    def fill_price(
        self,
        mid: float,
        *,
        action: BuySell,
        instrument: InstrumentSpec,
    ) -> float:
        """Convert a mid price to a modeled executable price."""
        half = 0.5 * self.spread_ticks * instrument.tick_size
        slip = self.slippage_ticks * instrument.tick_size
        if action == "buy":
            return float(mid + half + slip)
        return float(mid - half - slip)

    def fee_dollars(self, contracts: int, *, sides: int = 1) -> float:
        return float(abs(int(contracts)) * self.fee_per_side * max(int(sides), 0))


@dataclass(frozen=True)
class AccountConfig:
    """Cash account + instrument + default lot size."""

    initial_cash: float = 100_000.0
    instrument: InstrumentSpec = VXM
    execution: ExecutionModel = field(default_factory=ExecutionModel)
    contracts: int = 1  # fixed lot; sizing policies can wrap later

    def with_contracts(self, n: int) -> AccountConfig:
        return AccountConfig(
            initial_cash=self.initial_cash,
            instrument=self.instrument,
            execution=self.execution,
            contracts=int(n),
        )


def apply_fill_price(
    mid: float,
    *,
    side: Side,
    is_entry: bool,
    account: AccountConfig,
) -> float:
    """Entry/exit mid → fill. Long entry/short exit buy; short entry/long exit sell."""
    if is_entry:
        action: BuySell = "buy" if side == "long" else "sell"
    else:
        action = "sell" if side == "long" else "buy"
    return account.execution.fill_price(
        mid, action=action, instrument=account.instrument
    )


def futures_pnl_dollars(
    *,
    side: Side,
    contracts: int,
    entry_price: float,
    exit_price: float,
    account: AccountConfig,
    charge_fees: bool = True,
) -> tuple[float, float, float]:
    """Return ``(gross_pnl, fee_dollars, net_pnl)`` for one round-trip."""
    qty = abs(int(contracts))
    sign = 1.0 if side == "long" else -1.0
    gross = sign * qty * account.instrument.multiplier * (exit_price - entry_price)
    fee = account.execution.fee_dollars(qty, sides=2) if charge_fees else 0.0
    return float(gross), float(fee), float(gross - fee)


def build_futures_equity(
    close: np.ndarray | Sequence[float],
    trades: Sequence[dict[str, Any]],
    *,
    account: AccountConfig,
) -> pd.Series:
    """Daily cash equity from futures variation margin + fees.

    Each trade dict must include ``entry_i``, ``exit_i``, ``side``, ``qty``,
    ``entry_price``, ``exit_price`` as **executable fills** (already passed
    through ``ExecutionModel`` if desired). Fees are charged per side from
    ``account.execution``.
    """
    c = np.asarray(close, dtype=float)
    n = len(c)
    if n == 0:
        return pd.Series(dtype=float, name="equity")

    entries = {int(t["entry_i"]): t for t in trades}
    exits = {int(t["exit_i"]): t for t in trades}

    cash = float(account.initial_cash)
    equity = np.empty(n, dtype=float)
    pos = 0
    prev_mark = float(c[0])

    for i in range(n):
        if i in entries and pos == 0:
            t = entries[i]
            side: Side = t["side"]  # type: ignore[assignment]
            qty = abs(int(t["qty"]))
            fill = float(t["entry_price"])
            cash -= account.execution.fee_dollars(qty, sides=1)
            pos = qty if side == "long" else -qty
            prev_mark = fill

        if i in exits and pos != 0:
            t = exits[i]
            qty = abs(int(t["qty"]))
            fill = float(t["exit_price"])
            cash += pos * account.instrument.multiplier * (fill - prev_mark)
            cash -= account.execution.fee_dollars(qty, sides=1)
            pos = 0
            prev_mark = float(c[i])
        elif pos != 0:
            cash += pos * account.instrument.multiplier * (float(c[i]) - prev_mark)
            prev_mark = float(c[i])
        else:
            prev_mark = float(c[i])

        equity[i] = cash

    return pd.Series(equity, name="equity")
