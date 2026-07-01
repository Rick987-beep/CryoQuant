"""Phase 1 data QA — coverage, edges, timezone, duplicates, period boundaries."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from cryocore.instruments import Symbol, get_instrument
from cryoquant import config
from cryoquant.data import macro_store
from cryoquant.data.cleaning import audit_bars

log = logging.getLogger(__name__)

Level = Literal["error", "warning", "info"]
FINDING_LEVELS = {"error": 3, "warning": 2, "info": 1}

LOAD_END = datetime.now(timezone.utc)


def _parse_start(s: str | None) -> datetime:
    if s:
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return datetime(2010, 1, 1, tzinfo=timezone.utc)


def _etf_tickers_from_universe() -> list[str]:
    """E2 per-ticker list from universe.yaml (falls back if missing)."""
    import yaml

    from src.paths import ANALYSIS_ROOT

    path = ANALYSIS_ROOT / "universe.yaml"
    if not path.exists():
        return []
    universe = yaml.safe_load(path.read_text())
    for item in universe.get("institutional") or []:
        if item.get("id") == "E2":
            return [str(t).upper() for t in item.get("tickers") or []]
    return []


@dataclass
class QAFinding:
    series_id: str
    level: Level
    code: str
    message: str


@dataclass
class SeriesQAResult:
    id: str
    section: str
    key: str
    status: str
    rows_loaded: int
    rows_manifest: int
    ts_min: str | None
    ts_max: str | None
    manifest_ts_min: str | None
    manifest_ts_max: str | None
    duplicate_timestamps: int
    tz_utc: bool
    daily_midnight: bool | None
    first_row: dict[str, Any] | None = None
    last_row: dict[str, Any] | None = None
    period_boundaries: list[dict[str, Any]] = field(default_factory=list)
    findings: list[QAFinding] = field(default_factory=list)

    def add(self, level: Level, code: str, message: str) -> None:
        self.findings.append(QAFinding(self.id, level, code, message))


@dataclass
class QAReport:
    run_at: str
    series_checked: int
    errors: int
    warnings: int
    series: list[SeriesQAResult] = field(default_factory=list)
    cross_checks: list[QAFinding] = field(default_factory=list)

    def worst_level(self) -> Level:
        if self.errors:
            return "error"
        if self.warnings:
            return "warning"
        return "info"


def _row_preview(obj: pd.Series | pd.DataFrame, *, head: bool) -> dict[str, Any]:
    if isinstance(obj, pd.DataFrame):
        row = obj.iloc[0 if head else -1]
        ts = obj.index[0 if head else -1]
        out = {"timestamp": str(ts)}
        for col in row.index:
            val = row[col]
            if isinstance(val, (pd.Timestamp, datetime)):
                out[str(col)] = str(val)
            elif pd.isna(val):
                out[str(col)] = None
            else:
                out[str(col)] = float(val) if isinstance(val, (int, float)) else str(val)
        return out
    ts = obj.index[0 if head else -1]
    val = obj.iloc[0 if head else -1]
    return {"timestamp": str(ts), "value": None if pd.isna(val) else float(val)}


def _check_index(idx: pd.DatetimeIndex, *, daily: bool, result: SeriesQAResult) -> None:
    if idx.tz is None:
        result.tz_utc = False
        result.add("error", "TZ_NAIVE", "Index is timezone-naive")
        return
    if str(idx.tz) != "UTC":
        result.tz_utc = False
        result.add("error", "TZ_NOT_UTC", f"Index timezone is {idx.tz}, expected UTC")
        return
    result.tz_utc = True

    if not daily:
        result.daily_midnight = None
        return

    non_midnight = idx[(idx.hour != 0) | (idx.minute != 0) | (idx.second != 0)]
    if len(non_midnight):
        result.daily_midnight = False
        result.add(
            "warning",
            "NOT_MIDNIGHT_UTC",
            f"{len(non_midnight)} daily bars not normalized to 00:00 UTC (sample: {non_midnight[0]})",
        )
    else:
        result.daily_midnight = True


def _partition_paths(source: str, series_id: str) -> list[Path]:
    root = config.STORE_ROOT / "macro" / source / series_id
    if not root.exists():
        return []
    return sorted(root.glob("year=*/month=*.parquet"))


def _ohlcv_partition_paths(sym: Symbol, tf: str) -> list[Path]:
    venue = sym.venue.replace(".", "_")
    safe_ticker = sym.ticker.replace("=", "_").replace("/", "_").replace("\\", "_")
    root = config.STORE_ROOT / venue / f"{venue}_{safe_ticker}" / tf
    if not root.exists():
        return []
    return sorted(root.glob("year=*/month=*.parquet"))


def _check_period_boundaries(
    idx: pd.DatetimeIndex,
    *,
    paths: list[Path],
    result: SeriesQAResult,
    calendar_id: str | None,
    section: str = "",
) -> None:
    """Verify month/year partition edges and flag large internal gaps."""
    if len(idx) < 2:
        return

    for path in paths:
        df = pd.read_parquet(path)
        pidx = pd.DatetimeIndex(df.index)
        if pidx.tz is None:
            pidx = pidx.tz_localize("UTC")
        else:
            pidx = pidx.tz_convert("UTC")
        year = int(path.parent.name.split("=")[1])
        month = int(path.name.replace("month=", "").replace(".parquet", ""))
        result.period_boundaries.append(
            {
                "partition": f"{year}-{month:02d}",
                "rows": len(pidx),
                "first": str(pidx.min().date()) if len(pidx) else None,
                "last": str(pidx.max().date()) if len(pidx) else None,
            }
        )
        if len(pidx) == 1 and section not in ("institutional", "macro_events"):
            result.add("warning", "PARTITION_SINGLE_ROW", f"Partition {year}-{month:02d} has only 1 row")
        elif len(pidx) == 1:
            result.add("info", "PARTITION_SINGLE_ROW", f"Partition {year}-{month:02d} has only 1 row (sparse/event series)")

    # Month-end / year-end presence (daily series only)
    if result.daily_midnight:
        dates = pd.Series(idx.date)
        for y in sorted(set(d.year for d in dates)):
            dec = dates[(dates.apply(lambda d: d.year) == y) & (dates.apply(lambda d: d.month) == 12)]
            if len(dec) and dec.max().day < 28:
                result.add("info", "DEC_INCOMPLETE", f"Year {y}: latest December row is {dec.max()}")

    # Gap check: flag gaps > 7 days for 24/7 crypto daily, > 10 for macro
    if section in ("institutional",):
        return  # sparse event series — gaps expected
    max_gap_days = 10 if calendar_id in (None, "nyse", "us_business") else 7
    if calendar_id == "crypto_24_7":
        max_gap_days = 3
    diffs = idx.to_series().diff().dropna()
    if len(diffs):
        big = diffs[diffs > pd.Timedelta(days=max_gap_days)]
        if len(big):
            sample = big.index[0]
            result.add(
                "warning",
                "LARGE_GAP",
                f"{len(big)} gap(s) > {max_gap_days}d (first after {sample.date()}, Δ={big.iloc[0].days}d)",
            )


def _load_entry(entry: dict[str, Any]) -> tuple[pd.Series | pd.DataFrame | None, bool, str | None]:
    """Return (data, is_daily, calendar_id). Read-only — no API fetches."""
    section = entry["section"]
    key = entry["key"]
    status = entry.get("status", "ok")
    if status != "ok":
        return None, True, None

    start = _parse_start(entry.get("ts_min"))
    end = LOAD_END

    try:
        if section == "ohlcv":
            venue_ticker, tf = key.rsplit("@", 1)
            sym = Symbol.parse(venue_ticker)
            from cryoquant.data.loader import _read_partitions

            df = _read_partitions(sym, tf, start, end)
            if df.empty:
                return None, tf == "1d", None
            cal = get_instrument(sym).calendar_id if get_instrument(sym) else "crypto_24_7"
            return df, tf == "1d", cal

        if section == "perp":
            if key.endswith("_funding"):
                s = macro_store.load_series("binance_perp", key, start, end)
            elif key.endswith("_open_interest"):
                s = macro_store.load_series("xoomar", key, start, end)
            else:
                return None, True, None
            return s, True, "crypto_24_7"

        if section == "macro":
            source, sid = key.split(":", 1)
            if source == "yahoo":
                from cryoquant.data.loader import _read_partitions

                sym = Symbol("yahoo", sid)
                df = _read_partitions(sym, "1d", start, end)
                return df if not df.empty else None, True, "nyse"
            if source == "fred":
                return macro_store.load_series("fred", sid, start, end), True, "nyse"
            if source == "cboe":
                return macro_store.load_series("cboe", sid, start, end), True, "nyse"

        if section == "macro_events":
            return macro_store.load_frame("fed_calendar", key, start, end), True, "nyse"

        if section == "crypto_alt":
            source, sid = key.split(":", 1)
            return macro_store.load_series(source, sid, start, end), True, "crypto_24_7"

        if section == "network":
            return macro_store.load_frame("coinmetrics", key, start, end), True, "crypto_24_7"

        if section == "options":
            if entry["id"] in ("C3", "C4", "C5"):
                return None, True, None
            underlying = key.split("_")[0]
            return macro_store.load_series("deribit", f"{underlying}_DVOL", start, end), True, "crypto_24_7"

        if section == "institutional":
            if key == "etf_flow_aggregate_us":
                return macro_store.load_frame("farside", key, start, end), True, "nyse"
            if key == "etf_flow_per_ticker":
                return None, True, "nyse"
            return macro_store.load_frame("strategy", key, start, end), False, "nyse"

    except Exception as exc:
        log.warning("Load failed %s %s: %s", entry["id"], key, exc)
        return None, True, None

    return None, True, None


def _macro_paths_for_entry(entry: dict[str, Any]) -> list[Path]:
    section = entry["section"]
    key = entry["key"]
    if section == "perp":
        src = "binance_perp" if "_funding" in key else "xoomar"
        return _partition_paths(src, key)
    if section == "macro":
        source, sid = key.split(":", 1)
        if source == "yahoo":
            return _ohlcv_partition_paths(Symbol("yahoo", sid), "1d")
        return _partition_paths(source, sid)
    if section == "macro_events":
        return _partition_paths("fed_calendar", key)
    if section == "crypto_alt":
        source, sid = key.split(":", 1)
        return _partition_paths(source, sid)
    if section == "network":
        return _partition_paths("coinmetrics", key)
    if section == "options" and entry["id"] in ("C1", "C2"):
        u = key.split("_")[0]
        return _partition_paths("deribit", f"{u}_DVOL")
    if section == "institutional":
        if key == "etf_flow_aggregate_us":
            return _partition_paths("farside", key)
        if key.startswith("mstr"):
            return _partition_paths("strategy", key)
    if section == "ohlcv":
        venue_ticker, tf = key.rsplit("@", 1)
        return _ohlcv_partition_paths(Symbol.parse(venue_ticker), tf)
    return []


def audit_series(entry: dict[str, Any]) -> SeriesQAResult:
    result = SeriesQAResult(
        id=entry["id"],
        section=entry["section"],
        key=entry["key"],
        status=entry.get("status", "ok"),
        rows_loaded=0,
        rows_manifest=int(entry.get("row_count") or 0),
        ts_min=None,
        ts_max=None,
        manifest_ts_min=entry.get("ts_min"),
        manifest_ts_max=entry.get("ts_max"),
        duplicate_timestamps=0,
        tz_utc=True,
        daily_midnight=None,
    )

    if result.status != "ok":
        result.add("info", "SKIPPED", entry.get("notes") or "not ingested")
        return result

    data, is_daily, calendar_id = _load_entry(entry)
    if data is None:
        if entry["id"] == "E2":
            result.add("info", "AGGREGATE_CHILD", "Per-ticker ETF — checked in cross-check E2")
            return result
        if entry["id"] in ("C3", "C4", "C5"):
            result.add("info", "CHAIN_META", entry.get("notes") or "chain metadata only")
            result.rows_loaded = int(entry.get("row_count") or 0)
            return result
        result.add("error", "LOAD_FAILED", "Could not load series from disk")
        return result

    if isinstance(data, pd.DataFrame):
        if "close" in data.columns:
            idx = data.index
        else:
            idx = data.index
    else:
        idx = data.index

    idx = pd.DatetimeIndex(idx)
    result.rows_loaded = len(idx)
    if len(idx):
        result.ts_min = str(idx.min().date())
        result.ts_max = str(idx.max().date())
        result.first_row = _row_preview(data, head=True)
        result.last_row = _row_preview(data, head=False)

    dup = int(idx.duplicated().sum())
    result.duplicate_timestamps = dup
    if dup:
        result.add("error", "DUPLICATE_TS", f"{dup} duplicate timestamp(s)")

    _check_index(idx, daily=is_daily, result=result)

    if result.rows_manifest and abs(result.rows_loaded - result.rows_manifest) > max(2, result.rows_manifest * 0.02):
        result.add(
            "warning",
            "MANIFEST_ROW_MISMATCH",
            f"loaded {result.rows_loaded} rows vs manifest {result.rows_manifest}",
        )
    if result.manifest_ts_min and result.ts_min and result.manifest_ts_min != result.ts_min:
        result.add("warning", "MANIFEST_MIN_MISMATCH", f"disk {result.ts_min} vs manifest {result.manifest_ts_min}")
    if result.manifest_ts_max and result.ts_max and result.manifest_ts_max != result.ts_max:
        result.add("warning", "MANIFEST_MAX_MISMATCH", f"disk {result.ts_max} vs manifest {result.manifest_ts_max}")

    paths = _macro_paths_for_entry(entry)
    _check_period_boundaries(idx, paths=paths, result=result, calendar_id=calendar_id, section=entry["section"])

    # OHLCV daily audit
    if isinstance(data, pd.DataFrame) and "close" in data.columns and is_daily:
        cal = calendar_id or "crypto_24_7"
        asset = get_instrument(Symbol.parse(entry["key"].rsplit("@", 1)[0]))
        asset_class = asset.asset_class if asset else "crypto"
        warnings = audit_bars(data, "1d", cal, asset_class=asset_class)
        for w in warnings:
            lvl: Level = "error" if w.level == "error" else "warning" if w.level == "warning" else "info"
            result.add(lvl, w.code, w.message)

    # available_utc must not precede bar (would imply same-day leak before lag rule)
    if isinstance(data, pd.DataFrame) and "available_utc" in data.columns:
        avail = pd.to_datetime(data["available_utc"], utc=True)
        bar = pd.DatetimeIndex(data.index)
        if bar.tz is None:
            bar = bar.tz_localize("UTC")
        leaks = avail < bar
        if leaks.any():
            result.add("error", "AVAILABLE_UTC_LEAK", f"{int(leaks.sum())} rows with available_utc before bar date")
        elif entry["section"] in ("institutional", "network"):
            result.add("info", "AVAILABLE_UTC_LAG", f"publication lag enforced ({int((avail > bar).sum())} rows)")

    # Fear/greed range
    if entry["id"] == "F1":
        s = data["value"] if isinstance(data, pd.DataFrame) else data
        out_of_range = s[(s < 0) | (s > 100)].dropna()
        if len(out_of_range):
            result.add("error", "FEAR_GREED_RANGE", f"{len(out_of_range)} values outside [0,100]")

    return result


def cross_checks() -> list[QAFinding]:
    findings: list[QAFinding] = []
    start = datetime(2024, 1, 11, tzinfo=timezone.utc)
    end = LOAD_END

    # E1 vs sum(E2 tickers)
    try:
        agg = macro_store.load_frame("farside", "etf_flow_aggregate_us", start, end)
        frames: list[pd.Series] = []
        for t in _etf_tickers_from_universe():
            try:
                df = macro_store.load_frame("farside", f"etf_flow_{t}", start, end)
                frames.append(df["value"].rename(t))
            except FileNotFoundError:
                continue
        if frames and not agg.empty:
            ticker_df = pd.concat(frames, axis=1)
            common = agg.index.intersection(ticker_df.dropna(how="all").index)
            summed = ticker_df.loc[common].sum(axis=1, min_count=1)
            diff = (agg.loc[common, "value"] - summed).abs().dropna()
            if len(diff):
                max_diff = float(diff.max())
                worst_day = diff.idxmax()
                if max_diff > 5_000_000:  # $5m — Farside rounds to 0.1m
                    findings.append(
                        QAFinding(
                            "E1/E2",
                            "warning",
                            "ETF_SUM_MISMATCH",
                            f"max |Total−Σtickers|=${max_diff:,.0f} on {worst_day.date()}",
                        )
                    )
                else:
                    findings.append(
                        QAFinding("E1/E2", "info", "ETF_SUM_OK", f"max diff ${max_diff:,.0f}")
                    )
    except Exception as exc:
        findings.append(QAFinding("E1/E2", "error", "ETF_RECON_FAILED", str(exc)))

    # MSTR holdings monotonic
    try:
        h = macro_store.load_frame("strategy", "mstr_btc_holdings", datetime(2020, 8, 1, tzinfo=timezone.utc), end)
        drops = h["btc_holding"].diff().dropna()
        big_drops = drops[drops < -100]
        if len(big_drops):
            findings.append(
                QAFinding("E5", "warning", "MSTR_HOLDINGS_DROP", f"{len(big_drops)} large holding decrease(s)")
            )
        else:
            findings.append(QAFinding("E5", "info", "MSTR_HOLDINGS_OK", "holdings step function non-decreasing"))
    except Exception as exc:
        findings.append(QAFinding("E5", "error", "MSTR_CHECK_FAILED", str(exc)))

    # MSTR purchases delta vs holdings
    try:
        p = macro_store.load_frame("strategy", "mstr_btc_purchases", datetime(2020, 8, 1, tzinfo=timezone.utc), end)
        if "btc_acq" in p.columns and (p["btc_acq"] < 0).any():
            n = int((p["btc_acq"] < 0).sum())
            findings.append(QAFinding("E4", "info", "MSTR_SALES", f"{n} negative btc_acq (sales/redemptions)"))
    except Exception as exc:
        findings.append(QAFinding("E4", "warning", "MSTR_PURCHASES_CHECK", str(exc)))

    return findings


def run_phase1_qa(manifest_path: Path) -> QAReport:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report = QAReport(
        run_at=datetime.now(timezone.utc).isoformat(),
        series_checked=0,
        errors=0,
        warnings=0,
    )

    for entry in manifest.get("series", []):
        if entry.get("status") == "skipped":
            continue
        res = audit_series(entry)
        report.series.append(res)
        report.series_checked += 1
        for f in res.findings:
            if f.level == "error":
                report.errors += 1
            elif f.level == "warning":
                report.warnings += 1

    report.cross_checks = cross_checks()
    for f in report.cross_checks:
        if f.level == "error":
            report.errors += 1
        elif f.level == "warning":
            report.warnings += 1

    return report


def format_report_text(report: QAReport) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("BTCpredict Phase 1 QA Report")
    lines.append(f"Run: {report.run_at}")
    lines.append(f"Series checked: {report.series_checked}  |  errors: {report.errors}  |  warnings: {report.warnings}")
    lines.append("=" * 72)

    for res in report.series:
        flags = [f.code for f in res.findings if f.level in ("error", "warning")]
        flag_str = f"  ⚠ {', '.join(flags)}" if flags else ""
        lines.append("")
        lines.append(f"[{res.id}] {res.key}  ({res.rows_loaded} rows, {res.ts_min} → {res.ts_max}){flag_str}")
        if res.first_row:
            lines.append(f"  first: {res.first_row}")
        if res.last_row:
            lines.append(f"  last:  {res.last_row}")
        if res.period_boundaries:
            pb = res.period_boundaries
            lines.append(f"  partitions: {len(pb)}  first={pb[0]['partition']} last={pb[-1]['partition']}")
            # show year-end / recent month edges
            for edge in (pb[0], pb[-1]):
                lines.append(f"    {edge['partition']}: {edge['first']} → {edge['last']} ({edge['rows']} rows)")
        for f in res.findings:
            if f.level != "info":
                lines.append(f"  [{f.level.upper()}] {f.code}: {f.message}")

    lines.append("")
    lines.append("--- Cross-checks ---")
    for f in report.cross_checks:
        lines.append(f"  [{f.level.upper()}] {f.series_id} {f.code}: {f.message}")

    lines.append("")
    lines.append(f"Overall: {report.worst_level().upper()}")
    return "\n".join(lines)


def write_report(report: QAReport, json_path: Path, text_path: Path | None = None) -> None:
    payload = asdict(report)
    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    if text_path:
        text_path.write_text(format_report_text(report) + "\n", encoding="utf-8")
