#!/usr/bin/env python3
"""Phase 0 QA — gate on acceptance criteria from phase_0_extrusion.json."""

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

    phase_path = variant_reports_dir(variant) / "phase_0_extrusion.json"
    if not phase_path.is_file():
        print(f"[phase0_qa] Missing {phase_path} — run run_phase0_session_extrusion.py first")
        return 2

    payload = json.loads(phase_path.read_text())
    metrics = payload.get("metrics", {})
    cfg = load_config()
    hyp = cfg["hypothesis"]
    obj = cfg["objective"]

    errors: list[str] = []
    warnings: list[str] = []

    n_days = metrics.get("n_days", 0)
    if n_days < hyp["min_sample_days"]:
        errors.append(f"n_days={n_days} < min_sample_days={hyp['min_sample_days']}")

    if not metrics.get("primary_lift_passed"):
        errors.append(
            f"primary lift gate failed (lift={metrics.get('primary_lift')}, "
            f"need ≥{hyp['min_lift']}×, p<{hyp['max_p_value']})"
        )

    nq = metrics.get("n_predictor_quiet", metrics.get("n_morning_quiet"))
    print(f"[phase0_qa] predictor={variant}")

    if not metrics.get("false_calm_passed"):
        rate = metrics.get("false_calm_rate_pct")
        errors.append(
            f"false calm rate {rate}% >= threshold {obj['reference_tail_rate_pct']}%"
        )

    if not metrics.get("contract_reduction_passed"):
        warnings.append(
            f"contract reduction {metrics.get('contract_reduction_pct')}% < 40% target"
        )

    if not metrics.get("extrusion_safe_passed"):
        warnings.append("extrusion safe rate < 97% on aggressive profile cells")

    print("[phase0_qa] Metrics:")
    for k, v in metrics.items():
        if k != "counterfactual":
            print(f"  {k}: {v}")

    if errors:
        print(f"[phase0_qa] FAILED — {len(errors)} error(s):")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1

    if warnings:
        print(f"[phase0_qa] PASSED with {len(warnings)} warning(s):")
        for w in warnings:
            print(f"  WARN: {w}")
    else:
        print("[phase0_qa] PASSED — all hard gates satisfied")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
