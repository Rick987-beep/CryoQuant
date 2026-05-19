"""Phase 4 live integration test.

End-to-end sign-off:
  - Phase 3 LGBM model wrapped as ProbSignal → emit_history over 12mo BTC
    → assert schema, no NaN probs after warmup, value distribution sensible
  - Pullback BoolSignal → emit_pine → valid Pine v5 stub written to disk
  - CryoTrader adapter callable smoke test
  - pick_threshold verified against live data distribution

Markers: live, slow
Run with: pytest tests/live/test_phase4_live.py -m "live and slow" -v
"""
from __future__ import annotations

import json
from datetime import timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytestmark = [pytest.mark.live, pytest.mark.slow]


def _utcnow():
    from datetime import datetime
    return datetime.now(tz=timezone.utc).replace(second=0, microsecond=0)


def _artefact_dir() -> Path:
    d = Path(__file__).parent.parent / "artefacts" / "phase4_live"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def test_publish_lgbm_probsignal_end_to_end(tmp_path, monkeypatch):
    """Full Phase-4 pipeline on 12 months of BTC 1h data."""
    from cryoquant.data.loader import load
    from cryoquant.features.builders import DatasetRef, V2SpotFeaturesV1
    from cryoquant.features import store as store_mod
    from cryoquant.features.labels import ForwardReturnLabeler
    from cryoquant.models.tabular import TabularModel
    from cryoquant.signals.base import BoolSignal, ProbSignal
    from cryoquant.signals.from_model import bool_from_rule, prob_from_model
    from cryoquant.signals.thresholds import pick_threshold
    from cryoquant.signals.publishers.csv_emitter import emit_history
    from cryoquant.signals.publishers.pine_emitter import emit_pine
    from cryoquant.signals.publishers.cryotrader_adapter import to_cryotrader_condition
    from cryoquant.models.baselines import make_pullback
    from cryocore.instruments import Symbol
    import cryoquant.config as cfg

    monkeypatch.setattr(store_mod.config, "FEATURE_STORE_DIR", tmp_path / "features")
    monkeypatch.setattr(cfg, "CATALOG_DB", tmp_path / "catalog.duckdb")

    art = _artefact_dir()
    print(f"\nArtefacts → {art}")

    # ── 1. Load data ────────────────────────────────────────────────────────
    end = _utcnow()
    start = end - timedelta(days=365)
    sym = Symbol("binance.spot", "BTCUSDT")
    df_raw = load(sym, "1h", start, end)
    print(f"  Loaded {len(df_raw):,} bars")

    # ── 2. Build features ───────────────────────────────────────────────────
    ref = DatasetRef(sym, "1h")
    builder = V2SpotFeaturesV1()
    X_full = builder.build({ref: df_raw})
    print(f"  Features shape: {X_full.shape}")

    # ── 3. Fit LGBM on first 9 months, use last 3 months for signal emission
    split_idx = int(len(X_full) * 0.75)
    labeler = ForwardReturnLabeler(horizon_h=24, threshold=2.5, direction="magnitude")
    y_full = labeler.apply(df_raw)
    label_col = y_full.name

    combined = X_full.join(y_full, how="inner").dropna()
    X = combined.drop(columns=[label_col])
    y = combined[label_col].astype("int8")

    X_tr, X_te = X.iloc[:split_idx], X.iloc[split_idx:]
    y_tr, y_te = y.iloc[:split_idx], y.iloc[split_idx:]
    print(f"  Train: {len(X_tr)} bars  |  Test (signal emission): {len(X_te)} bars")
    assert len(X_te) > 500, "Expected at least 500 test bars"

    lgbm = TabularModel(calibration_cv=3)
    lgbm.fit(X_tr, y_tr)
    print("  LGBM trained.")

    # ── 4a. ProbSignal → emit_history ────────────────────────────────────────
    prob_sig = prob_from_model(
        lgbm,
        horizon_h=24,
        direction="magnitude",
        signal_id="btc_lgbm_mag24",
    )
    prob_path = art / "btc_lgbm_prob_history.parquet"
    emit_history(prob_sig, X_te, prob_path)
    assert prob_path.exists()

    sig_df = pd.read_parquet(prob_path)
    print(f"\n  ProbSignal history shape: {sig_df.shape}")
    print(f"  Columns: {sig_df.columns.tolist()}")
    print(f"  Index name: {sig_df.index.name}")
    print(f"  Prob range: [{sig_df['prob'].min():.4f}, {sig_df['prob'].max():.4f}]")
    print(f"  NaN probs: {sig_df['prob'].isna().sum()}")
    print(f"  value=True: {sig_df['value'].sum()} / {len(sig_df)}")
    print(f"  Sample:\n{sig_df.head(5).to_string()}")

    # Schema assertions
    assert sig_df.index.name == "ts"
    assert "prob" in sig_df.columns
    assert "value" in sig_df.columns
    assert "signal_id" in sig_df.columns
    assert "version" in sig_df.columns
    assert sig_df["prob"].isna().sum() == 0, "ProbSignal history has NaN probs"
    assert float(sig_df["prob"].min()) >= 0.0
    assert float(sig_df["prob"].max()) <= 1.0
    assert (sig_df["signal_id"] == "btc_lgbm_mag24").all()
    n_fires = sig_df["value"].sum()
    fire_rate = n_fires / len(sig_df)
    print(f"\n  Fire rate: {fire_rate:.1%}  ({n_fires} fires / {len(sig_df)} bars)")
    assert 0.01 < fire_rate < 0.99, f"Fire rate {fire_rate:.1%} outside expected range"

    # ── 4b. pick_threshold ──────────────────────────────────────────────────
    y_te_aligned = y_te.reindex(X_te.index)
    probs_te = prob_sig.as_feature(X_te).values
    y_te_vals = y_te_aligned.dropna().values
    probs_te_aligned = probs_te[:len(y_te_vals)]
    thr_prec = pick_threshold(y_te_vals, probs_te_aligned, target="precision", value=0.55)
    thr_f1 = pick_threshold(y_te_vals, probs_te_aligned, target="f1")
    print(f"\n  Threshold for precision>=0.55: {thr_prec:.4f}")
    print(f"  Threshold for max F1:          {thr_f1:.4f}")
    assert 0.0 <= thr_prec <= 1.0
    assert 0.0 <= thr_f1 <= 1.0

    thr_path = art / "thresholds.json"
    thr_path.write_text(json.dumps({"precision_0.55": thr_prec, "f1_max": thr_f1}, indent=2))
    print(f"  Thresholds JSON → {thr_path}")

    # ── 5a. BoolSignal (Pullback) → emit_history ────────────────────────────
    pullback_rule = make_pullback()
    pullback_sig = bool_from_rule(pullback_rule, name="pullback_v1")
    pullback_path = art / "pullback_history.parquet"
    emit_history(pullback_sig, X_te, pullback_path)

    pb_df = pd.read_parquet(pullback_path)
    fire_pct = pb_df["value"].mean()
    print(f"\n  Pullback signal: {fire_pct:.2%} fire rate ({pb_df['value'].sum()} fires)")
    print(f"  Sample:\n{pb_df[pb_df['value']].head(5).to_string()}")
    assert pb_df.index.name == "ts"
    assert "value" in pb_df.columns
    assert pb_df["value"].dtype == bool
    assert 0.0 <= fire_pct <= 1.0

    # ── 5b. Pullback → Pine v5 emitter ─────────────────────────────────────
    pine_str = emit_pine(pullback_sig, name="BTC Pullback Entry (V1)")
    pine_path = art / "pullback_v1.pine"
    pine_path.write_text(pine_str)
    print(f"\n  Pine stub written → {pine_path}")
    print("  Pine snippet (first 12 lines):")
    for line in pine_str.splitlines()[:12]:
        print(f"    {line}")
    assert pine_str.startswith("//@version=5")
    assert pine_str.count("indicator(") == 1
    assert "BTC Pullback Entry (V1)" in pine_str

    # ── 6. CryoTrader adapter ───────────────────────────────────────────────
    from types import SimpleNamespace
    ct_cond = to_cryotrader_condition(prob_sig, threshold=thr_f1)
    # Test on a few feature rows
    n_true = 0
    for i in range(min(50, len(X_te))):
        row = X_te.iloc[i]
        ctx = SimpleNamespace(features=row.to_dict(), timestamp=X_te.index[i])
        result = ct_cond(ctx)
        assert isinstance(result, bool)
        if result:
            n_true += 1
    print(f"\n  CryoTrader adapter: {n_true}/50 bars → True at threshold={thr_f1:.4f}")

    # ── 7. Summary ─────────────────────────────────────────────────────────
    summary = {
        "n_bars_total": len(X_full),
        "n_bars_test": len(X_te),
        "prob_signal_fires": int(n_fires),
        "prob_signal_fire_rate": round(fire_rate, 4),
        "pullback_fires": int(pb_df["value"].sum()),
        "pullback_fire_rate": round(fire_pct, 4),
        "threshold_precision_0.55": round(thr_prec, 4),
        "threshold_f1_max": round(thr_f1, 4),
    }
    summary_path = art / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\n  Summary → {summary_path}")
    print(json.dumps(summary, indent=2))

    print(f"\n✓ Phase 4 live test PASSED — artefacts at {art}")
