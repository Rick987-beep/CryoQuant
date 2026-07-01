"""Phase 6 study integration tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest_register import load_backtest_register
from src.config_models import StudyConfig
from src.option_policy import compose_short_vol_signal, resolve_tilt, zero_vol_edge_signals
from src.paths import load_study_config


def test_backtest_register_loads() -> None:
    reg = load_backtest_register()
    assert reg["chain"]["backtest_on_dev"] is False
    assert reg["assets"]["promotion"] == "BTC"
    assert "model_tilted" in reg["signal"]["tilt"]["modes"]


def test_tilt_call_heavy() -> None:
    from src.config_models import OptionBookSpec, OptionStructure, AssetId

    cfg = OptionBookSpec(
        underlyings=[AssetId.BTC],
        target_deltas=[0.1, 0.15, 0.2],
        wing_delta_offsets=[0.05, 0.1],
        structures=[OptionStructure.CREDIT_SPREAD, OptionStructure.STRANGLE],
        default_structure=OptionStructure.CREDIT_SPREAD,
        tilt_threshold=0.55,
        min_physical_edge=0.02,
    )
    assert resolve_tilt(0.9, cfg, tilt_mode="model_tilted") == "call_heavy"
    assert resolve_tilt(0.4, cfg, tilt_mode="model_tilted") == "put_heavy"
    assert resolve_tilt(0.5, cfg, tilt_mode="symmetric") == "symmetric"


@pytest.mark.skipif(
    not (ROOT / "data" / "oos_predictions.parquet").is_file(),
    reason="OOS predictions not built",
)
def test_signal_compose_dev_no_holdout() -> None:
    import pandas as pd

    from src.signal_compose import build_horizon_signals

    cfg = load_study_config()
    reg = load_backtest_register()
    sig = build_horizon_signals(cfg, reg, asset="BTC", horizon_id="T+1d")
    holdout = pd.Timestamp(cfg.splits.holdout_start, tz="UTC")
    assert sig.index.max() < holdout
    assert "vol_edge" in sig.columns


@pytest.mark.skipif(
    not (ROOT / "data" / "oos_predictions.parquet").is_file(),
    reason="OOS predictions not built",
)
def test_zero_vol_edge_no_fires() -> None:
    from src.signal_compose import build_horizon_signals

    cfg = load_study_config()
    reg = load_backtest_register()
    sig = build_horizon_signals(cfg, reg, asset="BTC", horizon_id="T+1d")
    pol = zero_vol_edge_signals(sig, cfg.option_book)
    assert not pol["fire"].any()


@pytest.mark.skipif(
    not (ROOT / "data" / "oos_predictions.parquet").is_file(),
    reason="OOS predictions not built",
)
def test_proxy_backtest_runs() -> None:
    from src.phase6_proxy import run_naive_vrp_baseline, run_vrp_proxy
    from src.signal_compose import build_horizon_signals
    from src.option_policy import compose_short_vol_signal

    cfg = load_study_config()
    reg = load_backtest_register()
    sig = build_horizon_signals(cfg, reg, asset="BTC", horizon_id="T+1d")
    policy = compose_short_vol_signal(sig, cfg.option_book, vrp_threshold=0.0, min_physical_edge=0.0)
    naive = run_naive_vrp_baseline(sig, cfg, asset="BTC", horizon_id="T+1d")
    model = run_vrp_proxy(policy, cfg, asset="BTC", horizon_id="T+1d", run_id="test")
    assert naive.n_trades > 0
    assert model.n_trades >= 0
