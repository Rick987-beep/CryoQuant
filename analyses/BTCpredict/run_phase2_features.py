#!/usr/bin/env python3
"""Phase 2 — build feature matrix and write parquet + schema."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.feature_schema import validate_panel_columns, write_features_schema
from src.panel_build import build_study_panel
from src.paths import data_dir, load_study_config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="BTCpredict Phase 2 feature build")
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date YYYY-MM-DD (default: now UTC)",
    )
    args = parser.parse_args()

    cfg = load_study_config()
    if not cfg.phase1_complete:
        log.error("phase1_complete must be true before building features")
        return 2
    if not cfg.phase2_catalog_reviewed:
        log.error("phase2_catalog_reviewed must be true before building features")
        return 2

    end = None
    if args.end:
        end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    log.info("Building feature panel (dev_start=%s)", cfg.splits.dev_start)
    df = build_study_panel(cfg, end=end)

    missing = validate_panel_columns(list(df.columns))
    if missing:
        log.warning("Panel missing %d catalog columns: %s", len(missing), missing[:20])

    out_parquet = data_dir() / "features.parquet"
    out_schema = data_dir() / "features_schema.json"
    df.to_parquet(out_parquet, index=False)
    schema = write_features_schema(list(df.columns), out_schema)

    log.info("Wrote %s (%d rows, %d cols)", out_parquet, len(df), len(df.columns))
    log.info("Wrote %s (catalog features=%d, missing=%d)", out_schema, schema["column_count"], len(missing))

    if missing:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
