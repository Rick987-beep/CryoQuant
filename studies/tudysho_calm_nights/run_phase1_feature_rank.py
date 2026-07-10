#!/usr/bin/env python3
"""Phase 1 — feature ranking on tail days.

Run from CryoQuant repo root:
    python studies/tudysho_calm_nights/run_phase1_feature_rank.py
"""

from __future__ import annotations

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

from src.paths import data_dir, load_config, reports_dir
from src.phase1_features import enrich_daily_features, rank_features


def main() -> int:
    cfg = load_config()
    daily_path = data_dir() / "session_extrusion_analysis.parquet"
    if not daily_path.is_file():
        daily_path = data_dir() / "session_extrusion_daily.parquet"
    if not daily_path.is_file():
        print("[phase1] Run phase 0 first")
        return 2

    daily = pd.read_parquet(daily_path)
    dr = cfg["data"]["date_range"]
    t0 = datetime.fromisoformat(dr["start"]).replace(tzinfo=timezone.utc)
    t1 = datetime.fromisoformat(dr["end"]).replace(tzinfo=timezone.utc)

    print("[phase1] Loading BTC 15m for turbulence...")
    bars = load_track(Symbol("binance.spot", "BTCUSDT"), "15m", t0, t1)
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")

    enriched = enrich_daily_features(daily, bars)
    enriched_path = data_dir() / "phase1_features.parquet"
    enriched.to_parquet(enriched_path, index=False)

    cont_path = reports_dir() / "contingency_summary.json"
    contingency = json.loads(cont_path.read_text()) if cont_path.is_file() else None

    result = rank_features(enriched, contingency)
    rank_path = reports_dir() / "phase_1_feature_rank.json"
    rank_path.write_text(json.dumps(result, indent=2, default=str))

    summary_path = reports_dir() / "phase_1_features.json"
    write_phase_summary(
        summary_path,
        phase_id="phase_1_features",
        metrics={
            "n_tail_days": result["n_tail_days"],
            "incremental_value": result["incremental_value"],
            "recommendation": result["recommendation"],
            "top_feature": result["feature_rankings"][0] if result["feature_rankings"] else None,
        },
        artifacts={
            "enriched_parquet": str(enriched_path),
            "feature_rank": str(rank_path),
        },
        status="ok",
    )

    print(f"[phase1] Wrote {enriched_path}, {rank_path}, {summary_path}")
    print(f"[phase1] Recommendation: {result['recommendation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
