"""Symbol and Instrument definitions for CryoQuant.

Symbol  — a (venue, ticker) pair. Hashable, frozen, serialises to "venue:ticker".
Instrument — static metadata for a Symbol (asset class, quote ccy, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


AssetClass = Literal["crypto", "equity", "fx", "rates", "commodity", "option", "macro", "volatility"]


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
    # Crypto
    Instrument(Symbol("binance.spot", "BTCUSDT"),  "crypto",    "USDT", "crypto_24_7"),
    Instrument(Symbol("binance.spot", "ETHUSDT"),  "crypto",    "USDT", "crypto_24_7"),
    Instrument(Symbol("binance.perp", "BTCUSDT"),  "crypto",    "USDT", "crypto_24_7"),
    Instrument(Symbol("binance.perp", "ETHUSDT"),  "crypto",    "USDT", "crypto_24_7"),
    Instrument(Symbol("deribit",      "BTC"),       "crypto",    "USD",  "crypto_24_7"),
    Instrument(Symbol("deribit",      "ETH"),       "crypto",    "USD",  "crypto_24_7"),

    # Macro (FRED)
    Instrument(Symbol("fred",         "DXY"),       "macro",     "USD",  "nyse"),
    Instrument(Symbol("fred",         "VIX"),       "macro",     "USD",  "nyse"),

    # US equity index ETFs (Yahoo)
    Instrument(Symbol("yahoo", "SPY"),   "equity",    "USD", "nyse"),
    Instrument(Symbol("yahoo", "QQQ"),   "equity",    "USD", "nyse"),
    Instrument(Symbol("yahoo", "DIA"),   "equity",    "USD", "nyse"),
    Instrument(Symbol("yahoo", "IWM"),   "equity",    "USD", "nyse"),

    # US sector ETFs (Yahoo)
    Instrument(Symbol("yahoo", "XLK"),   "equity",    "USD", "nyse"),
    Instrument(Symbol("yahoo", "XLE"),   "equity",    "USD", "nyse"),
    Instrument(Symbol("yahoo", "XLF"),   "equity",    "USD", "nyse"),
    Instrument(Symbol("yahoo", "XLB"),   "equity",    "USD", "nyse"),
    Instrument(Symbol("yahoo", "XLI"),   "equity",    "USD", "nyse"),
    Instrument(Symbol("yahoo", "XLY"),   "equity",    "USD", "nyse"),
    Instrument(Symbol("yahoo", "XLP"),   "equity",    "USD", "nyse"),
    Instrument(Symbol("yahoo", "XLV"),   "equity",    "USD", "nyse"),
    Instrument(Symbol("yahoo", "XLU"),   "equity",    "USD", "nyse"),
    Instrument(Symbol("yahoo", "XLRE"),  "equity",    "USD", "nyse"),

    # Gold / precious metals (Yahoo ETFs)
    Instrument(Symbol("yahoo", "GLD"),   "commodity", "USD", "nyse"),
    Instrument(Symbol("yahoo", "SLV"),   "commodity", "USD", "nyse"),

    # Commodity ETFs (Yahoo)
    Instrument(Symbol("yahoo", "USO"),   "commodity", "USD", "nyse"),
    Instrument(Symbol("yahoo", "PDBC"),  "commodity", "USD", "nyse"),

    # Continuous futures (Yahoo — roll noise; prefer ETF proxies for backtesting)
    Instrument(Symbol("yahoo", "GC=F"),  "commodity", "USD", "cme_futures"),
    Instrument(Symbol("yahoo", "SI=F"),  "commodity", "USD", "cme_futures"),
    Instrument(Symbol("yahoo", "CL=F"),  "commodity", "USD", "cme_futures"),
    Instrument(Symbol("yahoo", "BZ=F"),  "commodity", "USD", "cme_futures"),
    Instrument(Symbol("yahoo", "NG=F"),  "commodity", "USD", "cme_futures"),
    Instrument(Symbol("yahoo", "HG=F"),  "commodity", "USD", "cme_futures"),
    Instrument(Symbol("yahoo", "ZC=F"),  "commodity", "USD", "cme_futures"),
    Instrument(Symbol("yahoo", "ZW=F"),  "commodity", "USD", "cme_futures"),
    Instrument(Symbol("yahoo", "ZS=F"),  "commodity", "USD", "cme_futures"),
    Instrument(Symbol("yahoo", "ES=F"),  "equity",    "USD", "cme_futures"),
    Instrument(Symbol("yahoo", "NQ=F"),  "equity",    "USD", "cme_futures"),

    # FX majors (Yahoo — spot mid, no spread)
    # EURUSD=X, GBPUSD=X, AUDUSD=X are direct (1 USD per foreign unit)
    # JPY=X, CAD=X are INVERTED by Yahoo (USD per unit of foreign); normalised in cleaning
    Instrument(Symbol("yahoo", "EURUSD=X"), "fx", "USD", "fx_24_5",
               meta={"quote_convention": "direct",   "base": "EUR", "quote": "USD"}),
    Instrument(Symbol("yahoo", "GBPUSD=X"), "fx", "USD", "fx_24_5",
               meta={"quote_convention": "direct",   "base": "GBP", "quote": "USD"}),
    Instrument(Symbol("yahoo", "AUDUSD=X"), "fx", "USD", "fx_24_5",
               meta={"quote_convention": "direct",   "base": "AUD", "quote": "USD"}),
    Instrument(Symbol("yahoo", "JPY=X"),    "fx", "USD", "fx_24_5",
               meta={"quote_convention": "inverted", "base": "USD", "quote": "JPY",
                     "normalised_ticker": "USDJPY"}),
    Instrument(Symbol("yahoo", "CAD=X"),    "fx", "USD", "fx_24_5",
               meta={"quote_convention": "inverted", "base": "USD", "quote": "CAD",
                     "normalised_ticker": "USDCAD"}),

    # VIX (CBOE — via macro_store, not OHLCV loader)
    Instrument(Symbol("cboe",  "VIX"),   "volatility", "USD", "nyse"),
]

_INSTRUMENT_REGISTRY: dict[Symbol, Instrument] = {i.symbol: i for i in _DEFAULT_INSTRUMENTS}


def get_instrument(symbol: Symbol) -> Instrument | None:
    """Look up default instrument metadata. Returns None if not registered."""
    return _INSTRUMENT_REGISTRY.get(symbol)
