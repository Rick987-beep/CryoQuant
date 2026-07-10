#!/usr/bin/env python3
"""Run Phase 0 + Phase 3 for both predictor variants and write comparison report."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))
sys.path.insert(0, str(STUDY_DIR / "src"))

from src.paths import reports_dir
from src.report_compare_predictors import render_compare_report

VARIANTS = ("us_morning", "london_us")


def main() -> int:
    py = sys.executable
    for v in VARIANTS:
        for script in ("run_phase0_session_extrusion.py", "run_phase3_continuous_calm.py"):
            cmd = [py, str(STUDY_DIR / script), "--predictor", v]
            print(f"[compare] {' '.join(cmd)}")
            rc = subprocess.call(cmd)
            if rc != 0:
                print(f"[compare] failed: {script} --predictor {v} (exit {rc})")
                return rc

    rows = []
    for v in VARIANTS:
        p0 = reports_dir() / v / "phase_0_extrusion.json"
        p3 = reports_dir() / v / "phase_3_continuous_calm.json"
        row = {"variant": v}
        if p0.is_file():
            row["phase0"] = json.loads(p0.read_text()).get("metrics", {})
        if p3.is_file():
            row["phase3"] = json.loads(p3.read_text()).get("metrics", {})
        rows.append(row)

    out = reports_dir() / "predictor_comparison.json"
    out.write_text(json.dumps(rows, indent=2, default=str))
    html = reports_dir() / "predictor_comparison.html"
    render_compare_report(rows, html)
    print(f"[compare] Wrote {out} and {html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
