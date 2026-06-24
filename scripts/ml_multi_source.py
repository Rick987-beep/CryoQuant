#!/usr/bin/env python3
"""Path C example — multi-source ML indicator.

Demonstrates DataPanel, composed feature builders, walk-forward fit, and
ProbSignal backtest.  Uses synthetic data when macro_store is empty so the
script always runs offline; swap ``_build_synthetic_panel`` for
``DataPanel.from_loads`` with real symbols when data is ingested.

Usage:
    python scripts/ml_multi_source.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone

from cryocore.instruments import Symbol
from cryoquant.backtest.spot_pnl import simulate
from cryoquant.features.align import join_features
from cryoquant.features.builders import DatasetRef
from cryoquant.features.labels import ForwardReturnLabeler
from cryoquant.features.panel import DataPanel
from cryoquant.features.trend_builders import MacroFeatures, TrendFeatures
from cryoquant.models.fit_loop import concat_oos_probs, walk_forward_fit
from cryoquant.models.tabular import TabularModel
from cryoquant.signals.from_model import prob_from_model


def _synthetic_bars(n: int = 600, start: str = "2020-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(7)
    idx = pd.date_range(start, periods=n, freq="1D", tz="UTC")
    close = 100.0 + rng.standard_normal(n).cumsum()
    close = np.clip(close, 20, None)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": rng.uniform(1e6, 2e6, n),
        },
        index=idx,
    )


def _build_synthetic_panel() -> DataPanel:
    """Offline demo panel — replace with DataPanel.from_loads for production."""
    bars = _synthetic_bars()
    vix = pd.DataFrame({"close": 18.0 + np.linspace(0, 5, len(bars))}, index=bars.index)
    ref_spy = DatasetRef(Symbol("yahoo", "SPY"), "1d")
    ref_vix = DatasetRef(Symbol("cboe", "VIX"), "1d")
    return DataPanel(
        primary_ref=ref_spy,
        primary=bars,
        tracks={"vix": vix},
        track_refs={"vix": ref_vix},
    )


def main() -> int:
    print("── Path C: multi-source ML indicator (synthetic demo) ─────────────────")

    panel = _build_synthetic_panel()
    frames = panel.to_frames()

    trend = TrendFeatures().build({panel.primary_ref: panel.primary})
    macro = MacroFeatures().build(frames)
    features = join_features(trend, macro)

    bars = panel.with_features(features)
    labeler = ForwardReturnLabeler(horizon_h=5, threshold=1.5, direction="magnitude")
    y = labeler.apply(bars)

    feature_cols = list(features.columns)
    X = bars[feature_cols]
    mask = y.notna()
    X, y = X.loc[mask], y.loc[mask].astype(bool)

    results = walk_forward_fit(
        lambda: TabularModel(calibration_cv=3),
        X,
        y,
        train_window_bars=250,
        test_window_bars=60,
        step_bars=60,
        embargo_bars=5,
    )
    print(f"   walk-forward folds: {len(results)}")
    if results:
        print(f"   last-fold AUC: {results[-1].metrics.get('auc', float('nan')):.3f}")

    oos = concat_oos_probs(results)
    if oos.empty:
        print("   no OOS probs — skipping backtest")
        return 0

    if len(y) >= 80 and y.nunique() >= 2:
        model = TabularModel(calibration_cv=3)
        model.fit(X, y)
        signal = prob_from_model(model, horizon_h=5, default_threshold=0.55)
        bt = simulate(signal, bars, thr=0.55, hold_h=5, fee_bps=5.0)
        print(f"   backtest trades: {bt.metrics.get('n_trades', 0)}  "
              f"sharpe: {bt.metrics.get('sharpe', float('nan')):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
