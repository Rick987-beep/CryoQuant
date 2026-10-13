#!/usr/bin/env python3
"""Take a fresh market snapshot and (optionally) make it the active run.

Writes ``input/snapshots/<stamp>/data`` (same layout as the v5 reference) plus
``manifest.json``. With ``--activate`` it sets ``snapshot.stamp`` in
``config.yaml`` so phases 1–5 and the explorer read the new data.

Usage:
    python studies/france_sovereign_stress/run_snapshot.py --activate
    python studies/france_sovereign_stress/run_snapshot.py --stamp 2026-10-12T0935 --force
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

from src.data.snapshot import build_snapshot
from src.refresh import set_active_stamp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", default=None, help="default: now, Europe/Berlin, YYYY-MM-DDTHHMM")
    ap.add_argument("--force", action="store_true", help="overwrite an existing snapshot")
    ap.add_argument("--activate", action="store_true", help="set snapshot.stamp in config.yaml")
    ap.add_argument("--with-options", action="store_true", help="scrape OOAT/OGBL chains (Playwright)")
    ap.add_argument("--with-bank-options", action="store_true", help="scrape BNP/GLE/ACA option chains")
    ap.add_argument("--with-long-banks", action="store_true", help="fetch Yahoo bank history from 2010")
    args = ap.parse_args()

    out = build_snapshot(
        args.stamp,
        force=args.force,
        with_options=args.with_options,
        with_bank_options=args.with_bank_options,
        with_long_banks=args.with_long_banks,
    )
    manifest = json.loads((out.parent / "manifest.json").read_text())
    q = manifest["quote"]
    print(f"snapshot {manifest['stamp']} → {out}")
    print(
        f"  live quote OAT {q['oat10']:.4f}% / Bund {q['bund10']:.4f}% "
        f"= {q['spread_bp']:.2f} bp at {q['time']}"
    )
    print(f"  history cutoff {manifest['history_cutoff']}")
    for name, info in manifest["files"].items():
        if "fresh_rows_added" in info:
            print(
                f"  {name}: +{info['fresh_rows_added']} rows (from {info['first_added']}), "
                f"last {info['last_date']}, overlap diffs {info['overlap_max_abs_diff']}"
            )
    if args.activate:
        set_active_stamp(manifest["stamp"])
        print(f"  activated in config.yaml: snapshot.stamp = {manifest['stamp']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
