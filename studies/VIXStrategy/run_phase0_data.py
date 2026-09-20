#!/usr/bin/env python3
"""Phase 0 — refresh CBOE VIX OHLC, QA, write study parquet."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

from cryoquant.data.ingest import run_ingest

from src.paths import ANALYSIS_ROOT, load_config, reports_dir
from src.vix_data import (
    ingest_start,
    load_vix_ohlc,
    parse_window,
    qa_report,
    write_ohlc_parquet,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    cfg = load_config()
    start = ingest_start(cfg)
    window_start, window_end = parse_window(cfg)
    end = cfg["window"].get("end")

    log.info("Phase 0 — ingest CBOE VIX from %s", start.date())
    result = run_ingest(
        ANALYSIS_ROOT / "universe.yaml",
        start=start.strftime("%Y-%m-%d"),
        end=end,
        force=True,
        macro_only=True,
    )
    if result.failed:
        log.error("Ingest failed: %s", result.errors)
        return result.exit_code()

    full = load_vix_ohlc(start, window_end)
    research = full.loc[window_start:window_end]
    path = write_ohlc_parquet(research)
    qa_full = qa_report(full)
    qa_research = qa_report(research)

    report = {
        "ingest": {"ok": result.ok, "failed": result.failed},
        "qa_ingest_window": qa_full,
        "qa_research_window": qa_research,
        "parquet": str(path.relative_to(ANALYSIS_ROOT)),
        "columns": list(research.columns),
    }
    out = reports_dir() / "phase0_data.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info(
        "Research window: %d bars [%s → %s] → %s",
        qa_research["n"],
        qa_research["start"],
        qa_research["end"],
        path,
    )
    log.info("Wrote %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
