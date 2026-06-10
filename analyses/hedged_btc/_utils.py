"""Shared helpers for hedged_btc market-structure analysis."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

import pandas as pd

_DERIBIT_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

TENOR_BUCKETS = {
    "front": (5, 14, 10),
    "mid": (25, 50, 37),
    "back": (75, 120, 90),
}


def parse_deribit_expiry(label: str) -> date:
    """Parse Deribit expiry label, e.g. ``25SEP26`` → date."""
    m = re.match(r"^(\d{1,2})([A-Z]{3})(\d{2})$", str(label).upper())
    if not m:
        raise ValueError(f"Unrecognised Deribit expiry: {label!r}")
    day = int(m.group(1))
    month = _DERIBIT_MONTHS[m.group(2)]
    year = 2000 + int(m.group(3))
    return date(year, month, day)


def expiry_dte(expiry_label: str, as_of: date) -> int:
    return (parse_deribit_expiry(expiry_label) - as_of).days


def chain_daily_snapshot(chain: pd.DataFrame) -> pd.DataFrame:
    """Last 5-min chain snapshot of the UTC calendar day (24/7 market; not an equity close)."""
    if chain.empty:
        return chain
    ts = pd.to_datetime(chain["timestamp"], unit="us", utc=True)
    last = ts.max()
    return chain.loc[ts == last].copy()


# Back-compat alias
chain_eod_snapshot = chain_daily_snapshot


def nearest_strike(strikes: pd.Series, target: float) -> float:
    return float(strikes.iloc[(strikes - target).abs().argmin()])


def iv_at_strike(
    snap: pd.DataFrame,
    *,
    expiry: str,
    strike: float,
    is_call: bool,
) -> float | None:
    """Return mark_iv (percent) for the nearest strike/expiry/side, or None."""
    side = snap[(snap["expiry"] == expiry) & (snap["is_call"] == is_call)]
    if side.empty:
        return None
    idx = (side["strike"] - strike).abs().idxmin()
    iv = float(side.loc[idx, "mark_iv"])
    if iv <= 0 or iv > 200:
        return None
    return iv


def pick_expiry_for_bucket(expiries: list[str], as_of: date, bucket: str) -> str | None:
    """Choose expiry whose DTE is closest to bucket centre and inside DTE range."""
    lo, hi, target = TENOR_BUCKETS[bucket]
    best: tuple[int, str] | None = None
    for exp in expiries:
        dte = expiry_dte(exp, as_of)
        if lo <= dte <= hi:
            dist = abs(dte - target)
            if best is None or dist < best[0]:
                best = (dist, exp)
    return best[1] if best else None


def ensure_analysis_data_dir(root: "Path") -> "Path":
    from pathlib import Path
    d = Path(root) / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d
