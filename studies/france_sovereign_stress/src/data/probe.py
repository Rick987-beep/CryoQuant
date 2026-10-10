"""Live probes against CNBC, Eurex, FRED, and Yahoo (best-effort)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd


def probe_cnbc(rng: str = "1Y") -> dict[str, Any]:
    from cryoquant.data.sources.cnbc_yields import fetch_oat_bund

    df = fetch_oat_bund(rng)  # type: ignore[arg-type]
    last = df.iloc[-1]
    return {
        "ok": True,
        "rows": len(df),
        "start": str(df.index[0].date()),
        "end": str(df.index[-1].date()),
        "last": {
            "oat10": float(last["oat10"]),
            "bund10": float(last["bund10"]),
            "spread_bp": float(last["spread_bp"]),
        },
        "tail": _tail_records(df[["oat10", "bund10", "spread_bp"]], 5),
    }


def probe_eurex() -> dict[str, Any]:
    from cryoquant.data.sources.eurex_futures import fetch_settles

    df = fetch_settles()
    last = df.iloc[-1]
    cols = ["FOAT_front", "FOAT_next", "FGBL_front", "FGBL_next"]
    return {
        "ok": True,
        "rows": len(df),
        "start": str(df.index[0].date()),
        "end": str(df.index[-1].date()),
        "last": {c: float(last[c]) for c in cols},
        "tail": _tail_records(df[cols], 5),
    }


def probe_fred() -> dict[str, Any]:
    from cryoquant.data.sources.fred import fetch_series

    start = datetime(2007, 1, 1, tzinfo=timezone.utc)
    end = datetime.now(timezone.utc)
    out: dict[str, Any] = {"ok": True, "series": {}}
    for alias in ("FR10Y_LT", "DE10Y_LT", "IT10Y_LT"):
        s = fetch_series(alias, start, end).dropna()
        out["series"][alias] = {
            "rows": len(s),
            "start": str(s.index[0].date()),
            "end": str(s.index[-1].date()),
            "last": float(s.iloc[-1]),
        }
    return out


def probe_yahoo_cac() -> dict[str, Any]:
    from cryocore.instruments import Symbol
    from cryoquant.data.sources.yahoo import fetch_bars

    end = datetime.now(timezone.utc)
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    df = fetch_bars(Symbol("yahoo", "^FCHI"), "1d", start, end)
    if df.empty:
        return {"ok": False, "error": "empty yahoo ^FCHI"}
    return {
        "ok": True,
        "rows": len(df),
        "start": str(df.index[0].date()),
        "end": str(df.index[-1].date()),
        "last_close": float(df["close"].iloc[-1]),
        "tail": _tail_records(df[["close"]], 5),
    }


def run_live_probes() -> dict[str, Any]:
    """Probe each live source; failures are recorded, not raised."""
    probes = {
        "cnbc_yields": probe_cnbc,
        "eurex_settles": probe_eurex,
        "fred_lt_yields": probe_fred,
        "yahoo_cac": probe_yahoo_cac,
    }
    results: dict[str, Any] = {}
    for name, fn in probes.items():
        try:
            results[name] = fn()
        except Exception as exc:  # noqa: BLE001 — probe must not abort the run
            results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    results["all_ok"] = all(v.get("ok") for v in results.values() if isinstance(v, dict))
    return results


def _tail_records(df: pd.DataFrame, n: int) -> list[dict[str, Any]]:
    tail = df.tail(n).copy()
    out: list[dict[str, Any]] = []
    for ts, row in tail.iterrows():
        rec: dict[str, Any] = {"date": str(pd.Timestamp(ts).date())}
        for k, v in row.items():
            rec[str(k)] = None if pd.isna(v) else float(v)
        out.append(rec)
    return out
