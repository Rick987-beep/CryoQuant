#!/usr/bin/env python3
"""Phase 3 — build multi-horizon labels and write labels.parquet."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.label_build import build_study_labels, validate_label_keys, write_labels_schema
from src.paths import data_dir, load_study_config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="BTCpredict Phase 3 label build")
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date YYYY-MM-DD (default: now UTC)",
    )
    args = parser.parse_args()

    cfg = load_study_config()
    if not cfg.phase2_complete:
        log.error("phase2_complete must be true before building labels")
        return 2

    end = None
    if args.end:
        end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    log.info("Building labels (dev_start=%s, families 1-6)", cfg.splits.dev_start)
    df = build_study_labels(cfg, end=end)
    validate_label_keys(df)

    out_parquet = data_dir() / "labels.parquet"
    out_schema = data_dir() / "labels_schema.json"
    df.to_parquet(out_parquet, index=False)
    schema = write_labels_schema(df, out_schema)

    log.info("Wrote %s (%d rows)", out_parquet, len(df))
    log.info(
        "Wrote %s (%d label names, horizons=%s)",
        out_schema,
        schema["label_name_count"],
        schema["horizons"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
