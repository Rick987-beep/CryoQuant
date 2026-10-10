"""Unified data loading — route OHLCV vs macro/scalar series by Symbol.

Callers use ``load_track`` instead of choosing between ``loader.load`` and
``macro_store.load_series`` manually.
"""
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

from cryocore.instruments import Symbol, get_instrument
from cryoquant.data import loader
from cryoquant.data import macro_store

log = logging.getLogger(__name__)

_MACRO_VENUES: frozenset[str] = frozenset({"fred", "manual", "cboe", "cnbc", "eurex"})

# CBOE ingest series_id aliases for load_track (see data.ingest.ingest_macro).
_CBOE_SERIES_ID: dict[str, str] = {
    "VIX": "VIX_CLOSE",
    "VX": "VX_FRONT_SETTLE",
    "VX_FRONT": "VX_FRONT_SETTLE",
    "VX_TRADE": "VX_TRADE_SETTLE",
}

# Venues whose macro tracks are multi-column frames (not scalar series).
_MACRO_FRAME_VENUES: frozenset[str] = frozenset({"eurex"})


def is_ohlcv_symbol(symbol: Symbol) -> bool:
    """True when ``load_track`` should use ``loader.load`` (OHLCV bars)."""
    if symbol.venue in _MACRO_VENUES:
        return False
    instr = get_instrument(symbol)
    if instr is None:
        return True
    if instr.asset_class == "macro":
        return False
    if instr.meta.get("storage") == "macro":
        return False
    return True


def macro_source_and_id(symbol: Symbol) -> tuple[str, str]:
    """Return ``(source, series_id)`` for macro_store lookup."""
    source = symbol.venue
    series_id = symbol.ticker
    if source == "cboe":
        series_id = _CBOE_SERIES_ID.get(series_id, series_id)
    return source, series_id


def load_track(
    symbol: Symbol,
    tf: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame | pd.Series:
    """Load one track — OHLCV DataFrame or macro Series.

    Args:
        symbol: Registered or ad-hoc ``Symbol``.
        tf:     Timeframe for OHLCV (ignored for macro series).
        start:  UTC start (inclusive).
        end:    UTC end (inclusive).

    Returns:
        ``pd.DataFrame`` (OHLCV) or ``pd.Series`` (macro scalar).
    """
    if is_ohlcv_symbol(symbol):
        return loader.load(symbol, tf, start, end)

    source, series_id = macro_source_and_id(symbol)
    if source in _MACRO_FRAME_VENUES:
        return macro_store.load_frame(source, series_id, start, end)
    return macro_store.load_series(source, series_id, start, end)


def load_tracks(
    specs: list[tuple[Symbol, str]],
    start: datetime,
    end: datetime,
) -> dict[str, pd.DataFrame | pd.Series]:
    """Batch-load tracks; keys are ``str(symbol)`` or ``str(symbol)+'@'+tf`` for OHLCV."""
    out: dict[str, pd.DataFrame | pd.Series] = {}
    for symbol, tf in specs:
        key = str(symbol) if not is_ohlcv_symbol(symbol) else f"{symbol}@{tf}"
        out[key] = load_track(symbol, tf, start, end)
    return out
