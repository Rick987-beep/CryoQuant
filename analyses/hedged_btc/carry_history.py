"""1c — Funding rate history (Deribit primary; Binance reference only).

Product trades on Deribit — carry/funding income is assessed on Deribit perp first.
Post ~Mar 2026 Deribit changed perpetual mechanics; funding collapsed — do not rely on
carry as a core book pillar.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from cryocore.instruments import Symbol
from cryoquant.data.sources.binance_perp import fetch_funding

log = logging.getLogger(__name__)

FUNDING_TRIGGER_APR = 0.05
FUNDING_TRIGGER_PER_8H = FUNDING_TRIGGER_APR / (365 * 3)
DERIBIT_REGIME_CUTOFF = pd.Timestamp("2026-03-01", tz="UTC")


def fetch_deribit_funding_history(
    start: datetime,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Paginated Deribit BTC-PERPETUAL funding (hourly observations, interest_8h field)."""
    end = end or datetime.now(timezone.utc)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    url_base = (
        "https://www.deribit.com/api/v2/public/get_funding_rate_history"
        "?instrument_name=BTC-PERPETUAL"
    )

    rows: list[dict] = []
    cursor = end_ms
    while cursor > start_ms:
        url = f"{url_base}&start_timestamp={start_ms}&end_timestamp={cursor}"
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                chunk = json.load(resp).get("result", [])
        except Exception as exc:
            log.warning("Deribit funding page failed at cursor %s: %s", cursor, exc)
            break
        if not chunk:
            break
        rows.extend(chunk)
        first_ts = min(int(r["timestamp"]) for r in chunk)
        if first_ts <= start_ms or len(chunk) < 100:
            break
        cursor = first_ts - 1

    if not rows:
        return pd.DataFrame(columns=["timestamp", "funding_rate", "apr_pct"])

    df = pd.DataFrame(rows).drop_duplicates(subset=["timestamp"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df["funding_rate"] = df["interest_8h"].astype(float)
    df["apr_pct"] = df["funding_rate"] * 3 * 365 * 100
    return df[["timestamp", "funding_rate", "apr_pct"]].sort_values("timestamp")


def binance_funding_history(start: datetime, end: datetime | None = None) -> pd.DataFrame:
    sym = Symbol("binance.perp", "BTCUSDT")
    end = end or datetime.now(timezone.utc)
    df = fetch_funding(sym, start, end)
    df = df.reset_index().rename(columns={"timestamp": "ts"})
    df["apr_pct"] = df["funding_rate"] * 3 * 365 * 100
    df["source"] = "binance"
    return df


def _summarise_window(df: pd.DataFrame, *, ts_col: str = "timestamp", rate_col: str = "funding_rate") -> dict:
    if df.empty:
        return {"n_obs": 0}
    rates = df[rate_col].dropna()
    apr = df["apr_pct"] if "apr_pct" in df.columns else rates * 3 * 365 * 100
    return {
        "n_obs": len(rates),
        "apr_mean_pct": float(apr.mean()),
        "apr_median_pct": float(apr.median()),
        "pct_above_5pct_apr": float((rates > FUNDING_TRIGGER_PER_8H).mean() * 100),
        "pct_positive": float((rates > 0).mean() * 100),
        "max_apr_pct": float(apr.max()),
    }


def summarise_funding_regimes(df: pd.DataFrame, *, ts_col: str = "timestamp") -> dict:
    """Full sample plus pre/post Mar-2026 split (Deribit regime change)."""
    if df.empty:
        return {"n_obs": 0}

    full = _summarise_window(df, ts_col=ts_col)
    full["window"] = "all"

    ts = pd.to_datetime(df[ts_col], utc=True)
    pre = df[ts < DERIBIT_REGIME_CUTOFF]
    post = df[ts >= DERIBIT_REGIME_CUTOFF]

    return {
        "all": full,
        "pre_2026_03": _summarise_window(pre, ts_col=ts_col) | {"window": "pre_2026_03"},
        "post_2026_03": _summarise_window(post, ts_col=ts_col) | {"window": "post_2026_03"},
        "span_start": str(ts.min().date()),
        "span_end": str(ts.max().date()),
        "trigger_apr_pct": FUNDING_TRIGGER_APR * 100,
        "verdict": _carry_verdict(post),
    }


def _carry_verdict(post_regime: pd.DataFrame) -> str:
    if post_regime.empty:
        return "insufficient_data"
    s = _summarise_window(post_regime)
    if s.get("apr_median_pct", 99) < 1.0 and s.get("pct_above_5pct_apr", 100) < 25:
        return "not_viable_core_income_post_mar2026"
    return "marginal"


def run(out_dir: Path, start: datetime) -> tuple[dict, dict]:
    end = datetime.now(timezone.utc)

    deribit_df = fetch_deribit_funding_history(start, end)
    deribit_path = out_dir / "funding_deribit.csv"
    deribit_df.to_csv(deribit_path, index=False)
    deribit_summary = summarise_funding_regimes(deribit_df, ts_col="timestamp")
    deribit_summary["source"] = "deribit"
    deribit_summary["primary_venue"] = True
    log.info("Wrote %s (%d rows)", deribit_path, len(deribit_df))

    binance_df = binance_funding_history(start, end)
    binance_path = out_dir / "funding_binance.csv"
    binance_df.to_csv(binance_path, index=False)
    binance_summary = summarise_funding_regimes(binance_df, ts_col="ts")
    binance_summary["source"] = "binance"
    binance_summary["primary_venue"] = False
    binance_summary["note"] = "reference_only_product_trades_on_deribit"
    log.info("Wrote %s (%d rows)", binance_path, len(binance_df))

    combined = {
        "deribit": deribit_summary,
        "binance": binance_summary,
        "recommendation": (
            "Do not model L3/carry as a core income pillar. Deribit funding collapsed "
            "after ~Mar 2026 (median ~0.01% APR). Optional opportunistic overlay at most."
        ),
    }
    return combined, {"binance_df": binance_df, "deribit_df": deribit_df}
