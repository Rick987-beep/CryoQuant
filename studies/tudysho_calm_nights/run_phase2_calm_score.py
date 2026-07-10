#!/usr/bin/env python3
"""Phase 2 — overnight_calm_score prototype and promotion evaluation.

Run from CryoQuant repo root:
    python studies/tudysho_calm_nights/run_phase2_calm_score.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))
sys.path.insert(0, str(STUDY_DIR / "src"))

from cryoquant.reporting import write_phase_summary

from src.overnight_calm_score import (
    compute_overnight_calm_score,
    evaluate_vs_turbulence_only,
    threshold_sweep,
)
from src.paths import data_dir, reports_dir


def main() -> int:
    feat_path = data_dir() / "phase1_features.parquet"
    if not feat_path.is_file():
        print("[phase2] Run phase 1 first")
        return 2

    enriched = pd.read_parquet(feat_path)
    cont_path = reports_dir() / "contingency_summary.json"
    contingency = json.loads(cont_path.read_text()) if cont_path.is_file() else {}

    # Tail labels from phase 1 logic
    from src.phase1_features import _tail_labels

    enriched = enriched.copy()
    enriched["is_tail"] = _tail_labels(enriched, contingency)

    score = compute_overnight_calm_score(enriched)
    enriched["overnight_calm_score"] = score

    sweep = threshold_sweep(enriched, enriched["overnight_calm_score"])
    vs_turb = evaluate_vs_turbulence_only(enriched)

    phase0_path = reports_dir() / "phase_0_extrusion.json"
    contract_ok = False
    if phase0_path.is_file():
        p0 = json.loads(phase0_path.read_text())
        cf = p0.get("metrics", {}).get("counterfactual", {})
        contract_ok = cf.get("contract_reduction_passed", False)

    promote = (
        vs_turb.get("score_beats_turbulence", False)
        and contract_ok
    )

    out_parquet = data_dir() / "phase2_calm_score.parquet"
    enriched.to_parquet(out_parquet, index=False)

    metrics = {
        "threshold_sweep": sweep,
        "vs_turbulence": vs_turb,
        "score_median": float(score.median()),
        "score_mean": float(score.mean()),
        "contract_efficiency_preserved": contract_ok,
        "promotion_recommended": promote,
        "promotion_target": "cryoquant/features/overnight_calm.py" if promote else None,
    }

    detail_path = reports_dir() / "phase_2_calm_score_detail.json"
    detail_path.write_text(json.dumps(metrics, indent=2, default=str))

    summary_path = reports_dir() / "phase_2_calm_score.json"
    write_phase_summary(
        summary_path,
        phase_id="phase_2_calm_score",
        metrics=metrics,
        artifacts={"scored_parquet": str(out_parquet), "detail": str(detail_path)},
        status="ok" if promote else "review",
        notes="Promotion to cryoquant/features/ only if promotion_recommended is true.",
    )

    print(f"[phase2] Wrote {out_parquet}, {detail_path}, {summary_path}")
    print(f"[phase2] Promotion recommended: {promote}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
