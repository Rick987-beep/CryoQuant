#!/usr/bin/env python3
"""Phase 0 — validate config and freeze train/dev/hold-out split manifest."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.config_models import load_study_config, write_splits_json  # noqa: E402
from src.paths import config_path, data_dir, splits_path  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BTCpredict Phase 0 — config & splits")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config.yaml (default: analyses/BTCpredict/config.yaml)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing splits.json",
    )
    args = parser.parse_args(argv)

    cfg_path = args.config or config_path()
    if not cfg_path.is_file():
        log.error("Config not found: %s", cfg_path)
        return 2

    try:
        cfg = load_study_config(cfg_path)
    except Exception as exc:
        log.error("Config validation failed: %s", exc)
        return 2

    out = splits_path()
    if out.exists() and not args.force:
        existing = load_study_config(cfg_path)
        if existing.splits.model_dump() != cfg.splits.model_dump():
            log.error(
                "splits.json exists with different content; use --force to overwrite: %s",
                out,
            )
            return 2
        log.info("splits.json already up to date: %s", out)
        return 0

    data_dir()
    write_splits_json(cfg, out)
    log.info("Study: %s", cfg.study_id)
    log.info("Dev:   %s → %s (%s)", cfg.splits.dev_start, cfg.splits.dev_end, cfg.splits.bar_cadence)
    log.info("Hold-out from: %s", cfg.splits.holdout_start)
    log.info("Data sources reviewed: %s", cfg.data_sources_reviewed)
    log.info("Wrote %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
