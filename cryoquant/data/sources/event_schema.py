"""Shared schema helpers for scheduled macro/earnings event calendars."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

_NYC = ZoneInfo("America/New_York")

DEFAULT_MAG7: tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "NVDA",
    "TSLA",
)

BLS_TITLE_TO_TYPE: dict[str, str] = {
    "Consumer Price Index": "cpi",
    "Employment Situation": "nfp",
    "Producer Price Index": "ppi",
    "Job Openings and Labor Turnover Survey": "jolts",
    "Employment Cost Index": "eci",
    "U.S. Import and Export Price Indexes": "import_export_prices",
}

EVENT_TIERS: dict[str, int] = {
    "fomc": 1,
    "cpi": 1,
    "nfp": 1,
    "ppi": 2,
    "jolts": 2,
    "eci": 2,
    "import_export_prices": 2,
    "earnings": 2,
    "bls_other": 3,
}

MACRO_STORE_KEYS: dict[str, str] = {
    "fed_calendar": "FOMC_DECISION_DAYS",
    "bls_calendar": "macro_releases",
    "yahoo_calendar": "mag7_earnings",
    "economic_events": "us_scheduled",
}


def bls_title_to_event_type(title: str) -> str:
    return BLS_TITLE_TO_TYPE.get(title, "bls_other")


def release_slot_nyc(event_utc: datetime) -> str:
    local = event_utc.astimezone(_NYC)
    hm = local.hour * 60 + local.minute
    if hm < 12 * 60:
        return "morning"
    if hm < 16 * 60:
        return "afternoon"
    return "evening"


def empty_event_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_id",
            "source",
            "event_type",
            "tier",
            "title",
            "symbol",
            "event_date",
            "event_time_et",
            "release_slot",
            "available_utc",
        ]
    )


def records_to_event_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return empty_event_frame()

    df = pd.DataFrame(records)
    df["event_utc"] = pd.to_datetime(df["event_utc"], utc=True)
    df["available_utc"] = df["event_utc"]
    df["release_slot"] = df["event_utc"].map(
        lambda ts: release_slot_nyc(ts.to_pydatetime())
    )
    df["tier"] = df["tier"].astype(float)
    df["symbol"] = df["symbol"].fillna("").astype(str)
    df = df.set_index("event_utc").sort_index()
    df.index.name = "timestamp"
    return df
