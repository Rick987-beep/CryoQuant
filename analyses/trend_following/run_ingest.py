"""Phase 1 ingestion orchestrator for the trend-following universe.

Usage::

    # Full ingest — daily + hourly, from default start date
    python -m analyses.trend_following.run_ingest

    # Specific timeframes
    python -m analyses.trend_following.run_ingest --tf 1d,1h

    # Custom date range
    python -m analyses.trend_following.run_ingest --tf 1d --start 2010-01-01

    # Macro / VIX only
    python -m analyses.trend_following.run_ingest --macro-only

    # Specific symbols only
    python -m analyses.trend_following.run_ingest --symbols yahoo:SPY,yahoo:GLD --tf 1d

    # Force re-fetch (deletes existing partitions for matching symbols)
    python -m analyses.trend_following.run_ingest --tf 1d --symbols yahoo:SPY --force

    # Dry run — show what would be fetched without touching disk
    python -m analyses.trend_following.run_ingest --dry-run

    # Print QA audit report after ingest
    python -m analyses.trend_following.run_ingest --audit

Exit codes:
    0 — success (all requested series ingested)
    1 — partial failure (some series errored; check logs)
    2 — all series failed
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("run_ingest")

_HERE = Path(__file__).resolve().parent
_UNIVERSE_YAML = _HERE / "universe.yaml"

# Default historical start date
_DEFAULT_DAILY_START = "2010-01-01"
_DEFAULT_HOURLY_START = "2020-01-01"   # Twelve Data 1h available from ~2020-02-10


# ---------------------------------------------------------------------------
# Universe loading
# ---------------------------------------------------------------------------

def load_universe(yaml_path: Path = _UNIVERSE_YAML) -> dict[str, Any]:
    with open(yaml_path) as f:
        return yaml.safe_load(f)


def iter_ohlcv_symbols(
    universe: dict[str, Any],
    filter_tickers: list[str] | None = None,
    filter_tfs: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Yield (symbol_str, tf) for all OHLCV symbols (yahoo venue)."""
    results: list[tuple[str, str]] = []
    for group_name, group in universe.items():
        if not isinstance(group, dict):
            continue
        if group_name in ("macro_fred", "macro_cboe"):
            continue
        tfs = group.get("timeframes", ["1d"])
        for sym_str in group.get("symbols", []):
            if filter_tickers and sym_str not in filter_tickers:
                continue
            for tf in tfs:
                if filter_tfs and tf not in filter_tfs:
                    continue
                results.append((sym_str, tf))
    return results


def iter_macro_symbols(
    universe: dict[str, Any],
    filter_tickers: list[str] | None = None,
) -> list[str]:
    """Yield symbol strings for macro series (fred + cboe)."""
    results: list[str] = []
    for group_name in ("macro_fred", "macro_cboe"):
        group = universe.get(group_name, {})
        for sym_str in group.get("symbols", []):
            if filter_tickers and sym_str not in filter_tickers:
                continue
            results.append(sym_str)
    return results


# ---------------------------------------------------------------------------
# Ingestion helpers
# ---------------------------------------------------------------------------

def ingest_ohlcv(
    sym_str: str,
    tf: str,
    start: datetime,
    end: datetime,
    force: bool = False,
    dry_run: bool = False,
) -> bool:
    """Fetch and store one OHLCV symbol/tf.  Returns True on success."""
    from cryocore.instruments import Symbol
    from cryoquant.data import loader as ldr
    from cryoquant import config

    symbol = Symbol.parse(sym_str)

    if force:
        _delete_partitions(symbol, tf, start, end)

    if dry_run:
        log.info("[DRY RUN] Would ingest %s %s [%s → %s]",
                 sym_str, tf, start.date(), end.date())
        return True

    try:
        df = ldr.load(symbol, tf, start, end)
        log.info("OK  %s %s — %d bars [%s → %s]",
                 sym_str, tf, len(df),
                 df.index.min().date() if not df.empty else "n/a",
                 df.index.max().date() if not df.empty else "n/a")
        return True
    except Exception as exc:
        log.error("FAIL %s %s — %s", sym_str, tf, exc)
        return False


def ingest_macro(
    sym_str: str,
    start: datetime,
    end: datetime,
    force: bool = False,
    dry_run: bool = False,
) -> bool:
    """Fetch and store one macro series.  Returns True on success."""
    from cryocore.instruments import Symbol
    from cryoquant.data import macro_store

    symbol = Symbol.parse(sym_str)
    source = symbol.venue
    series_id = symbol.ticker

    if dry_run:
        log.info("[DRY RUN] Would ingest macro %s/%s [%s → %s]",
                 source, series_id, start.date(), end.date())
        return True

    try:
        if source == "fred":
            from cryoquant.data.sources.fred import fetch_series
            s = fetch_series(series_id, start, end)
            macro_store.write_series(source, series_id, s, force=force)
        elif source == "cboe":
            from cryoquant.data.sources.cboe import fetch_vix
            vix_df = fetch_vix(start, end)
            # Store close column as the primary scalar series
            macro_store.write_series("cboe", "VIX_CLOSE", vix_df["close"], force=force)
            # Also store the full OHLC frame as separate series for audit
            for col in ("open", "high", "low"):
                if col in vix_df.columns and not vix_df[col].isnull().all():
                    macro_store.write_series("cboe", f"VIX_{col.upper()}", vix_df[col], force=force)
        else:
            log.error("FAIL %s — unknown macro venue %r", sym_str, source)
            return False

        log.info("OK  macro %s/%s", source, series_id)
        return True
    except Exception as exc:
        log.error("FAIL macro %s — %s", sym_str, exc)
        return False


def _delete_partitions(symbol: Any, tf: str, start: datetime, end: datetime) -> None:
    """Remove on-disk partitions and sentinels for symbol/tf so they will be re-fetched."""
    from cryoquant.data.loader import _partition_path, _sentinel_path
    import pandas as pd
    periods = pd.period_range(start=start, end=end, freq="M")
    removed = 0
    for p in periods:
        for path in (_partition_path(symbol, tf, p.year, p.month),
                     _sentinel_path(symbol, tf, p.year, p.month)):
            if path.exists():
                path.unlink()
                removed += 1
    if removed:
        log.info("force: removed %d file(s) for %s %s", removed, symbol, tf)


def run_audit(
    universe: dict[str, Any],
    start: datetime,
    end: datetime,
    filter_tickers: list[str] | None = None,
    filter_tfs: list[str] | None = None,
) -> None:
    """Run audit_bars on all ingested symbols and print a report."""
    from cryocore.instruments import Symbol, get_instrument
    from cryoquant.data import loader as ldr
    from cryoquant.data.cleaning import audit_bars

    pairs = iter_ohlcv_symbols(universe, filter_tickers, filter_tfs)
    issues_total = 0
    for sym_str, tf in pairs:
        symbol = Symbol.parse(sym_str)
        try:
            df = ldr.load(symbol, tf, start, end)
            instr = get_instrument(symbol)
            cal = instr.calendar_id if instr else "nyse"
            warnings = audit_bars(df, tf, cal)
            errors = [w for w in warnings if w.level == "error"]
            warnings_only = [w for w in warnings if w.level == "warning"]
            issues_total += len(errors) + len(warnings_only)
            if errors or warnings_only:
                log.warning("AUDIT %s %s — %d errors, %d warnings",
                            sym_str, tf, len(errors), len(warnings_only))
                for w in errors + warnings_only:
                    log.warning("  %s", w)
            else:
                log.info("AUDIT OK  %s %s (%d bars)", sym_str, tf, len(df))
        except Exception as exc:
            log.error("AUDIT SKIP %s %s — %s", sym_str, tf, exc)

    log.info("Audit complete — %d total issues across all symbols", issues_total)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Ingest the trend-following universe into CryoQuant data store.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--tf", default="1d,1h",
        help="Comma-separated timeframes to ingest (default: 1d,1h)",
    )
    p.add_argument(
        "--start",
        help=(
            "Start date (YYYY-MM-DD). Default: 2010-01-01 for daily, "
            "2020-01-01 for hourly (Twelve Data limit ~2020-02-10)."
        ),
    )
    p.add_argument(
        "--end",
        help="End date (YYYY-MM-DD). Default: today.",
    )
    p.add_argument(
        "--symbols",
        help="Comma-separated list of symbol strings to ingest (e.g. yahoo:SPY,fred:US10Y). "
             "Default: full universe.",
    )
    p.add_argument(
        "--macro-only", action="store_true",
        help="Only ingest FRED + CBOE macro series (skip OHLCV).",
    )
    p.add_argument(
        "--ohlcv-only", action="store_true",
        help="Only ingest OHLCV series (skip macro).",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Delete and re-fetch existing partitions for the requested range.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be fetched without touching disk.",
    )
    p.add_argument(
        "--audit", action="store_true",
        help="Run audit_bars on all ingested symbols after ingest and print report.",
    )
    p.add_argument(
        "--universe", default=str(_UNIVERSE_YAML),
        help="Path to universe YAML file.",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Set log level to DEBUG.",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    universe = load_universe(Path(args.universe))

    tfs = [t.strip() for t in args.tf.split(",") if t.strip()]
    filter_tickers = (
        [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.symbols else None
    )

    end_dt = (
        datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if args.end else datetime.now(timezone.utc)
    )

    # Determine start per-timeframe (yfinance 1h limit)
    def _start(tf: str) -> datetime:
        if args.start:
            return datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (
            datetime.strptime(_DEFAULT_DAILY_START, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if tf == "1d"
            else datetime.strptime(_DEFAULT_HOURLY_START, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        )

    ok_count = 0
    fail_count = 0

    # --- OHLCV ---
    if not args.macro_only:
        pairs = iter_ohlcv_symbols(universe, filter_tickers, tfs)
        log.info("Ingesting %d OHLCV (symbol, tf) pairs …", len(pairs))
        for sym_str, tf in pairs:
            success = ingest_ohlcv(
                sym_str, tf, _start(tf), end_dt,
                force=args.force, dry_run=args.dry_run,
            )
            if success:
                ok_count += 1
            else:
                fail_count += 1

    # --- Macro ---
    if not args.ohlcv_only:
        macro_syms = iter_macro_symbols(universe, filter_tickers)
        log.info("Ingesting %d macro series …", len(macro_syms))
        macro_start = (
            datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if args.start
            else datetime.strptime(_DEFAULT_DAILY_START, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        )
        for sym_str in macro_syms:
            success = ingest_macro(
                sym_str, macro_start, end_dt,
                force=args.force, dry_run=args.dry_run,
            )
            if success:
                ok_count += 1
            else:
                fail_count += 1

    # --- Audit ---
    if args.audit and not args.dry_run:
        log.info("Running post-ingest audit …")
        run_audit(universe, _start("1d"), end_dt, filter_tickers, tfs)

    total = ok_count + fail_count
    log.info("Done: %d/%d succeeded, %d failed.", ok_count, total, fail_count)

    if fail_count == 0:
        return 0
    if ok_count == 0:
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
