#!/usr/bin/env python3
"""Phase 3 QA — continuous calm index verification gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

from src.paths import load_config, variant_reports_dir
from src.predictor import resolve_predictor


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictor", choices=["us_morning", "london_us"], default=None)
    args = parser.parse_args()
    cfg = load_config()
    variant = resolve_predictor(cfg, args.predictor)

    path = variant_reports_dir(variant) / "phase_3_continuous_calm.json"
    if not path.is_file():
        print(f"[phase3_qa] Missing {path}")
        return 2

    payload = json.loads(path.read_text())
    metrics = payload.get("metrics", {})
    cfg = load_config()
    gates = cfg.get("phase3_gates", {})

    errors = []
    if (metrics.get("spearman_mci_hci") or 0) < gates.get("min_spearman", 0.25):
        errors.append(f"Spearman {metrics.get('spearman_mci_hci')} < {gates.get('min_spearman')}")
    if (metrics.get("permutation_p") or 1) >= gates.get("max_perm_p", 0.05):
        errors.append(f"permutation p {metrics.get('permutation_p')} >= {gates.get('max_perm_p')}")
    oos = metrics.get("oos_spearman_pred")
    if oos is None or oos < gates.get("min_oos_spearman", 0.15):
        errors.append(f"OOS Spearman {oos} < {gates.get('min_oos_spearman')}")
    if not metrics.get("gates_passed"):
        errors.append("composite gates_passed is false")

    print("[phase3_qa] Metrics:", json.dumps(metrics, indent=2))
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        return 1
    print("[phase3_qa] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
