#!/usr/bin/env python3
"""Batch-ingest the VIXStrategy universe into local CryoQuant stores."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

from cryoquant.data.ingest import run_ingest

from src.paths import ANALYSIS_ROOT, load_config
from src.vix_data import ingest_start


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Overwrite cached partitions")
    parser.add_argument("--dry-run", action="store_true", help="List symbols only; do not fetch")
    args = parser.parse_args()

    cfg = load_config()
    start = ingest_start(cfg).strftime("%Y-%m-%d")
    end = cfg["window"].get("end")

    print(f"[ingest] universe {ANALYSIS_ROOT / 'universe.yaml'} start={start}")
    result = run_ingest(
        ANALYSIS_ROOT / "universe.yaml",
        start=start,
        end=end,
        force=args.force,
        dry_run=args.dry_run,
        macro_only=True,
    )
    print(f"[ingest] ok={result.ok} failed={result.failed}")
    return result.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
