#!/usr/bin/env python3
"""Phase 3 — continuous calm index, predictive verification, entry schedule.

Run from CryoQuant repo root:
    python studies/tudysho_calm_nights/run_phase3_continuous_calm.py --predictor us_morning
    python studies/tudysho_calm_nights/run_phase3_continuous_calm.py --predictor london_us
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))
sys.path.insert(0, str(STUDY_DIR / "src"))

from cryocore.instruments import Symbol
from cryoquant.data.resolve import load_track
from cryoquant.reporting import write_phase_summary

from src.calm_index import attach_calm_indices
from src.daily_features import filter_for_analysis, parse_date_range
from src.entry_schedule import EntryWindow, add_entry_schedule, parse_hhmm, run_phase3_verification
from src.paths import load_config, variant_data_dir, variant_reports_dir
from src.predictor import get_predictor_spec, resolve_predictor
from src.report_phase3 import render_phase3_report


def run_phase3(variant: str) -> int:
    cfg = load_config()
    spec = get_predictor_spec(variant, cfg)
    out_dir = variant_reports_dir(variant)
    data_out = variant_data_dir(variant)

    analysis_path = data_out / "session_extrusion_analysis.parquet"
    full_path = data_out / "session_extrusion_daily.parquet"

    if analysis_path.is_file():
        daily = pd.read_parquet(analysis_path)
    elif full_path.is_file():
        daily = filter_for_analysis(pd.read_parquet(full_path), cfg)
    else:
        print(f"[phase3] Run phase 0 first with --predictor {variant}")
        return 2

    ext = cfg["extrusion"]
    daily = attach_calm_indices(daily, window=ext["rolling_days"], min_periods=20)

    ce = cfg.get("continuous_entry", {})
    window = EntryWindow(
        earliest=parse_hhmm(ce.get("earliest_nyc", "12:00")),
        latest=parse_hhmm(ce.get("latest_nyc", "16:00")),
        step_minutes=int(ce.get("step_minutes", 15)),
    )
    daily = add_entry_schedule(daily, window=window)

    start, end = parse_date_range(cfg)
    t0 = datetime.fromisoformat(cfg["data"]["date_range"]["start"]).replace(tzinfo=timezone.utc)
    t1 = datetime.fromisoformat(cfg["data"]["date_range"]["end"]).replace(tzinfo=timezone.utc)
    print(f"[phase3] predictor={variant} ({spec.label})")
    print(f"[phase3] Loading bars {start} → {end}")
    bars = load_track(Symbol("binance.spot", "BTCUSDT"), "15m", t0, t1)
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")

    result = run_phase3_verification(daily, bars, cfg)
    result["predictor_variant"] = variant
    result["predictor_label"] = spec.label

    out_parquet = data_out / "phase3_continuous_calm.parquet"
    daily.to_parquet(out_parquet, index=False)
    schedule_csv = out_dir / "phase3_entry_schedule.csv"
    daily[
        [
            "entry_date",
            "predictor_variant",
            "morning_calm_index",
            "hold_night_calm_index",
            "entry_time_nyc",
            "entry_minutes_nyc",
            "minutes_earlier_than_base",
            "predictor_range_norm",
            "hold_night_range_norm",
        ]
    ].to_csv(schedule_csv, index=False)

    detail_path = out_dir / "phase3_verification.json"
    detail_path.write_text(json.dumps(result, indent=2, default=str))

    summary_path = out_dir / "phase_3_continuous_calm.json"
    write_phase_summary(
        summary_path,
        phase_id="phase_3_continuous_calm",
        metrics={
            "predictor_variant": variant,
            "predictor_label": spec.label,
            "n_days": result["n_days"],
            "spearman_mci_hci": result["predictor"].get("spearman_rho"),
            "permutation_p": result["permutation_test"].get("p_value"),
            "oos_spearman_pred": result["walk_forward_oos"].get("mean_oos_spearman_pred"),
            "oos_mae": result["walk_forward_oos"].get("mean_oos_mae"),
            "gates_passed": result["gates_passed"],
            "entry_window": result["entry_window"],
        },
        artifacts={
            "parquet": str(out_parquet),
            "schedule_csv": str(schedule_csv),
            "verification": str(detail_path),
        },
        status="ok" if result["gates_passed"] else "review",
    )

    html_path = out_dir / "phase3_continuous_calm_report.html"
    render_phase3_report(result, daily, html_path)

    print(f"[phase3] Wrote {out_parquet}, {schedule_csv}, {summary_path}")
    print(f"[phase3] MCI→HCI Spearman: {result['predictor'].get('spearman_rho'):.3f}")
    print(f"[phase3] Gates passed: {result['gates_passed']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 3 continuous calm index")
    parser.add_argument(
        "--predictor",
        choices=["us_morning", "london_us"],
        default=None,
        help="Predictor window variant",
    )
    args = parser.parse_args()
    cfg = load_config()
    variant = resolve_predictor(cfg, args.predictor)
    return run_phase3(variant)


if __name__ == "__main__":
    raise SystemExit(main())
