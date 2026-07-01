#!/usr/bin/env python3
"""Phase 1 — ingest CDX.NA.IG, align proxies, build features."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.features import build_features
from src.ingest import build_aligned_panel, ingest_cdx, load_cdx_clean_csv, qa_report
from src.paths import data_dir, reports_dir

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    log.info("Phase 1 — CDX.NA.IG data ingest")
    ingest_cdx(force=True)
    df = load_cdx_clean_csv()
    qa = qa_report(df)
    log.info("QA: %s", qa)

    panel = build_aligned_panel(force_cdx=False)
    features = build_features(panel)
    feat_path = data_dir() / "features_daily.parquet"
    features.to_parquet(feat_path)
    log.info("Features: %d rows × %d cols → %s", *features.shape, feat_path)

    report = {
        "qa": qa,
        "panel_columns": list(panel.columns),
        "feature_columns": list(features.columns),
        "panel_start": str(panel.index.min().date()),
        "panel_end": str(panel.index.max().date()),
    }
    out = reports_dir() / "phase1_data.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("Wrote %s", out)


if __name__ == "__main__":
    main()
