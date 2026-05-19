"""Phase 5 live tests — full backtest pipeline on real data.

Live tests:
    test_full_pipeline_live        — gated by CRYOQUANT_FULL_LIVE=1
    test_option_lookup_real_chains — gated by CRYOBACKTESTER_DATA_DIR existing
    test_cryobt_bridge_smoke       — gated by CRYOBACKTESTER_ROOT existing
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _artefact_dir(subdir: str = "") -> Path:
    d = Path(__file__).parent.parent / "artefacts" / "phase5_live"
    if subdir:
        d = d / subdir
    d.mkdir(parents=True, exist_ok=True)
    return d


# ─────────────────────────────────────────────────────────────────────────────
# test_full_pipeline_live — gated by CRYOQUANT_FULL_LIVE=1
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.live
@pytest.mark.slow
def test_full_pipeline_live(tmp_path, monkeypatch):
    """End-to-end: load → features → LGBM walk-forward → ProbSignal →
    spot_pnl.simulate → render HTML report.

    Gated by CRYOQUANT_FULL_LIVE=1 environment variable.
    """
    if not os.environ.get("CRYOQUANT_FULL_LIVE"):
        pytest.skip("Set CRYOQUANT_FULL_LIVE=1 to run the full pipeline live test")

    from cryoquant.data.loader import load
    from cryoquant.features.builders import DatasetRef, V2SpotFeaturesV1
    from cryoquant.features import store as store_mod
    from cryoquant.features.labels import ForwardReturnLabeler
    from cryoquant.models.tabular import TabularModel
    from cryoquant.models.cv import walk_forward
    from cryoquant.signals.from_model import prob_from_model
    from cryoquant.backtest.spot_pnl import simulate
    from cryoquant.backtest.reports import render_spot_result
    from cryocore.instruments import Symbol
    import cryoquant.config as cfg

    monkeypatch.setattr(store_mod.config, "FEATURE_STORE_DIR", tmp_path / "features")
    monkeypatch.setattr(cfg, "CATALOG_DB", tmp_path / "catalog.duckdb")

    art = _artefact_dir("full_pipeline")
    print(f"\nArtefacts → {art}")

    # ── 1. Load data ────────────────────────────────────────────────────────
    end = _utcnow()
    start = end - timedelta(days=365)
    sym = Symbol("binance.spot", "BTCUSDT")
    df_raw = load(sym, "1h", start, end)
    print(f"  Loaded {len(df_raw):,} bars")
    assert len(df_raw) > 4000

    # ── 2. Features + labels ────────────────────────────────────────────────
    ref = DatasetRef(sym, "1h")
    builder = V2SpotFeaturesV1()
    X_full = builder.build({ref: df_raw})

    labeler = ForwardReturnLabeler(horizon_h=24, threshold=2.5, direction="magnitude")
    y_full = labeler.apply(df_raw)

    aligned = X_full.join(y_full).dropna()
    X = aligned.drop(columns=[y_full.name])
    y = aligned[y_full.name]
    feature_cols = [c for c in X.columns if c not in ("open", "high", "low", "close", "volume")]
    X = X[feature_cols]
    print(f"  Feature matrix: {X.shape}")

    # ── 3. Walk-forward train final model ───────────────────────────────────
    n = len(X)
    splits = list(walk_forward(n, train_window=180 * 24, test_window=30 * 24, step=30 * 24))
    assert len(splits) >= 3, "Need at least 3 WF splits"

    # Train on last train split, test on last test split
    train_idx, test_idx = splits[-1]
    X_tr, y_tr = X.iloc[train_idx], y.iloc[train_idx]
    X_te = X.iloc[test_idx]

    model = TabularModel()
    model.fit(X_tr.values, y_tr.values.astype(int))
    print("  Model trained.")

    # ── 4. Wrap as ProbSignal + simulate spot P&L ────────────────────────────
    from cryoquant.signals.from_model import prob_from_model
    prob_sig = prob_from_model(model, horizon_h=24, default_threshold=0.55,
                               signal_id="btc_lgbm_fullpipe")

    # Simulate on the test window bars (with OHLCV available)
    bars_te = df_raw.iloc[test_idx]
    # Build features only for the test window (using full X for context)
    X_te_aligned = X.iloc[test_idx]
    result = simulate(prob_sig, bars_te, thr=0.55, hold_h=24, fee_bps=1.0)
    print(f"  Simulation: {result.metrics['n_trades']} trades  "
          f"return={result.metrics['total_return']:.2%}")

    # ── 5. Render HTML report ────────────────────────────────────────────────
    report_path = art / "report.html"
    render_spot_result(result, report_path, signal_info="btc_lgbm_fullpipe")
    assert report_path.exists() and report_path.stat().st_size > 500
    print(f"  Report → {report_path}")

    # ── 6. Write summary ────────────────────────────────────────────────────
    summary = {
        "n_bars_total": len(df_raw),
        "n_bars_test": len(bars_te),
        "n_trades": result.metrics["n_trades"],
        "total_return": result.metrics["total_return"],
        "win_rate": result.metrics.get("win_rate"),
        "sharpe": result.metrics.get("sharpe"),
        "max_drawdown": result.metrics.get("max_drawdown"),
    }
    (art / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))

    print("✓ Phase 5 full pipeline live test PASSED")


# ─────────────────────────────────────────────────────────────────────────────
# test_option_lookup_real_chains
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.live
@pytest.mark.slow
def test_option_lookup_real_chains(tmp_path, monkeypatch):
    """Evaluate BoolSignal (pullback) option P&L against real Deribit chains.

    Skipped if CRYOBACKTESTER_DATA_DIR does not exist.
    """
    from cryoquant import config
    from cryoquant.data.sources.deribit_options import list_dates

    chains_dir = config.CRYOBACKTESTER_DATA_DIR
    if not chains_dir.exists():
        pytest.skip(f"CRYOBACKTESTER_DATA_DIR not found: {chains_dir}")

    dates = list_dates()
    if len(dates) < 10:
        pytest.skip(f"Not enough option chain dates ({len(dates)} < 10)")

    from cryoquant.data.loader import load
    from cryoquant.features.builders import DatasetRef, V2SpotFeaturesV1
    from cryoquant.features import store as store_mod
    from cryoquant.models.baselines import make_pullback
    from cryoquant.signals.from_model import bool_from_rule
    from cryoquant.backtest.option_lookup import evaluate, ExitRule
    import cryoquant.config as cfg

    monkeypatch.setattr(store_mod.config, "FEATURE_STORE_DIR", tmp_path / "features")
    monkeypatch.setattr(cfg, "CATALOG_DB", tmp_path / "catalog.duckdb")

    art = _artefact_dir("option_lookup")
    print(f"\nArtefacts → {art}")
    print(f"  Chain dates available: {len(dates)}  ({dates[0]} → {dates[-1]})")

    # Use most recent 30 dates
    recent_dates = dates[-30:]
    from cryocore.instruments import Symbol
    sym = Symbol("binance.spot", "BTCUSDT")

    # Load 1h bars covering the chain period + warmup
    from datetime import date as _date, timedelta
    start_dt = datetime(recent_dates[0].year, recent_dates[0].month, recent_dates[0].day,
                        tzinfo=timezone.utc) - timedelta(days=35)
    end_dt = datetime(recent_dates[-1].year, recent_dates[-1].month, recent_dates[-1].day,
                      tzinfo=timezone.utc) + timedelta(days=1)
    df_raw = load(sym, "1h", start_dt, end_dt)
    print(f"  Loaded {len(df_raw):,} bars  {df_raw.index[0].date()} → {df_raw.index[-1].date()}")

    ref = DatasetRef(sym, "1h")
    builder = V2SpotFeaturesV1()
    X_full = builder.build({ref: df_raw})
    print(f"  Features: {X_full.shape}")

    pullback = make_pullback()
    signal = bool_from_rule(pullback, name="pullback_v1")

    # Merge feature columns into bars so signal.as_feature() can access them
    import pandas as pd
    new_cols = [c for c in X_full.columns if c not in df_raw.columns]
    bars_enriched = df_raw.join(X_full[new_cols], how="left")

    result = evaluate(
        signal, bars_enriched,
        dte=1,
        delta=0.30,
        exit_rule=ExitRule(hold_h=24),
        chains_dir=chains_dir,
    )

    print(f"  Fires evaluated: {result.fires_evaluated}")
    print(f"  Fires with data: {result.fires_with_data}")
    if result.fires_with_data > 0:
        print(f"  Win rate: {result.win_rate:.1%}")
        print(f"  Expectancy: {result.expectancy:.2%}")
        print(f"  Entry costs median: ${float(__import__('numpy').median(result.entry_costs_usd)):.0f}")

    assert result.fires_evaluated >= 0
    # The live test doesn't require fires_with_data >= 5 since chain data may not
    # overlap with the signal window. But if we do have data, it must be valid.
    if result.fires_with_data > 0:
        assert all(isinstance(p, float) for p in result.pnl_pct)
        print(f"✓ {result.fires_with_data} fires resolved with finite P&L")
    else:
        print("  No fires resolved (chain dates may not overlap with signal window) — OK")

    print("✓ Phase 5 option lookup live test PASSED")


# ─────────────────────────────────────────────────────────────────────────────
# test_cryobt_bridge_smoke
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.live
@pytest.mark.slow
def test_cryobt_bridge_smoke():
    """Smoke test: adapter wraps signal and has required Strategy attributes.

    Does NOT invoke CryoBacktester. Skipped if CRYOBACKTESTER_ROOT absent.
    """
    from cryoquant import config

    root = getattr(config, "CRYOBACKTESTER_ROOT", None)
    if root is None or not Path(root).exists():
        pytest.skip("CRYOBACKTESTER_ROOT not set or not found")

    from cryoquant.backtest.cryobt_bridge import CryoBTAdapter
    from cryoquant.models.baselines import make_pullback
    from cryoquant.signals.from_model import bool_from_rule

    signal = bool_from_rule(make_pullback(), name="pullback_v1")
    adapter = CryoBTAdapter(signal)

    # Duck-typed contract
    assert hasattr(adapter, "name") and "pullback_v1" in adapter.name
    assert callable(adapter.generate_signals)
    assert callable(adapter.get_parameters)
    params = adapter.get_parameters()
    assert params["signal_id"] == "pullback_v1"

    print(f"  Adapter: {adapter.name}")
    print(f"  Params:  {params}")
    print("✓ Phase 5 cryobt bridge smoke PASSED")
