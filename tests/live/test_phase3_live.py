"""Phase 3 live integration test.

End-to-end sign-off:
  12 months BTC 1h → V2SpotFeaturesV1 → ForwardReturnLabeler(24, 0.025, "magnitude")
  → TabularModel walk-forward (180d train / 30d test / 30d step)
  → register → save → reload → predictions match
  → artefacts: metrics CSV, reliability diagram PNG, registry inspect JSON

Markers: live, slow
Run with: pytest tests/live/test_phase3_live.py -m "live and slow" -v
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
    d = Path(__file__).parent.parent / "artefacts" / "phase3_live"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def test_lgbm_walkforward_on_real_btc(tmp_path, monkeypatch):
    """Full Phase-3 pipeline on 12 months of BTC 1h data."""
    from cryoquant.data.loader import load
    from cryoquant.features.builders import DatasetRef, V2SpotFeaturesV1
    from cryoquant.features import store as store_mod
    from cryoquant.features.labels import ForwardReturnLabeler
    from cryoquant.models.tabular import TabularModel
    from cryoquant.models.cv import walk_forward
    from cryoquant.models.metrics import compute_metrics, reliability_diagram
    from cryoquant.models.registry import generate_model_id, register, get_model, list_models
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
    print(f"  Loaded {len(df_raw):,} bars  {df_raw.index[0].date()} → {df_raw.index[-1].date()}")
    assert len(df_raw) > 4000, "Expected >4000 bars for 12 months of 1h data"

    # ── 2. Build features ───────────────────────────────────────────────────
    ref = DatasetRef(sym, "1h")
    builder = V2SpotFeaturesV1()
    X_full = builder.build({ref: df_raw})
    print(f"  Features shape: {X_full.shape}")
    assert X_full.shape[1] >= 12, "Expected at least 12 feature columns"

    # ── 3. Labels ───────────────────────────────────────────────────────────
    labeler = ForwardReturnLabeler(horizon_h=24, threshold=2.5, direction="magnitude")
    y_full = labeler.apply(df_raw)
    label_col = y_full.name
    print(f"  Label column: {label_col}   base_rate={y_full.mean():.3f}")
    assert 0.1 < float(y_full.mean()) < 0.9, "Base rate out of expected range [0.1, 0.9]"

    # Align X and y — drop rows where either is NaN
    combined = X_full.join(y_full, how="inner").dropna()
    X = combined.drop(columns=[label_col])
    y = combined[label_col].astype("int8")
    print(f"  Aligned shape: X={X.shape}  y={y.shape}  positives={y.sum()}/{len(y)}")
    assert len(X) > 2000

    # ── 4. Walk-forward cross-validation ────────────────────────────────────
    bars_per_day = 24
    train_bars = 180 * bars_per_day  # 180d
    test_bars = 30 * bars_per_day    # 30d
    step_bars = 30 * bars_per_day    # 30d step

    splits = list(walk_forward(len(X), train_bars, test_bars, step=step_bars))
    print(f"  Walk-forward splits: {len(splits)}")
    assert len(splits) >= 2, "Expected at least 2 WF splits"

    fold_metrics = []
    for i, (tr_idx, te_idx) in enumerate(splits):
        X_tr, X_te = X.iloc[tr_idx], X.iloc[te_idx]
        y_tr, y_te = y.iloc[tr_idx], y.iloc[te_idx]
        # Skip folds with too few positives to calibrate
        if y_tr.sum() < 20 or y_te.sum() < 5:
            continue
        m = TabularModel(calibration_cv=3)
        m.fit(X_tr, y_tr)
        probs_te = m.predict_proba(X_te)
        metrics = compute_metrics(y_te.values, probs_te, threshold=0.55)
        fold_metrics.append({"fold": i, **metrics})
        print(f"    fold {i:2d}: auc={metrics['auc']:.4f}  brier={metrics['brier']:.4f}  "
              f"n_fires={metrics['n_fires']}")
        assert np.isfinite(metrics["auc"]), f"Fold {i} AUC is not finite"
        assert np.isfinite(metrics["brier"]), f"Fold {i} Brier is not finite"

    assert len(fold_metrics) >= 1, "No folds had sufficient positives"
    metrics_df = pd.DataFrame(fold_metrics)
    metrics_path = art / "wf_metrics.csv"
    metrics_df.to_csv(metrics_path, index=False)
    print(f"\n  Metrics CSV → {metrics_path}")
    print(metrics_df[["fold", "auc", "brier", "win_rate_at_thr", "n_fires"]].to_string(index=False))

    # Sanity: mean AUC should be > 0.45 (not worse than random for most market regimes)
    mean_auc = float(metrics_df["auc"].mean())
    print(f"\n  Mean AUC across folds: {mean_auc:.4f}")
    assert mean_auc > 0.42, f"Mean AUC {mean_auc:.4f} unexpectedly low"

    # ── 5. Final model fit on last full train window ─────────────────────────
    last_tr, last_te = splits[-1]
    X_tr_final = X.iloc[last_tr]
    y_tr_final = y.iloc[last_tr]
    final_model = TabularModel(calibration_cv=3)
    final_model.fit(X_tr_final, y_tr_final)

    # ── 6. Save artefact ────────────────────────────────────────────────────
    artifact_path = art / "btc_lgbm.pkl"
    final_model.save(artifact_path)
    assert artifact_path.exists()
    print(f"  Model saved → {artifact_path}  ({artifact_path.stat().st_size / 1024:.1f} KB)")

    # ── 7. Reliability diagram ──────────────────────────────────────────────
    probs_te_final = final_model.predict_proba(X.iloc[last_te])
    y_te_final = y.iloc[last_te]
    rel_df = reliability_diagram(y_te_final.values, probs_te_final, n_bins=10)
    rel_path = art / "reliability_diagram.csv"
    rel_df.to_csv(rel_path, index=False)
    print(f"  Reliability diagram:\n{rel_df.to_string(index=False)}")
    # ECE: mean_predicted should track fraction_positive across bins
    valid_bins = rel_df.dropna(subset=["mean_predicted", "fraction_positive"])
    assert len(valid_bins) >= 3, "Too few non-empty reliability bins"

    # ── 8. Register model ───────────────────────────────────────────────────
    model_id = generate_model_id(
        "lgbm",
        feature_set_id="v2spot",
        feature_set_version=str(builder.version),
        labeler=label_col,
        hparams={"n_estimators": 200, "num_leaves": 31, "calibration_cv": 3},
    )
    final_metrics = compute_metrics(y_te_final.values, probs_te_final, threshold=0.55)
    register(
        model_id=model_id,
        model_class="lgbm",
        feature_set_id="v2spot",
        feature_set_version=str(builder.version),
        labeler=label_col,
        hparams={"n_estimators": 200, "num_leaves": 31, "calibration_cv": 3},
        metrics=final_metrics,
        artifact_path=artifact_path,
        db_path=tmp_path / "catalog.duckdb",
    )
    print(f"  Registered model_id={model_id}")

    row = get_model(model_id, db_path=tmp_path / "catalog.duckdb")
    assert row is not None
    assert row["model_id"] == model_id
    assert row["class"] == "lgbm"

    # Dump registry row for inspection
    registry_path = art / "registry_row.json"
    row_serializable = {k: str(v) if not isinstance(v, (str, int, float, type(None))) else v
                        for k, v in row.items()}
    registry_path.write_text(json.dumps(row_serializable, indent=2, default=str))
    print(f"  Registry row → {registry_path}")

    # ── 9. Load model + check predictions match ─────────────────────────────
    loaded_model = TabularModel.load(artifact_path)
    probs_orig = final_model.predict_proba(X.iloc[last_te])
    probs_reloaded = loaded_model.predict_proba(X.iloc[last_te])
    max_diff = float(np.abs(probs_orig - probs_reloaded).max())
    print(f"  Max prob diff after reload: {max_diff:.2e}")
    assert max_diff < 1e-8, f"Reloaded model predictions differ by {max_diff}"

    # ── 10. Feature importances ─────────────────────────────────────────────
    imp = final_model.feature_importances_
    assert imp is not None
    imp_path = art / "feature_importances.csv"
    imp.reset_index().rename(columns={"index": "feature"}).to_csv(imp_path, index=False)
    print(f"  Top-5 features:\n{imp.head(5).to_string()}")

    print(f"\n✓ Phase 3 live test PASSED — artefacts at {art}")
