#!/usr/bin/env python3
"""Regenerate Phase 4 human-readable training report from manifest."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.paths import data_dir, reports_dir
from src.phase4_report import write_training_report


def main() -> int:
    parser = argparse.ArgumentParser(description="BTCpredict Phase 4 training report")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to phase4_training_manifest.json",
    )
    args = parser.parse_args()

    manifest = args.manifest or (data_dir() / "phase4_training_manifest.json")
    if not manifest.is_file():
        print(f"Missing manifest: {manifest}", file=sys.stderr)
        return 2

    txt_out = reports_dir() / "phase4_training_report.txt"
    json_out = data_dir() / "phase4_training_report.json"
    text = write_training_report(manifest, txt_out, json_out)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
