"""Build a fresh market-data snapshot under ``input/snapshots/<stamp>/``.

The snapshot has the same file layout as ``input/v5_reference/data`` so the
loaders in ``src.data.reference`` read either one. History is the frozen v5
file up to the day before the reference stamp, extended with fresh rows up to
``cutoff`` (the last full business day before the new stamp). Today's live
CNBC quote sets only the entry spread; today's partial session never enters a
calibration window.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.paths import reference_stamp, snapshots_dir, stamp_date, v5_reference_dir


def last_business_day_before(d: date) -> date:
    prev = d - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return prev


def new_stamp(now: datetime | None = None) -> str:
    """Stamp in Europe/Berlin wall time, e.g. ``2026-10-12T0935``."""
    from zoneinfo import ZoneInfo

    now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("Europe/Berlin"))
    return now.strftime("%Y-%m-%dT%H%M")


def _naive_days(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    idx = pd.DatetimeIndex(out.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    out.index = idx.normalize()
    out = out[out.index.dayofweek < 5]
    return out[~out.index.duplicated(keep="last")].sort_index()


@dataclass(frozen=True)
class MergeReport:
    frozen_rows: int
    fresh_rows_added: int
    first_added: str | None
    last_date: str
    overlap_rows: int
    overlap_max_abs_diff: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def merge_history(
    frozen: pd.DataFrame,
    fresh: pd.DataFrame,
    *,
    ref_date: date,
    cutoff: date,
    compare: list[str] | None = None,
) -> tuple[pd.DataFrame, MergeReport]:
    """Frozen rows before ``ref_date`` + fresh business-day rows in [ref_date, cutoff].

    Frozen rows dated on or after ``ref_date`` were partial sessions at the
    reference stamp and are replaced. Overlap diffs on ``compare`` columns are
    reported so revisions in the live source stay visible.
    """
    frozen = _naive_days(frozen)
    fresh = _naive_days(fresh)
    ref_ts, cut_ts = pd.Timestamp(ref_date), pd.Timestamp(cutoff)
    keep = frozen[frozen.index < ref_ts]
    add = fresh[(fresh.index >= ref_ts) & (fresh.index <= cut_ts)]
    add = add[add.index > (keep.index.max() if len(keep) else pd.Timestamp.min)]
    cols = [c for c in keep.columns if c in add.columns] or list(add.columns)
    merged = pd.concat([keep, add[cols]]).sort_index()

    overlap = keep.join(fresh, rsuffix="__fresh", how="inner")
    diffs: dict[str, float] = {}
    for c in compare or []:
        if c in keep.columns and f"{c}__fresh" in overlap.columns:
            d = (overlap[c] - overlap[f"{c}__fresh"]).abs().max()
            diffs[c] = None if pd.isna(d) else round(float(d), 6)
    report = MergeReport(
        frozen_rows=len(keep),
        fresh_rows_added=len(add),
        first_added=str(add.index[0].date()) if len(add) else None,
        last_date=str(merged.index[-1].date()),
        overlap_rows=len(overlap),
        overlap_max_abs_diff=diffs,
    )
    return merged, report


def _read_ref(name: str, **kw: Any) -> pd.DataFrame:
    return pd.read_csv(v5_reference_dir() / "data" / name, **kw)


# Default equities: v5 names plus French banks / bank-index proxies for v7.
BANK_TICKERS = ["BNP.PA", "GLE.PA", "ACA.PA", "EXV1.DE"]


def _fetch_stocks(tickers: list[str], start: date) -> pd.DataFrame:
    from cryocore.instruments import Symbol
    from cryoquant.data.sources.yahoo import fetch_bars

    t0 = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    cols = {}
    for t in tickers:
        try:
            df = fetch_bars(Symbol("yahoo", t), "1d", t0, datetime.now(timezone.utc))
        except Exception:  # noqa: BLE001 — a missing equity must not block the snapshot
            continue
        if not df.empty:
            cols[t] = df["close"]
    if "^FCHI" not in cols:
        raise RuntimeError("Yahoo returned no ^FCHI bars; the CAC sleeve needs them")
    return pd.DataFrame(cols)


def _fetch_long_bank_history(start: date = date(2010, 1, 1)) -> pd.DataFrame:
    """Long Yahoo history for bank ranking (2011–12 and 2024 episodes)."""
    return _fetch_stocks(["^FCHI", *BANK_TICKERS], start)


def build_snapshot(
    stamp: str | None = None,
    *,
    force: bool = False,
    with_options: bool = False,
    with_bank_options: bool = False,
    with_long_banks: bool = False,
) -> Path:
    """Fetch live inputs and write ``input/snapshots/<stamp>/data``. Returns that dir.

    ``with_options`` pulls live OOAT/OGBL chains via Playwright (v7).
    ``with_bank_options`` pulls BNP/GLE/ACA Eurex equity option chains.
    ``with_long_banks`` writes a separate long Yahoo bank history CSV.
    """
    from cryoquant.data.sources.cnbc_yields import fetch_oat_bund, fetch_oat_bund_quote
    from cryoquant.data.sources.eurex_futures import fetch_settles

    stamp = stamp or new_stamp()
    ref_stamp = reference_stamp()
    if stamp == ref_stamp:
        raise ValueError("snapshot stamp equals the reference stamp")
    out = snapshots_dir() / stamp / "data"
    if out.exists() and not force:
        raise FileExistsError(f"{out} exists; pass force=True to overwrite")
    out.mkdir(parents=True, exist_ok=True)

    ref_date = stamp_date(ref_stamp)
    cutoff = last_business_day_before(stamp_date(stamp))
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest: dict[str, Any] = {
        "stamp": stamp,
        "fetched_at_utc": fetched_at,
        "reference_stamp": ref_stamp,
        "history_cutoff": str(cutoff),
        "merge_rule": "frozen v5 rows before the reference date + fresh business-day rows "
        "up to the cutoff; today's partial session excluded",
        "files": {},
    }

    quote = fetch_oat_bund_quote()
    manifest["quote"] = quote

    frozen_y = _read_ref("yields_daily.csv", index_col=0, parse_dates=True)
    yields, rep = merge_history(
        frozen_y, fetch_oat_bund("1Y"), ref_date=ref_date, cutoff=cutoff,
        compare=["oat10", "bund10", "spread_bp"],
    )
    yields.to_csv(out / "yields_daily.csv")
    manifest["files"]["yields_daily.csv"] = {"source": "CNBC chart 1Y daily", **rep.to_dict()}

    frozen_s = _read_ref("eurex_settles.csv", parse_dates=["date"]).set_index("date")
    fresh_s = fetch_settles()
    settles, rep = merge_history(
        frozen_s, fresh_s, ref_date=ref_date, cutoff=cutoff,
        compare=["FOAT_front", "FOAT_next", "FGBL_front", "FGBL_next"],
    )
    for col in ("FOAT_front_month", "FGBL_front_month"):
        settles[col] = settles[col].astype("int64")
    settles.index.name = "date"
    settles.to_csv(out / "eurex_settles.csv")
    manifest["files"]["eurex_settles.csv"] = {"source": "Eurex overallstatistics", **rep.to_dict()}

    frozen_st = _read_ref("stocks_daily.csv", parse_dates=["Date"]).set_index("Date")
    want = list(dict.fromkeys([*frozen_st.columns, *BANK_TICKERS]))
    fresh_st = _fetch_stocks(want, ref_date - timedelta(days=14))
    # Keep frozen columns; append any new bank columns from fresh only.
    stocks, rep = merge_history(
        frozen_st, fresh_st[[c for c in fresh_st.columns if c in frozen_st.columns]],
        ref_date=ref_date, cutoff=cutoff, compare=["^FCHI"],
    )
    for t in BANK_TICKERS:
        if t in fresh_st.columns:
            # merge bank column onto the shared index (NaN before availability)
            stocks[t] = fresh_st[t].reindex(stocks.index)
    stocks.index.name = "Date"
    stocks.to_csv(out / "stocks_daily.csv")
    manifest["files"]["stocks_daily.csv"] = {
        "source": "Yahoo 1d close",
        "bank_tickers": [t for t in BANK_TICKERS if t in stocks.columns],
        **rep.to_dict(),
    }

    if with_long_banks:
        long_banks = _fetch_long_bank_history()
        long_banks.index.name = "Date"
        long_banks.to_csv(out / "banks_daily_long.csv")
        manifest["files"]["banks_daily_long.csv"] = {
            "source": "Yahoo 1d close from 2010",
            "columns": list(long_banks.columns),
            "rows": len(long_banks),
            "first": str(long_banks.index[0].date()) if len(long_banks) else None,
            "last": str(long_banks.index[-1].date()) if len(long_banks) else None,
        }

    for name in ("yields_weekly.csv", "fred_10y_monthly.csv", "eurex_settles_recent.csv"):
        shutil.copy2(v5_reference_dir() / "data" / name, out / name)
        manifest["files"][name] = {"source": "copied from v5 reference (not used by the simulation)"}

    bond_chains: dict[str, Any] = {}
    bank_chains: dict[str, Any] = {}
    chain_note = "Option chains not pulled."
    if with_options:
        from src.data.options_chain import (
            chain_summary,
            fetch_bond_option_chains,
            fetch_equity_option_chains,
        )

        bond_chains = fetch_bond_option_chains()
        chain_note = "OOAT/OGBL chains pulled via Playwright from Eurex product pages."
        manifest["files"]["bond_option_chains"] = {
            "source": "Eurex Playwright scrape",
            "summary": chain_summary(bond_chains),
        }
        if with_bank_options:
            bank_chains = fetch_equity_option_chains()
            manifest["files"]["bank_option_chains"] = {
                "source": "Eurex Playwright scrape (equity options)",
                "summary": chain_summary(bank_chains),
            }

    last = settles.iloc[-1]
    snap = {
        "fetched_at": quote.get("time") or fetched_at,
        "yields": {
            "oat10": quote["oat10"],
            "bund10": quote["bund10"],
            "time": quote.get("time"),
            "source": quote["source"],
        },
        "futures": {
            code: {
                "settle_date": settles.index[-1].strftime("%Y%m%d"),
                "source": "Eurex overallstatistics",
                "front_month": int(last[f"{code}_front_month"]),
                "front_settle": float(last[f"{code}_front"]),
                "next_settle": float(last[f"{code}_next"]),
            }
            for code in ("FOAT", "FGBL")
        },
        "chains": bond_chains,
        "bank_chains": bank_chains,
        "note": chain_note,
    }
    (out / f"eurex_{stamp}.json").write_text(json.dumps(snap, indent=2))
    (out.parent / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    return out
