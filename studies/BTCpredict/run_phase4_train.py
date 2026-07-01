#!/usr/bin/env python3
"""Phase 4 — train models per training.yaml register (Phase 4.5 transparency)."""
from __future__ import annotations

import argparse
import logging
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.paths import data_dir, load_study_config, reports_dir
from src.phase4_report import write_training_report
from src.phase4_train import run_result_to_dict, run_training_run, write_training_manifest
from src.repro_bundle import build_repro_bundle
from src.trial_log import append_training_session, trial_log_path
from src.training_register import list_training_runs

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="BTCpredict Phase 4 training")
    parser.add_argument("--smoke", action="store_true", help="BTC T+1d up_win only (P4-L01)")
    parser.add_argument("--run-id", type=str, default=None, help="Single run_id from training.yaml")
    parser.add_argument("--max-runs", type=int, default=None, help="Limit number of runs")
    args = parser.parse_args()

    cfg = load_study_config()
    if not cfg.phase3_complete:
        log.error("phase3_complete must be true before Phase 4 training")
        return 2
    if cfg.phase4 is None or not cfg.phase4.register_signed_off:
        log.error("phase4.register_signed_off must be true in config.yaml")
        return 2

    runs = list_training_runs()
    if args.smoke:
        runs = [r for r in runs if r.run_id == "smoke_btc_up_h1"]
    elif args.run_id:
        runs = [r for r in runs if r.run_id == args.run_id]
        if not runs:
            log.error("Unknown run_id: %s", args.run_id)
            return 2
    if args.max_runs is not None:
        runs = runs[: args.max_runs]

    session_id = str(uuid.uuid4())[:8]
    repro = build_repro_bundle(cfg)
    log.info("Phase 4 training — %d run(s) session=%s", len(runs), session_id)
    results = []
    oos_parts = []

    for i, run in enumerate(runs, 1):
        log.info("[%d/%d] %s", i, len(runs), run.run_id)
        result, oos_df = run_training_run(cfg, run)
        results.append(result)
        if not oos_df.empty:
            oos_parts.append(oos_df)
        if result.status == "error":
            log.error("Run failed: %s", result.error)
        elif result.status == "empty":
            log.warning("Run empty: %s — %s", run.run_id, result.error)
        else:
            log.info(
                "  OOS rows=%d folds=%d metrics=%s",
                result.n_oos,
                len(result.fold_metrics),
                result.aggregate_metrics,
            )

    manifest_path = data_dir() / "phase4_training_manifest.json"
    write_training_manifest(
        results,
        manifest_path,
        reproducibility=repro,
        session_id=session_id,
    )
    log.info("Wrote %s", manifest_path)

    run_dicts = [run_result_to_dict(r) for r in results]
    tlog = trial_log_path(data_dir())
    append_training_session(
        tlog,
        session_id=session_id,
        phase="phase4",
        runs=run_dicts,
        reproducibility=repro,
    )
    log.info("Appended %d trial(s) to %s", len(run_dicts), tlog)

    report_txt = reports_dir() / "phase4_training_report.txt"
    report_json = data_dir() / "phase4_training_report.json"
    write_training_report(manifest_path, report_txt, report_json)
    log.info("Wrote %s and %s", report_txt, report_json)

    if oos_parts:
        import pandas as pd

        oos_path = data_dir() / "oos_predictions.parquet"
        oos_all = pd.concat(oos_parts, ignore_index=True)
        oos_all.to_parquet(oos_path, index=False)
        log.info("Wrote %s (%d rows)", oos_path, len(oos_all))

    errors = [r for r in results if r.status == "error"]
    if errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
