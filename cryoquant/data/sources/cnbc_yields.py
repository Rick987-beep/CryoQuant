"""CNBC chart API — sovereign 10Y yields (FR / DE).

Unofficial public endpoint used by the france_sovereign_stress study (v5/v6)::

    https://ts-api.cnbc.com/harmony/app/charts/{rng}.json?symbol={sym}

Live quotes come from the CNBC quote web service::

    https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol

Public interface::

    fetch_yield(symbol, rng) -> pd.Series
    fetch_oat_bund(rng) -> pd.DataFrame   # oat10, bund10, spread_bp
    fetch_oat_bund_quote() -> dict        # live oat10, bund10, times, previous closes
    ingest_oat_bund(rng, *, force) -> pd.DataFrame

Daily chart bars can include a stale weekend bar; callers that need business
days should drop Saturday/Sunday rows.
"""
from __future__ import annotations

import logging
from typing import Literal

import pandas as pd
import requests

log = logging.getLogger(__name__)

_CHART_URL = "https://ts-api.cnbc.com/harmony/app/charts/{rng}.json?symbol={sym}"
_QUOTE_URL = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_TIMEOUT = 30

# Friendly ids → CNBC chart symbols
_SYMBOLS: dict[str, str] = {
    "OAT10": "FR10Y-FR",
    "BUND10": "DE10Y-DE",
    "oat10": "FR10Y-FR",
    "bund10": "DE10Y-DE",
}

ChartRange = Literal["1Y", "5Y", "10Y"]


def list_symbols() -> dict[str, str]:
    """Return alias → CNBC symbol mapping (uppercase keys only)."""
    return {"OAT10": _SYMBOLS["OAT10"], "BUND10": _SYMBOLS["BUND10"]}


def fetch_yield(
    series_id: str,
    rng: ChartRange = "1Y",
    *,
    session: requests.Session | None = None,
) -> pd.Series:
    """Fetch one CNBC yield series as UTC-indexed closes (%)."""
    cnbc_sym = _SYMBOLS.get(series_id, series_id)
    sess = session or requests.Session()
    url = _CHART_URL.format(rng=rng, sym=cnbc_sym)
    r = sess.get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT)
    r.raise_for_status()
    payload = r.json()
    bars = payload.get("barData", {}).get("priceBars") or []
    if not bars:
        raise RuntimeError(f"CNBC chart empty for {cnbc_sym!r} rng={rng!r}")

    idx = pd.to_datetime([b["tradeTime"][:8] for b in bars], format="%Y%m%d", utc=True)
    s = pd.Series([float(b["close"]) for b in bars], index=idx, name=series_id.upper()).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s.astype(float)


def fetch_oat_bund(
    rng: ChartRange = "1Y",
    *,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch FR10Y and DE10Y and compute spread in basis points."""
    sess = session or requests.Session()
    oat = fetch_yield("OAT10", rng, session=sess)
    bund = fetch_yield("BUND10", rng, session=sess)
    df = pd.DataFrame({"oat10": oat, "bund10": bund}).dropna()
    df["spread_bp"] = (df["oat10"] - df["bund10"]) * 100.0
    return df


def _pct(text: str) -> float:
    return float(str(text).replace("%", "").replace("+", "").strip())


def fetch_oat_bund_quote(*, session: requests.Session | None = None) -> dict:
    """Live FR10Y / DE10Y quotes (%) with quote times and previous closes."""
    sess = session or requests.Session()
    syms = {"oat10": _SYMBOLS["OAT10"], "bund10": _SYMBOLS["BUND10"]}
    params = {
        "symbols": "|".join(syms.values()),
        "requestMethod": "itv",
        "noform": "1",
        "partnerId": "2",
        "fund": "1",
        "exthrs": "1",
        "output": "json",
        "events": "1",
    }
    r = sess.get(_QUOTE_URL, params=params, headers={"User-Agent": _UA}, timeout=_TIMEOUT)
    r.raise_for_status()
    quotes = r.json()["FormattedQuoteResult"]["FormattedQuote"]
    by_sym = {q["symbol"]: q for q in quotes}
    out: dict = {"source": "CNBC FR10Y-FR / DE10Y-DE"}
    for key, sym in syms.items():
        q = by_sym.get(sym)
        if q is None:
            raise RuntimeError(f"CNBC quote missing {sym!r}")
        last = _pct(q["last"])
        out[key] = last
        out[f"{key}_time"] = q.get("last_time")
        out[f"{key}_prev_close"] = last - _pct(q.get("change", "0"))
    out["time"] = out["oat10_time"]
    out["spread_bp"] = (out["oat10"] - out["bund10"]) * 100.0
    return out


def ingest_oat_bund(
    rng: ChartRange = "1Y",
    *,
    force: bool = False,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch OAT/Bund yields and persist scalar series to ``macro_store``."""
    from cryoquant.data import macro_store

    df = fetch_oat_bund(rng, session=session)
    macro_store.write_series("cnbc", "OAT10", df["oat10"].rename("OAT10"), force=force)
    macro_store.write_series("cnbc", "BUND10", df["bund10"].rename("BUND10"), force=force)
    macro_store.write_series("cnbc", "SPREAD_BP", df["spread_bp"].rename("SPREAD_BP"), force=force)
    log.info(
        "cnbc oat/bund %s → %s (%d rows); last spread %.2f bp",
        df.index[0].date(),
        df.index[-1].date(),
        len(df),
        float(df["spread_bp"].iloc[-1]),
    )
    return df
