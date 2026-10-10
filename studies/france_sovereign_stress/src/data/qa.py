"""Lightweight QA over loaded frames (gaps, duplicates, stale ends)."""

from __future__ import annotations

from typing import Any

import pandas as pd


def _index_issues(idx: pd.DatetimeIndex) -> dict[str, Any]:
    dup = int(idx.duplicated().sum())
    mono = bool(idx.is_monotonic_increasing)
    return {"n": len(idx), "duplicates": dup, "monotonic": mono}


def qa_series_frame(
    name: str,
    df: pd.DataFrame,
    *,
    required_cols: list[str] | None = None,
    max_gap_days: int | None = 5,
) -> dict[str, Any]:
    """Return a JSON-serialisable QA dict for one frame."""
    out: dict[str, Any] = {"name": name, "ok": True, "issues": []}
    if df.empty:
        out["ok"] = False
        out["issues"].append("empty")
        return out

    idx = pd.DatetimeIndex(df.index)
    meta = _index_issues(idx)
    out["rows"] = meta["n"]
    out["start"] = str(idx.min().date())
    out["end"] = str(idx.max().date())
    out["columns"] = list(df.columns)

    if meta["duplicates"]:
        out["ok"] = False
        out["issues"].append(f"duplicate_index={meta['duplicates']}")
    if not meta["monotonic"]:
        out["ok"] = False
        out["issues"].append("index_not_monotonic")

    if required_cols:
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            out["ok"] = False
            out["issues"].append(f"missing_cols={missing}")

    nulls = {c: int(df[c].isna().sum()) for c in df.columns if df[c].isna().any()}
    if nulls:
        out["nulls"] = nulls

    if max_gap_days is not None and len(idx) >= 2:
        gaps = idx.to_series().diff().dt.days.dropna()
        big = gaps[gaps > max_gap_days]
        if len(big):
            out["large_gaps"] = [
                {"after": str(idx[i - 1].date()), "days": int(gaps.iloc[i - 1])}
                for i in big.index
            ][:5]

    return out


def qa_report(
    yields_daily: pd.DataFrame,
    settles: pd.DataFrame,
    stocks_daily: pd.DataFrame,
    fred_monthly: pd.DataFrame,
) -> dict[str, Any]:
    """QA bundle for the four core v5 reference tables."""
    parts = [
        qa_series_frame(
            "yields_daily",
            yields_daily,
            required_cols=["oat10", "bund10", "spread_bp"],
            max_gap_days=5,
        ),
        qa_series_frame(
            "eurex_settles",
            settles,
            required_cols=["FOAT_front", "FGBL_front"],
            max_gap_days=5,
        ),
        qa_series_frame(
            "stocks_daily",
            stocks_daily,
            required_cols=["^FCHI"],
            max_gap_days=5,
        ),
        qa_series_frame(
            "fred_monthly",
            fred_monthly,
            required_cols=["IRLTLT01FRM156N", "IRLTLT01DEM156N", "IRLTLT01ITM156N"],
            max_gap_days=45,
        ),
    ]
    return {
        "ok": all(p["ok"] for p in parts),
        "tables": parts,
        "spot_checks": {
            "yields_last_spread_bp": float(yields_daily["spread_bp"].iloc[-1]),
            "yields_last_date": str(yields_daily.index[-1].date()),
            "settles_last_date": str(settles.index[-1].date()),
            "foat_front_last": float(settles["FOAT_front"].iloc[-1]),
            "fgbl_front_last": float(settles["FGBL_front"].iloc[-1]),
            "cac_last": float(stocks_daily["^FCHI"].iloc[-1]),
            "cac_last_date": str(stocks_daily.index[-1].date()),
        },
    }
