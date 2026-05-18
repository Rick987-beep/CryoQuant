"""Non-OHLCV data feeds (Phase 5+).

Each feed name maps to a callable `attach(df, *, symbol) -> df_with_columns`
that is closed-bar safe (no look-ahead). Feeds are pulled in by name from
`RunSpec.feeds`; the agent_api applies them in order before `classify()`.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from . import binance_perp

# Public registry of feed-name -> attach callable
FEED_ATTACH: dict[str, Callable[..., pd.DataFrame]] = {
    "binance.perp.funding": binance_perp.attach_funding,
}


def attach_feeds(df: pd.DataFrame, feeds: list[str], *, symbol: str) -> pd.DataFrame:
    """Apply the requested feeds in order. Unknown feed names raise KeyError."""
    out = df
    for name in feeds:
        if name not in FEED_ATTACH:
            raise KeyError(f"unknown feed {name!r}; known: {list(FEED_ATTACH)}")
        out = FEED_ATTACH[name](out, symbol=symbol)
    return out
