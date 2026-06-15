"""Trend-following universe ingestion CLI.

Thin wrapper around ``cryoquant.data.ingest`` — see that module for the
reusable orchestration logic.

Usage::

    python -m analyses.trend_following.run_ingest
    python -m analyses.trend_following.run_ingest --tf 1d,1h --audit
    python -m analyses.trend_following.run_ingest --macro-only --force
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from cryoquant.data import ingest

_HERE = Path(__file__).resolve().parent
_UNIVERSE_YAML = _HERE / "universe.yaml"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("run_ingest")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Ingest the trend-following universe into CryoQuant data store.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--tf", default="1d,1h", help="Comma-separated timeframes (default: 1d,1h)")
    p.add_argument(
        "--start",
        help="Start date YYYY-MM-DD (default: 2010-01-01 daily, 2020-01-01 hourly)",
    )
    p.add_argument("--end", help="End date YYYY-MM-DD (default: today)")
    p.add_argument(
        "--symbols",
        help="Comma-separated symbol strings (e.g. yahoo:SPY,fred:US10Y)",
    )
    p.add_argument("--macro-only", action="store_true", help="FRED + CBOE macro only")
    p.add_argument("--ohlcv-only", action="store_true", help="OHLCV only, skip macro")
    p.add_argument("--force", action="store_true", help="Delete and re-fetch partitions")
    p.add_argument("--dry-run", action="store_true", help="Print plan without fetching")
    p.add_argument("--audit", action="store_true", help="Run audit_bars after ingest")
    p.add_argument("--universe", default=str(_UNIVERSE_YAML), help="Path to universe YAML")
    p.add_argument("--verbose", "-v", action="store_true", help="DEBUG logging")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    tfs = [t.strip() for t in args.tf.split(",") if t.strip()]
    symbols = (
        [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.symbols else None
    )

    result = ingest.run_ingest(
        Path(args.universe),
        tfs=tfs,
        start=args.start,
        end=args.end,
        symbols=symbols,
        macro_only=args.macro_only,
        ohlcv_only=args.ohlcv_only,
        force=args.force,
        dry_run=args.dry_run,
        audit=args.audit,
        daily_start=ingest.DEFAULT_DAILY_START,
        hourly_start=ingest.DEFAULT_HOURLY_START,
    )
    return result.exit_code()


if __name__ == "__main__":
    sys.exit(main())
