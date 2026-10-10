"""FRED data source — fetches macro series (DXY, rates, etc.).

Uses fredapi if FRED_API_KEY is set; otherwise falls back to FRED's public
CSV download endpoint (no key required, but rate-limited).

Public interface::

    fetch_series(series_id, start, end) -> pd.Series   # daily, UTC-indexed
    list_aliases() -> dict[str, str]                    # alias → FRED series ID
"""
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
import requests

from cryoquant import config

log = logging.getLogger(__name__)

_FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_TIMEOUT = 90        # FRED public endpoint can be very slow
_MAX_RETRIES = 3

# Map our friendly names to FRED series IDs.
# When adding new series, choose the FRED ID that FRED publishes with the fewest revisions
# (e.g. prefer seasonally adjusted series with stable vintage definitions).
_ALIASES: dict[str, str] = {
    # FX / rates benchmarks
    "DXY":          "DTWEXBGS",   # Trade-weighted USD index (broad, goods & services)
    "VIX":          "VIXCLS",     # CBOE VIX (close; prefer cboe.fetch_vix for OHLC)

    # US interest rates
    "FEDFUNDS":        "DFF",         # Daily effective federal funds rate (DFF is daily; FEDFUNDS is monthly avg)
    "FEDFUNDS_UPPER":  "DFEDTARU",    # Fed funds target range upper bound (FOMC-announced rate)
    "FEDFUNDS_LOWER":  "DFEDTARL",    # Fed funds target range lower bound
    "US2Y":            "DGS2",        # 2-year Treasury constant maturity
    "US5Y":            "DGS5",        # 5-year Treasury constant maturity
    "US10Y":           "DGS10",       # 10-year Treasury constant maturity
    "US30Y":           "DGS30",       # 30-year Treasury constant maturity
    "TIPS10Y":         "DFII10",      # 10-year TIPS yield (real rate)
    "BREAKEVEN10Y":    "T10YIE",      # 10-year breakeven inflation rate
    "SOFR":            "SOFR",        # Secured overnight financing rate (from 2018)
    "YIELD_CURVE":     "T10Y2Y",      # 10Y-2Y Treasury spread (inversion = recession signal)
    "T10Y2Y":          "T10Y2Y",      # alias for direct FRED id
    "YIELD_CURVE_3M":  "T10Y3M",      # 10Y-3M spread (Fed's preferred recession indicator)

    # Inflation / macro
    "CPI":          "CPIAUCSL",   # CPI, all items, seasonally adjusted (monthly)
    "CPIYOY":       "CPIAUCSL",   # Same series; YoY calculation is downstream
    "PCE":          "PCEPI",      # PCE price index (monthly, SA)
    "PPI":          "PPIACO",     # Producer price index, all commodities
    "UMICH":        "UMCSENT",    # U of Michigan consumer sentiment (monthly)

    # Growth / activity
    "GDP":          "GDP",        # US GDP, quarterly SA annual rate
    "INDPRO":       "INDPRO",     # Industrial production index (monthly)
    "PAYROLLS":     "PAYEMS",     # Total nonfarm payrolls (monthly)
    "UNRATE":       "UNRATE",     # Unemployment rate (monthly)
    "RETAIL":       "RSAFS",      # Retail sales (monthly, SA)

    # Credit / financial conditions
    # NOTE: ICE BofA spread series (BAML*) are only available from FRED from June 2023 due to
    # a data-sharing agreement. Use NFCI / NFCICREDIT for 2010+ credit-stress history.
    "HY_SPREAD":    "BAMLH0A0HYM2",    # ICE BofA HY OAS — 2023+ only via FRED
    "IG_SPREAD":    "BAMLC0A0CM",      # ICE BofA IG OAS — 2023+ only via FRED
    "TED":          "TEDRATE",         # TED spread (3M LIBOR − T-bill); discontinued Jan 2022
    "NFCI":         "NFCI",            # Chicago Fed National Financial Conditions Index (weekly, 2010+)
    "NFCI_CREDIT":  "NFCICREDIT",      # NFCI credit sub-index (weekly, 2010+)
    "FIN_STRESS":   "STLFSI4",         # St. Louis Fed Financial Stress Index v4 (weekly, 2010+)

    # Euro sovereign long-term government bond yields (monthly, OECD via FRED)
    "FR10Y_LT":     "IRLTLT01FRM156N",  # France 10Y
    "DE10Y_LT":     "IRLTLT01DEM156N",  # Germany 10Y
    "IT10Y_LT":     "IRLTLT01ITM156N",  # Italy 10Y
}


def list_aliases() -> dict[str, str]:
    """Return a copy of the alias → FRED series ID mapping."""
    return dict(_ALIASES)


def fetch_series(
    series_id: str,
    start: datetime,
    end: datetime | None = None,
    *,
    session: requests.Session | None = None,
) -> pd.Series:
    """Fetch a FRED daily series.

    Args:
        series_id: FRED series ID or alias (e.g. "DXY", "DTWEXBGS").
        start:     First date (inclusive), tz-aware UTC.
        end:       Last date (inclusive). Defaults to today.

    Returns:
        pd.Series with tz-aware UTC DatetimeIndex, named series_id, float dtype.
        NaN entries (missing observations) are kept as-is.
    """
    fred_id = _ALIASES.get(series_id, series_id)
    end_dt = end or datetime.now(tz=start.tzinfo)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    # Try fredapi first
    if config.FRED_API_KEY:
        try:
            from fredapi import Fred  # type: ignore
            fred = Fred(api_key=config.FRED_API_KEY)
            raw = fred.get_series(fred_id, observation_start=start_str, observation_end=end_str)
            raw.index = pd.DatetimeIndex(raw.index, tz="UTC")
            raw.name = series_id
            return raw.astype(float)
        except Exception as exc:
            log.warning("fredapi fetch failed (%s); falling back to CSV: %s", fred_id, exc)

    # Public CSV fallback (with retry on timeout/server error)
    # Use observation_start/end — works for all series types including daily rates.
    # vintage_date is only reliable for select series and causes 400/empty responses
    # for higher-frequency series like FEDFUNDS and credit spreads.
    sess = session or requests.Session()
    params = {
        "id": fred_id,
        "observation_start": start_str,
        "observation_end":   end_str,
    }
    last_exc: Exception | None = None
    r: requests.Response | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = sess.get(_FRED_CSV_URL, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            r = resp
            break
        except (requests.exceptions.Timeout, requests.exceptions.HTTPError) as exc:
            last_exc = exc
            wait = min(30.0, 5 * (attempt + 1))
            log.warning("FRED CSV failed (attempt %d/%d) for %s: %s; retrying in %.0fs",
                        attempt + 1, _MAX_RETRIES, fred_id, exc, wait)
            import time
            time.sleep(wait)
    if r is None:
        raise RuntimeError(
            f"FRED CSV fetch failed after {_MAX_RETRIES} retries for {fred_id!r}: {last_exc}"
        )

    from io import StringIO
    raw_text = r.text

    # FRED CSV has header "DATE,<SERIES_ID>" but some series use different column names.
    # Read flexibly and rename whatever the second column is to "value".
    try:
        df = pd.read_csv(StringIO(raw_text))
    except Exception as exc:
        raise RuntimeError(f"FRED CSV parse error for {fred_id!r}: {exc}\nResponse: {raw_text[:500]}") from exc

    if df.empty or "DATE" not in df.columns:
        raise RuntimeError(
            f"FRED CSV for {fred_id!r} returned unexpected format. "
            f"Columns: {list(df.columns)}. First 200 chars: {raw_text[:200]!r}"
        )

    # Second column is the value; it may be named differently from fred_id
    value_col = df.columns[1]
    df = df.rename(columns={"DATE": "date", value_col: "value"})
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.set_index("date").sort_index()

    # Replace "." (FRED's missing-value marker) with NaN
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    series = df["value"].astype(float)
    series.index.name = "timestamp"
    series.name = series_id
    return series
