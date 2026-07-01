#!/usr/bin/env python3
"""Phase 1 — ingest approved BTCpredict universe and write ingest manifest."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.ingest import run_btcpredict_ingest, write_manifest
from src.paths import ANALYSIS_ROOT, data_dir, load_study_config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="BTCpredict Phase 1 data ingest")
    parser.add_argument("--force", action="store_true", help="Overwrite existing partitions")
    parser.add_argument("--dry-run", action="store_true", help="Log only; no fetches")
    parser.add_argument("--smoke", action="store_true", help="Last 30 days only")
    parser.add_argument("--skip-optional", action="store_true",
                        help="Skip institutional E-series (Farside ETF + Strategy MSTR)")
    args = parser.parse_args()

    cfg = load_study_config()
    if not cfg.data_sources_reviewed:
        log.error("data_sources_reviewed is false — sign off DATA_SOURCES.md first")
        return 2

    universe_path = ANALYSIS_ROOT / "universe.yaml"
    if not universe_path.exists():
        log.error("Missing universe.yaml at %s", universe_path)
        return 2

    log.info("Phase 1 ingest — universe %s", universe_path)
    manifest = run_btcpredict_ingest(
        universe_path,
        force=args.force,
        dry_run=args.dry_run,
        smoke=args.smoke,
        skip_optional=args.skip_optional,
        study_id=cfg.study_id,
    )

    out = data_dir() / "ingest_manifest.json"
    write_manifest(manifest, out)
    log.info("Wrote %s (%d ok, %d skipped, %d failed)", out, manifest.ok, manifest.skipped, manifest.failed)

    if manifest.failed > 0 and manifest.ok == 0:
        return 2
    if manifest.failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
