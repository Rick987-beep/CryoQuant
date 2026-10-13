#!/usr/bin/env python3
"""Refresh market data and rerun the whole study on it.

Takes a live snapshot (entry at the current CNBC quote, history to the last
full session), activates it in ``config.yaml``, and runs phases 1–5 plus both
explorers. Per-step logs go to ``reports/refresh/<stamp>/``.

Usage:
    python studies/france_sovereign_stress/run_refresh.py
    python studies/france_sovereign_stress/run_refresh.py --reuse 2026-10-12T0941
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

from src.paths import data_dir
from src.refresh import refresh


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", default=None, help="snapshot stamp (default: now, Europe/Berlin)")
    ap.add_argument("--reuse", metavar="STAMP", help="rerun on an existing snapshot, no fetch")
    args = ap.parse_args()

    stamp = args.reuse or args.stamp
    try:
        res = refresh(stamp, reuse=bool(args.reuse))
    except RuntimeError as exc:
        print(f"refresh failed: {exc}\nconfig.yaml still points at the previous snapshot.")
        return 1

    q = res.manifest["quote"]
    p5 = json.loads((data_dir() / "phase5_evaluate.json").read_text())
    a300, wrong = p5["primary"]["at_300"], p5["primary"]["wrong"]
    print(f"\nsnapshot {res.stamp} active (was {res.previous})")
    if res.archived:
        print(f"  previous outputs archived to {res.archived}")
    print(f"  entry {q['spread_bp']:.2f} bp at {q['time']}  (OAT {q['oat10']:.3f}%, Bund {q['bund10']:.3f}%)")
    print(f"  history to {res.manifest['history_cutoff']}")
    print(
        f"  300 bp exit: mean {a300['mean']:.2f}×, median {a300['median']:.2f}×, "
        f"stopped out {100 * a300['p_lost']:.1f}%; no stress: mean {wrong['mean']:.2f}×"
    )
    for w in res.warnings:
        print(f"  warning: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
