"""Trading calendars for CryoQuant.

Each calendar implements `is_open(ts) -> bool` and `session_label(ts) -> str | None`.

Available calendars (registry key → class):
    "crypto_24_7"   — always open
    "nyse"          — NYSE/XNYS; requires pandas_market_calendars
    "cme_futures"   — stub (treated as NYSE-aligned for now)
    "fx_eur"        — stub (weekdays only)

Use `get_calendar(name)` to retrieve a calendar by key.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Protocol, runtime_checkable

import pandas as pd


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Calendar(Protocol):
    name: str

    def is_open(self, ts: pd.Timestamp | datetime) -> bool: ...
    def session_label(self, ts: pd.Timestamp | datetime) -> str | None: ...


# ---------------------------------------------------------------------------
# Crypto 24/7
# ---------------------------------------------------------------------------

class Crypto24_7:
    name = "crypto_24_7"

    def is_open(self, ts: pd.Timestamp | datetime) -> bool:  # noqa: ARG002
        return True

    def session_label(self, ts: pd.Timestamp | datetime) -> str | None:  # noqa: ARG002
        return "crypto"


# ---------------------------------------------------------------------------
# NYSE (requires pandas_market_calendars)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=8)
def _nyse_trading_days(year_start: int, year_end: int) -> pd.DatetimeIndex:
    import pandas_market_calendars as mcal
    cal = mcal.get_calendar("XNYS")
    schedule = cal.schedule(
        start_date=f"{year_start}-01-01",
        end_date=f"{year_end}-12-31",
    )
    return pd.DatetimeIndex(schedule.index.normalize())


class NYSE:
    name = "nyse"

    def is_open(self, ts: pd.Timestamp | datetime) -> bool:
        t = pd.Timestamp(ts).tz_convert("UTC") if hasattr(ts, "tzinfo") and ts.tzinfo else pd.Timestamp(ts, tz="UTC")
        trading = _nyse_trading_days(t.year, t.year)
        bar_date = t.normalize().tz_localize(None)
        return bool(bar_date in trading)

    def session_label(self, ts: pd.Timestamp | datetime) -> str | None:
        t = pd.Timestamp(ts).tz_convert("UTC") if hasattr(ts, "tzinfo") and ts.tzinfo else pd.Timestamp(ts, tz="UTC")
        if not self.is_open(t):
            return None
        hour = t.hour
        if 13 <= hour < 21:   # approx NYSE 09:30–16:00 ET in UTC (summer)
            return "us_regular"
        return "us_extended"


# ---------------------------------------------------------------------------
# CME futures — stub (weekdays, rough)
# ---------------------------------------------------------------------------

class CMEFutures:
    name = "cme_futures"

    def is_open(self, ts: pd.Timestamp | datetime) -> bool:
        t = pd.Timestamp(ts)
        return t.weekday() < 5  # Monday–Friday only; not accounting for holidays

    def session_label(self, ts: pd.Timestamp | datetime) -> str | None:
        return "cme" if self.is_open(ts) else None


# ---------------------------------------------------------------------------
# FX EUR — stub (weekdays only)
# ---------------------------------------------------------------------------

class FxEur:
    name = "fx_eur"

    def is_open(self, ts: pd.Timestamp | datetime) -> bool:
        t = pd.Timestamp(ts)
        return t.weekday() < 5

    def session_label(self, ts: pd.Timestamp | datetime) -> str | None:
        return "fx_eur" if self.is_open(ts) else None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Calendar] = {
    "crypto_24_7": Crypto24_7(),
    "nyse":        NYSE(),
    "cme_futures": CMEFutures(),
    "fx_eur":      FxEur(),
}


def get_calendar(name: str) -> Calendar:
    """Return a Calendar instance by registry key."""
    if name not in _REGISTRY:
        raise KeyError(f"unknown calendar {name!r}; available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


CALENDARS = _REGISTRY
