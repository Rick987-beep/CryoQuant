"""Tests for cryoquant.reporting.phase_summary."""
from __future__ import annotations

import json
from pathlib import Path

from cryoquant.reporting.phase_summary import write_phase_summary


def test_write_phase_summary_shape(tmp_path: Path) -> None:
    out = write_phase_summary(
        tmp_path / "phase_1_ingest.json",
        phase_id="ingest",
        metrics={"n_bars": 1000},
        artifacts={"panel": "data/panel.parquet"},
        status="ok",
        notes="clean panel",
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["phase_id"] == "ingest"
    assert data["status"] == "ok"
    assert data["metrics"]["n_bars"] == 1000
    assert data["artifacts"]["panel"] == "data/panel.parquet"
    assert data["notes"] == "clean panel"
    assert "created_at" in data
