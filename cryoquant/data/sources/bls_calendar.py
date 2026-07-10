"""BLS macro release calendar — ICS feed (CPI, NFP, PPI, …).

Public interface::

    fetch_macro_releases(start, end, *, session) -> pd.DataFrame

Persist via ``macro_store.write_frame("bls_calendar", "macro_releases", df)``.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from cryoquant.data.sources.event_schema import (
    EVENT_TIERS,
    bls_title_to_event_type,
    records_to_event_frame,
)

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
_BLS_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _parse_ics_dt(value: str) -> datetime:
    naive = datetime.strptime(value, "%Y%m%dT%H%M%S")
    return naive.replace(tzinfo=_ET).astimezone(timezone.utc)


def fetch_macro_releases(
    start: date,
    end: date | None = None,
    *,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Return BLS scheduled macro releases between *start* and *end*."""
    end_d = end or date.today()
    sess = session or requests.Session()
    r = sess.get(
        _BLS_ICS_URL,
        headers={"User-Agent": _BLS_USER_AGENT},
        timeout=60,
    )
    r.raise_for_status()

    records: list[dict[str, Any]] = []
    for block in r.text.split("BEGIN:VEVENT")[1:]:
        summary_m = re.search(r"^SUMMARY:(.+)$", block, re.MULTILINE)
        dt_m = re.search(
            r"^DTSTART;TZID=US-Eastern:(\d{8}T\d{6})$",
            block,
            re.MULTILINE,
        )
        uid_m = re.search(r"^UID:(.+)$", block, re.MULTILINE)
        if not summary_m or not dt_m:
            continue

        title = summary_m.group(1).strip().replace("\\,", ",")
        event_utc = _parse_ics_dt(dt_m.group(1))
        event_d = event_utc.astimezone(_ET).date()
        if event_d < start or event_d > end_d:
            continue

        event_type = bls_title_to_event_type(title)
        records.append(
            {
                "event_id": uid_m.group(1).strip() if uid_m else f"bls-{event_d}-{title}",
                "source": "bls_calendar",
                "event_type": event_type,
                "tier": EVENT_TIERS.get(event_type, 3),
                "title": title,
                "symbol": "",
                "event_date": event_d.isoformat(),
                "event_time_et": event_utc.astimezone(_ET).strftime("%H:%M"),
                "event_utc": event_utc,
            }
        )

    return records_to_event_frame(records)
