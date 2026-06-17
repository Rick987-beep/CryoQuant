"""Generic data-ingestion orchestrator.

Reads a universe YAML manifest and dispatches OHLCV loads via ``loader`` and
macro series via ``macro_store``.  Analysis folders supply ``universe.yaml``
and a thin CLI wrapper (see ``analyses/trend_following/run_ingest.py``).

Public interface::

    load_universe(path) -> dict
    iter_ohlcv_symbols(universe, ...) -> list[(symbol_str, tf)]
    iter_macro_symbols(universe, ...) -> list[symbol_str]
    ingest_ohlcv(sym_str, tf, start, end, ...) -> bool
    ingest_macro(sym_str, start, end, ...) -> bool
    run_audit(universe, start, end, ...) -> int
    run_ingest(universe_path, ...) -> IngestResult
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from cryocore.instruments import Symbol, get_instrument

log = logging.getLogger(__name__)

DEFAULT_DAILY_START = "2010-01-01"
DEFAULT_HOURLY_START = "2020-01-01"
MACRO_GROUP_PREFIX = "macro_"


@dataclass
class IngestResult:
    """Summary of one ingest run."""

    ok: int = 0
    failed: int = 0
    audit_issues: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.ok + self.failed

    def exit_code(self) -> int:
        if self.failed == 0:
            return 0
        if self.ok == 0:
            return 2
        return 1


def load_universe(yaml_path: Path | str) -> dict[str, Any]:
    with open(yaml_path) as f:
        return yaml.safe_load(f)


def iter_ohlcv_symbols(
    universe: dict[str, Any],
    filter_tickers: list[str] | None = None,
    filter_tfs: list[str] | None = None,
) -> list[tuple[str, str, dict[str, Any]]]:
    """Return ``(symbol_str, tf, group)`` for all non-macro universe groups.

    *group* is the YAML group dict (may contain ``start_daily`` / ``start_hourly``).
    """
    results: list[tuple[str, str, dict[str, Any]]] = []
    for _group_name, group in universe.items():
        if not isinstance(group, dict) or _group_name.startswith(MACRO_GROUP_PREFIX):
            continue
        tfs = group.get("timeframes", ["1d"])
        for sym_str in group.get("symbols", []):
            if filter_tickers and sym_str not in filter_tickers:
                continue
            for tf in tfs:
                if filter_tfs and tf not in filter_tfs:
                    continue
                results.append((sym_str, tf, group))
    return results


def iter_macro_symbols(
    universe: dict[str, Any],
    filter_tickers: list[str] | None = None,
) -> list[str]:
    """Return symbol strings for all ``macro_*`` universe groups."""
    results: list[str] = []
    for group_name, group in universe.items():
        if not isinstance(group, dict) or not group_name.startswith(MACRO_GROUP_PREFIX):
            continue
        for sym_str in group.get("symbols", []):
            if filter_tickers and sym_str not in filter_tickers:
                continue
            results.append(sym_str)
    return results


def _start_for_tf(
    tf: str,
    *,
    start_override: str | None,
    daily_start: str,
    hourly_start: str,
    group: dict[str, Any] | None = None,
) -> datetime:
    if start_override:
        return datetime.strptime(start_override, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if group:
        if tf == "1d" and group.get("start_daily"):
            daily_start = group["start_daily"]
        elif tf != "1d" and group.get("start_hourly"):
            hourly_start = group["start_hourly"]
    default = daily_start if tf == "1d" else hourly_start
    return datetime.strptime(default, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def ingest_ohlcv(
    sym_str: str,
    tf: str,
    start: datetime,
    end: datetime,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> bool:
    """Fetch and store one OHLCV symbol/timeframe.  Returns True on success."""
    from cryoquant.data import loader as ldr

    symbol = Symbol.parse(sym_str)

    if force:
        ldr.delete_partitions(symbol, tf, start, end)

    if dry_run:
        log.info(
            "[DRY RUN] Would ingest %s %s [%s → %s]",
            sym_str, tf, start.date(), end.date(),
        )
        return True

    try:
        df = ldr.load(symbol, tf, start, end)
        log.info(
            "OK  %s %s — %d bars [%s → %s]",
            sym_str, tf, len(df),
            df.index.min().date() if not df.empty else "n/a",
            df.index.max().date() if not df.empty else "n/a",
        )
        return True
    except Exception as exc:
        log.error("FAIL %s %s — %s", sym_str, tf, exc)
        return False


def ingest_macro(
    sym_str: str,
    start: datetime,
    end: datetime,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> bool:
    """Fetch and store one macro series.  Returns True on success."""
    from cryoquant.data import macro_store

    symbol = Symbol.parse(sym_str)
    source = symbol.venue
    series_id = symbol.ticker

    if dry_run:
        log.info(
            "[DRY RUN] Would ingest macro %s/%s [%s → %s]",
            source, series_id, start.date(), end.date(),
        )
        return True

    try:
        if source == "fred":
            from cryoquant.data.sources.fred import fetch_series
            s = fetch_series(series_id, start, end)
            macro_store.write_series(source, series_id, s, force=force)
        elif source == "cboe":
            from cryoquant.data.sources.cboe import fetch_vix
            vix_df = fetch_vix(start, end)
            macro_store.write_series("cboe", "VIX_CLOSE", vix_df["close"], force=force)
            for col in ("open", "high", "low"):
                if col in vix_df.columns and not vix_df[col].isnull().all():
                    macro_store.write_series(
                        "cboe", f"VIX_{col.upper()}", vix_df[col], force=force
                    )
        else:
            log.error("FAIL %s — unknown macro venue %r", sym_str, source)
            return False

        log.info("OK  macro %s/%s", source, series_id)
        return True
    except Exception as exc:
        log.error("FAIL macro %s — %s", sym_str, exc)
        return False


def run_audit(
    universe: dict[str, Any],
    end: datetime,
    filter_tickers: list[str] | None = None,
    filter_tfs: list[str] | None = None,
    *,
    start_override: str | None = None,
    daily_start: str = DEFAULT_DAILY_START,
    hourly_start: str = DEFAULT_HOURLY_START,
) -> int:
    """Run ``audit_bars`` on ingested OHLCV symbols.  Returns total issue count."""
    from cryoquant.data import loader as ldr
    from cryoquant.data.cleaning import audit_bars

    pairs = iter_ohlcv_symbols(universe, filter_tickers, filter_tfs)
    issues_total = 0
    for sym_str, tf, group in pairs:
        symbol = Symbol.parse(sym_str)
        try:
            audit_start = _start_for_tf(
                tf, start_override=start_override,
                daily_start=daily_start,
                hourly_start=hourly_start,
                group=group,
            )
            df = ldr.load(symbol, tf, audit_start, end)
            instr = get_instrument(symbol)
            cal = instr.calendar_id if instr else "nyse"
            asset_class = instr.asset_class if instr else None
            warnings = audit_bars(df, tf, cal, asset_class=asset_class)
            errors = [w for w in warnings if w.level == "error"]
            warns = [w for w in warnings if w.level == "warning"]
            issues_total += len(errors) + len(warns)
            if errors or warns:
                log.warning(
                    "AUDIT %s %s — %d errors, %d warnings",
                    sym_str, tf, len(errors), len(warns),
                )
                for w in errors + warns:
                    log.warning("  %s", w)
            else:
                log.info("AUDIT OK  %s %s (%d bars)", sym_str, tf, len(df))
        except Exception as exc:
            log.error("AUDIT SKIP %s %s — %s", sym_str, tf, exc)

    log.info("Audit complete — %d total issues across all symbols", issues_total)
    return issues_total


def run_ingest(
    universe_path: Path | str,
    *,
    tfs: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    symbols: list[str] | None = None,
    macro_only: bool = False,
    ohlcv_only: bool = False,
    force: bool = False,
    dry_run: bool = False,
    audit: bool = False,
    daily_start: str = DEFAULT_DAILY_START,
    hourly_start: str = DEFAULT_HOURLY_START,
) -> IngestResult:
    """Ingest a full universe manifest.  Returns summary counts."""
    universe = load_universe(universe_path)
    tfs = tfs or ["1d", "1h"]
    end_dt = (
        datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if end else datetime.now(timezone.utc)
    )
    result = IngestResult()

    if not macro_only:
        pairs = iter_ohlcv_symbols(universe, symbols, tfs)
        log.info("Ingesting %d OHLCV (symbol, tf) pairs …", len(pairs))
        for sym_str, tf, group in pairs:
            ok = ingest_ohlcv(
                sym_str, tf,
                _start_for_tf(
                    tf, start_override=start, daily_start=daily_start,
                    hourly_start=hourly_start, group=group,
                ),
                end_dt,
                force=force, dry_run=dry_run,
            )
            if ok:
                result.ok += 1
            else:
                result.failed += 1

    if not ohlcv_only:
        macro_syms = iter_macro_symbols(universe, symbols)
        log.info("Ingesting %d macro series …", len(macro_syms))
        macro_start = _start_for_tf(
            "1d", start_override=start, daily_start=daily_start, hourly_start=hourly_start
        )
        for sym_str in macro_syms:
            ok = ingest_macro(sym_str, macro_start, end_dt, force=force, dry_run=dry_run)
            if ok:
                result.ok += 1
            else:
                result.failed += 1

    if audit and not dry_run:
        log.info("Running post-ingest audit …")
        result.audit_issues = run_audit(
            universe, end_dt, symbols, tfs,
            start_override=start, daily_start=daily_start, hourly_start=hourly_start,
        )

    log.info("Done: %d/%d succeeded, %d failed.", result.ok, result.total, result.failed)
    return result
