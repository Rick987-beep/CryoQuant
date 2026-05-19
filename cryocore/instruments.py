"""Symbol and Instrument definitions for CryoQuant.

Symbol  — a (venue, ticker) pair. Hashable, frozen, serialises to "venue:ticker".
Instrument — static metadata for a Symbol (asset class, quote ccy, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


AssetClass = Literal["crypto", "equity", "fx", "rates", "commodity", "option", "macro"]


@dataclass(frozen=True)
class Symbol:
    """A (venue, ticker) identifier.

    Examples::

        Symbol("binance.spot", "BTCUSDT")
        Symbol("deribit",      "BTC")
        Symbol("fred",         "DXY")
        Symbol("nyse",         "AAPL")
    """

    venue: str
    ticker: str

    def __str__(self) -> str:
        return f"{self.venue}:{self.ticker}"

    def __repr__(self) -> str:
        return f"Symbol({self.venue!r}, {self.ticker!r})"

    @classmethod
    def parse(cls, s: str) -> "Symbol":
        """Parse ``"venue:ticker"`` into a Symbol."""
        parts = s.split(":", 1)
        if len(parts) != 2:
            raise ValueError(f"invalid symbol string {s!r}; expected 'venue:ticker'")
        return cls(venue=parts[0], ticker=parts[1])


@dataclass(frozen=True)
class Instrument:
    """Static metadata about a Symbol.

    Loaded from a registry at startup; not stored alongside time series data.
    """

    symbol: Symbol
    asset_class: AssetClass
    quote_ccy: str
    calendar_id: str
    tick_size: float | None = None
    meta: dict[str, Any] = field(default_factory=dict, compare=False)

    def __repr__(self) -> str:
        return (
            f"Instrument({self.symbol!r}, asset_class={self.asset_class!r}, "
            f"quote_ccy={self.quote_ccy!r}, calendar_id={self.calendar_id!r})"
        )


def parse_symbol(s: str) -> Symbol:
    """Convenience alias for ``Symbol.parse(s)``."""
    return Symbol.parse(s)


# ---------------------------------------------------------------------------
# Default instrument definitions (extend as needed)
# ---------------------------------------------------------------------------

_DEFAULT_INSTRUMENTS: list[Instrument] = [
    Instrument(Symbol("binance.spot", "BTCUSDT"),  "crypto",    "USDT", "crypto_24_7"),
    Instrument(Symbol("binance.spot", "ETHUSDT"),  "crypto",    "USDT", "crypto_24_7"),
    Instrument(Symbol("binance.perp", "BTCUSDT"),  "crypto",    "USDT", "crypto_24_7"),
    Instrument(Symbol("binance.perp", "ETHUSDT"),  "crypto",    "USDT", "crypto_24_7"),
    Instrument(Symbol("deribit",      "BTC"),       "crypto",    "USD",  "crypto_24_7"),
    Instrument(Symbol("deribit",      "ETH"),       "crypto",    "USD",  "crypto_24_7"),
    Instrument(Symbol("fred",         "DXY"),       "macro",     "USD",  "nyse"),
    Instrument(Symbol("fred",         "VIX"),       "macro",     "USD",  "nyse"),
]

_INSTRUMENT_REGISTRY: dict[Symbol, Instrument] = {i.symbol: i for i in _DEFAULT_INSTRUMENTS}


def get_instrument(symbol: Symbol) -> Instrument | None:
    """Look up default instrument metadata. Returns None if not registered."""
    return _INSTRUMENT_REGISTRY.get(symbol)
