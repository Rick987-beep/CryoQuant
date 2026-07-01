"""Phase 5 study integration tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.validation_register import load_validation_register


def test_validation_register_loads() -> None:
    reg = load_validation_register()
    assert reg["permutation"]["n_permutations"] == 20
    assert reg["permutation"]["scope"] == "all_runs"
    assert reg["directional"]["null_blocks_phase5"] is False


@pytest.mark.skipif(
    not (ROOT / "data" / "oos_predictions.parquet").is_file(),
    reason="OOS predictions not built",
)
def test_exceedance_overlay_produces_rows() -> None:
    import pandas as pd

    from src.paths import load_study_config
    from src.phase5_calibration import exceedance_calibration_overlay

    cfg = load_study_config()
    oos = pd.read_parquet(ROOT / "data" / "oos_predictions.parquet")
    reg = load_validation_register()
    rows = exceedance_calibration_overlay(cfg, oos, reg)
    assert len(rows) >= 12
