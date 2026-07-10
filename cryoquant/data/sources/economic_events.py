"""Unified US scheduled economic + earnings event calendar."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from cryoquant.data.sources import fomc_calendar
from cryoquant.data.sources.event_schema import (
    DEFAULT_MAG7,
    EVENT_TIERS,
    MACRO_STORE_KEYS,
    empty_event_frame,
    records_to_event_frame,
    release_slot_nyc,
)

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

# Re-export for callers
__all__ = [
    "DEFAULT_MAG7",
    "EVENT_TIERS",
    "MACRO_STORE_KEYS",
    "empty_event_frame",
    "fetch_scheduled_events",
    "ingest_scheduled_events",
    "load_scheduled_events",
    "release_slot_nyc",
]


def _fomc_events_frame(start: date, end: date) -> pd.DataFrame:
    sparse = fomc_calendar.fetch_fomc_decision_days(start, end)
    if sparse.empty:
        return empty_event_frame()

    records: list[dict[str, Any]] = []
    for _ts, row in sparse.iterrows():
        decision_d = row["decision_date"]
        if isinstance(decision_d, str):
            decision_d = date.fromisoformat(decision_d)
        avail = pd.Timestamp(row["available_utc"])
        if avail.tzinfo is None:
            avail = avail.tz_localize("UTC")
        else:
            avail = avail.tz_convert("UTC")
        records.append(
            {
                "event_id": f"fomc-{decision_d.isoformat()}",
                "source": "fed_calendar",
                "event_type": "fomc",
                "tier": EVENT_TIERS["fomc"],
                "title": "FOMC rate decision",
                "symbol": "",
                "event_date": decision_d.isoformat(),
                "event_time_et": avail.astimezone(_ET).strftime("%H:%M"),
                "event_utc": avail.to_pydatetime(),
            }
        )
    return records_to_event_frame(records)


def fetch_scheduled_events(
    start: date,
    end: date | None = None,
    *,
    earnings_tickers: Sequence[str] | None = None,
    session: Any | None = None,
) -> pd.DataFrame:
    """Fetch and merge FOMC, BLS macro, and earnings into one event frame."""
    from cryoquant.data.sources.bls_calendar import fetch_macro_releases
    from cryoquant.data.sources.earnings_calendar import fetch_earnings_events

    tickers = earnings_tickers if earnings_tickers is not None else DEFAULT_MAG7
    end_d = end or date.today()
    parts = [
        _fomc_events_frame(start, end_d),
        fetch_macro_releases(start, end_d, session=session),
        fetch_earnings_events(start, end_d, tickers=tickers, session=session),
    ]
    frames = [p for p in parts if not p.empty]
    if not frames:
        return empty_event_frame()

    out = pd.concat(frames)
    out = out[~out.index.duplicated(keep="first")]
    if "event_id" in out.columns:
        out = out.drop_duplicates(subset=["event_id"], keep="first")
    return out.sort_index()


def ingest_scheduled_events(
    start: date,
    end: date | None = None,
    *,
    earnings_tickers: Sequence[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
    session: Any | None = None,
) -> dict[str, int]:
    """Fetch component feeds and persist to ``macro_store``."""
    from cryoquant.data import macro_store
    from cryoquant.data.sources.bls_calendar import fetch_macro_releases
    from cryoquant.data.sources.earnings_calendar import fetch_earnings_events

    tickers = earnings_tickers if earnings_tickers is not None else DEFAULT_MAG7
    end_d = end or date.today()

    if dry_run:
        merged = fetch_scheduled_events(
            start, end_d, earnings_tickers=tickers, session=session
        )
        return {"dry_run": len(merged)}

    fomc_sparse = fomc_calendar.fetch_fomc_decision_days(start, end_d, session=session)
    macro_store.write_frame(
        "fed_calendar",
        MACRO_STORE_KEYS["fed_calendar"],
        fomc_sparse,
        force=force,
    )

    bls = fetch_macro_releases(start, end_d, session=session)
    macro_store.write_frame(
        "bls_calendar",
        MACRO_STORE_KEYS["bls_calendar"],
        bls,
        force=force,
    )

    earn = fetch_earnings_events(start, end_d, tickers=tickers, session=session)
    macro_store.write_frame(
        "yahoo_calendar",
        MACRO_STORE_KEYS["yahoo_calendar"],
        earn,
        force=force,
    )

    merged = fetch_scheduled_events(
        start, end_d, earnings_tickers=tickers, session=session
    )
    macro_store.write_frame(
        "economic_events",
        MACRO_STORE_KEYS["economic_events"],
        merged,
        force=force,
    )
    return {
        "fed_calendar": len(fomc_sparse),
        "bls_calendar": len(bls),
        "yahoo_calendar": len(earn),
        "economic_events": len(merged),
    }


def load_scheduled_events(
    start: datetime,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Load merged scheduled events from ``macro_store``."""
    from cryoquant.data import macro_store

    return macro_store.load_frame(
        "economic_events",
        MACRO_STORE_KEYS["economic_events"],
        start,
        end,
    )
