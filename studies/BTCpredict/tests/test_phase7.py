"""Phase 7 hold-out tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.holdout_register import load_holdout_register
from src.paths import load_study_config
from src.phase7_qa import HoldoutAlreadyTouchedError, check_one_shot


def test_holdout_register_loads() -> None:
    reg = load_holdout_register()
    assert reg["sweep"]["mode"] == "report_all"
    assert reg["sweep"]["selection_on_holdout"] is False
    assert reg["gates"]["tier_primary"]["G2"] == "calibration_gap_gt_0_or_ece_lt_0.05"


def test_holdout_inference_fit_slice() -> None:
    """P7-T01: fit uses only dev; predict rows are hold-out."""
    from src.config_models import AssetId, HorizonId, ModelHeadId
    from src.phase7_inference import fit_predict_holdout_run
    from src.training_register import TrainingRun

    cfg = load_study_config()
    run = TrainingRun(
        run_id="realized_vol_btc_h1",
        head=ModelHeadId.REALIZED_VOL,
        asset=AssetId.BTC,
        horizon_id=HorizonId.H1,
        label_base="fwd_rv",
        label_name="fwd_rv_h1",
        task="regression",
    )
    rows, meta = fit_predict_holdout_run(cfg, run)
    if meta.get("status") != "ok":
        pytest.skip(f"inference not ok: {meta}")
    holdout = pd.Timestamp(cfg.splits.holdout_start, tz="UTC")
    for r in rows:
        ts = pd.Timestamp(r["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        assert ts >= holdout
    assert meta["n_train"] > 0


@pytest.mark.skipif(
    not (ROOT / "data" / "features.parquet").is_file(),
    reason="features not built",
)
def test_holdout_smoke_inference_writes_parquet(tmp_path: Path) -> None:
    from src.phase7_inference import run_holdout_inference

    cfg = load_study_config()
    df, meta = run_holdout_inference(cfg, data_dir=tmp_path, smoke=True)
    if df.empty:
        pytest.skip("smoke inference produced no rows")
    holdout = pd.Timestamp(cfg.splits.holdout_start, tz="UTC")
    assert (df["timestamp"] >= holdout).all()
    assert len(meta) == 3
    assert (tmp_path / "holdout_predictions.parquet").is_file()


def test_one_shot_guard_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    g = tmp_path / "phase7_holdout_touched.json"
    g.write_text('{"touched_at": "2026-01-01"}')
    reg = load_holdout_register()

    import src.phase7_qa as qa_mod

    monkeypatch.setattr(qa_mod, "guard_path", lambda _d, _r=None: g)
    with pytest.raises(HoldoutAlreadyTouchedError):
        check_one_shot(tmp_path, force=False)


def test_chain_eval_effective_start() -> None:
    from src.phase7_holdout import _effective_start

    cfg = load_study_config()
    reg = load_holdout_register()
    eff = _effective_start(reg, cfg)
    assert eff >= pd.Timestamp("2025-04-11", tz="UTC")


def test_naive_seller_signal_fires() -> None:
    from src.phase7_holdout import _always_fire_signal

    idx = pd.date_range("2025-04-15", periods=5, freq="D", tz="UTC")
    bars = pd.DataFrame({"close": [100.0] * 5}, index=idx)
    sig = _always_fire_signal("test")
    assert sig.as_feature(bars).all()


def test_physical_vs_delta_finite_synthetic() -> None:
    from cryoquant.backtest.short_vol_metrics import calibration_gap, otm_rate_vs_delta

    realized = np.array([True, True, False, True])
    implied = 1.0 - 0.15
    stats = otm_rate_vs_delta(realized.astype(float), np.full(4, implied))
    gap = calibration_gap(stats["realized_otm_rate"], 0.15)
    assert np.isfinite(gap)


def test_report_all_no_best_config() -> None:
    report_path = ROOT / "data" / "phase7_holdout_report.json"
    if not report_path.is_file():
        pytest.skip("phase7 not run yet")
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert "best_config" not in payload


def test_results_md_sections() -> None:
    report_path = ROOT / "reports" / "RESULTS.md"
    if not report_path.is_file():
        pytest.skip("RESULTS.md not written yet")
    text = report_path.read_text(encoding="utf-8")
    for section in ("Dev recap", "Hold-out inference", "Chain window", "Physical P(OTM)"):
        assert section in text
