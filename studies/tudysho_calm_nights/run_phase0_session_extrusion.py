#!/usr/bin/env python3
"""Phase 0 — session extrusion and predictor→night hypothesis tests.

Run from CryoQuant repo root:
    python studies/tudysho_calm_nights/run_phase0_session_extrusion.py --predictor us_morning
    python studies/tudysho_calm_nights/run_phase0_session_extrusion.py --predictor london_us
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))
sys.path.insert(0, str(STUDY_DIR / "src"))

from cryocore.instruments import Symbol
from cryoquant.data.resolve import load_track
from cryoquant.reporting import write_phase_summary

from src.contingency import run_contingency_tests
from src.counterfactual import run_counterfactual_grid
from src.daily_features import build_daily_table, filter_for_analysis, parse_date_range
from src.paths import load_config, variant_data_dir, variant_reports_dir
from src.predictor import get_predictor_spec, resolve_predictor
from src.report_phase0 import render_phase0_report


def run_phase0(variant: str) -> int:
    cfg = load_config()
    spec = get_predictor_spec(variant, cfg)
    out_dir = variant_reports_dir(variant)
    data_out = variant_data_dir(variant)

    start, end = parse_date_range(cfg)
    ext = cfg["extrusion"]
    analysis = cfg.get("analysis", {})
    exclude_weekends = ext.get("exclude_weekends", analysis.get("exclude_weekends_from_baselines", False))

    t0 = datetime.fromisoformat(cfg["data"]["date_range"]["start"]).replace(tzinfo=timezone.utc)
    t1 = datetime.fromisoformat(cfg["data"]["date_range"]["end"]).replace(tzinfo=timezone.utc)

    print(f"[phase0] predictor={variant} ({spec.label})")
    print(f"[phase0] Loading BTCUSDT 15m {start} → {end}")
    bars = load_track(Symbol("binance.spot", "BTCUSDT"), "15m", t0, t1)
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")

    daily_full = build_daily_table(
        bars,
        start,
        end,
        predictor_variant=variant,
        rolling_days=ext["rolling_days"],
        quiet_tertile=ext["quiet_tertile"],
        exclude_weekends=exclude_weekends,
        entry_times_nyc=cfg["counterfactual"]["entry_times_nyc"],
    )
    if daily_full.empty:
        print("[phase0] No slot-A days in range")
        return 1

    daily = filter_for_analysis(daily_full, cfg)
    print(
        f"[phase0] Analysis window: {len(daily)} days "
        f"(full={len(daily_full)}, effective>={analysis.get('effective_start')}, "
        f"warmup={analysis.get('warmup_days', 0)})"
    )

    parquet_path = data_out / "session_extrusion_daily.parquet"
    daily_full.to_parquet(parquet_path, index=False)
    analysis_path = data_out / "session_extrusion_analysis.parquet"
    daily.to_parquet(analysis_path, index=False)
    csv_path = out_dir / "session_extrusion_daily.csv"
    daily.to_csv(csv_path, index=False)
    print(f"[phase0] Wrote {parquet_path} ({len(daily_full)} full, {len(daily)} analysis)")

    contingency = run_contingency_tests(daily, bars, cfg)
    cont_path = out_dir / "contingency_summary.json"
    cont_path.write_text(json.dumps(contingency, indent=2, default=str))
    print(f"[phase0] Wrote {cont_path}")

    grid, cf_summary = run_counterfactual_grid(daily, bars, cfg)
    grid_path = out_dir / "counterfactual_grid.csv"
    grid.to_csv(grid_path, index=False)
    print(f"[phase0] Wrote {grid_path} ({len(grid)} cells)")

    all_passed = (
        contingency["primary_gate"]["passed"]
        and contingency["false_calm"]["passed"]
        and cf_summary.get("contract_reduction_passed", False)
        and cf_summary.get("extrusion_safe_passed", False)
    )

    phase_metrics = {
        "predictor_variant": variant,
        "predictor_label": spec.label,
        "n_days_full": len(daily_full),
        "n_days": contingency["n_days"],
        "n_predictor_quiet": contingency["n_morning_quiet"],
        "analysis_effective_start": analysis.get("effective_start"),
        "analysis_warmup_days": analysis.get("warmup_days"),
        "exclude_weekends": exclude_weekends,
        "primary_lift_passed": contingency["primary_gate"]["passed"],
        "primary_lift": contingency["primary_gate"]["lift"],
        "false_calm_passed": contingency["false_calm"]["passed"],
        "false_calm_rate_pct": contingency["false_calm"]["rate_pct"],
        "contract_reduction_pct": cf_summary.get("contract_reduction_pct"),
        "contract_reduction_passed": cf_summary.get("contract_reduction_passed"),
        "extrusion_safe_passed": cf_summary.get("extrusion_safe_passed"),
        "phase0_all_gates_passed": all_passed,
        "counterfactual": cf_summary,
    }

    phase_path = out_dir / "phase_0_extrusion.json"
    write_phase_summary(
        phase_path,
        phase_id="phase_0_extrusion",
        metrics=phase_metrics,
        artifacts={
            "daily_parquet": str(parquet_path),
            "analysis_parquet": str(analysis_path),
            "daily_csv": str(csv_path),
            "contingency_summary": str(cont_path),
            "counterfactual_grid": str(grid_path),
        },
        status="ok" if all_passed else "review",
        notes=f"Phase 0 complete ({variant}); run run_phase0_qa.py --predictor {variant}",
    )
    print(f"[phase0] Wrote {phase_path}")

    html_path = out_dir / "session_extrusion_report.html"
    render_phase0_report(contingency, cf_summary, out_path=html_path)
    print(f"[phase0] Wrote {html_path}")
    print(f"[phase0] All gates passed: {all_passed}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 0 session extrusion study")
    parser.add_argument(
        "--predictor",
        choices=["us_morning", "london_us"],
        default=None,
        help="Predictor window variant (default: config predictor.default)",
    )
    args = parser.parse_args()
    cfg = load_config()
    variant = resolve_predictor(cfg, args.predictor)
    return run_phase0(variant)


if __name__ == "__main__":
    raise SystemExit(main())
