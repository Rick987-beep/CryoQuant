"""End-to-end live sanity run.

   load OHLCV → build features → label → train LightGBM → ProbSignal
   → spot_pnl.simulate → deflated Sharpe → HTML report

Usage:
    python scripts/e2e_live.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── imports ────────────────────────────────────────────────────────────────
from cryocore.instruments import Symbol
from cryoquant.data.loader import load
from cryoquant.features.builders import DatasetRef, SpotFeatures
from cryoquant.features.labels import ForwardReturnLabeler
from cryoquant.models.tabular import TabularModel
from cryoquant.models.cv import walk_forward
from cryoquant.signals.from_model import prob_from_model
from cryoquant.backtest.spot_pnl import simulate
from cryoquant.backtest.robustness import deflated_sharpe
from cryoquant.backtest.reports import render_spot_result

OUT = Path("tests/artefacts/e2e_live")
OUT.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────
# 1. Load data
# ──────────────────────────────────────────────────────────────────────────
print("── 1. Loading data ──────────────────────────────────────────────────")
sym = Symbol("binance.spot", "BTCUSDT")
end = datetime.now(timezone.utc)
start = end - timedelta(days=400)          # ~13 months of 1h bars

df_raw = load(sym, "1h", start, end)
print(f"   Bars loaded: {len(df_raw):,}  "
      f"({df_raw.index[0].date()} → {df_raw.index[-1].date()})")
assert len(df_raw) > 5_000, "Too few bars — data fetch may have failed"

# ──────────────────────────────────────────────────────────────────────────
# 2. Build features
# ──────────────────────────────────────────────────────────────────────────
print("\n── 2. Building features ─────────────────────────────────────────────")
ref = DatasetRef(sym, "1h")
builder = SpotFeatures()
X_full = builder.build({ref: df_raw})
print(f"   Feature matrix: {X_full.shape}")

# Feature-only columns (drop OHLCV passthrough)
ohlcv = {"open", "high", "low", "close", "volume"}
feat_cols = [c for c in X_full.columns if c not in ohlcv]
X_feat = X_full[feat_cols]
print(f"   Feature columns ({len(feat_cols)}): {feat_cols}")

# ──────────────────────────────────────────────────────────────────────────
# 3. Build labels
# ──────────────────────────────────────────────────────────────────────────
print("\n── 3. Labelling ─────────────────────────────────────────────────────")
labeler = ForwardReturnLabeler(horizon_h=24, threshold=2.5, direction="magnitude")
y_full = labeler.apply(df_raw)
base_rate = y_full.mean()
print(f"   Label: {y_full.name}  base-rate={base_rate:.1%}")

# ──────────────────────────────────────────────────────────────────────────
# 4. Align, split, train
# ──────────────────────────────────────────────────────────────────────────
print("\n── 4. Walk-forward split + train ─────────────────────────────────────")
aligned = X_feat.join(y_full).dropna()
X = aligned.drop(columns=[y_full.name])
y = aligned[y_full.name]
print(f"   Aligned rows: {len(X):,}")

n = len(X)
splits = list(walk_forward(n, train_window=180 * 24, test_window=30 * 24, step=30 * 24))
print(f"   Walk-forward splits: {len(splits)}")
assert len(splits) >= 2

# Use the final split for the demo
train_idx, test_idx = splits[-1]
X_tr, y_tr = X.iloc[train_idx], y.iloc[train_idx]
X_te = X.iloc[test_idx]
print(f"   Train: {len(X_tr):,} rows   Test: {len(X_te):,} rows")
print(f"   Train positive rate: {y_tr.mean():.1%}")

model = TabularModel()
model.fit(X_tr, y_tr)
print("   Model fitted.")

# Check feature importances
imps = model.feature_importances_
if imps is not None:
    top5 = imps.sort_values(ascending=False).head(5)
    print(f"   Top-5 feature importances:\n{top5.to_string()}")

# ──────────────────────────────────────────────────────────────────────────
# 5. Wrap as ProbSignal, simulate on test window
# ──────────────────────────────────────────────────────────────────────────
print("\n── 5. Signal + backtest ─────────────────────────────────────────────")
prob_sig = prob_from_model(model, horizon_h=24, default_threshold=0.55,
                           signal_id="btc_lgbm_e2e")

# Enrich bars with features for the test window
bars_te = df_raw.iloc[test_idx].copy()
new_feat_cols = [c for c in X_te.columns if c not in bars_te.columns]
bars_enriched = bars_te.join(X_te[new_feat_cols], how="left")

result = simulate(prob_sig, bars_enriched, thr=0.55, hold_h=24, fee_bps=5.0)
m = result.metrics
print(f"   Trades:        {m['n_trades']}")
print(f"   Total return:  {m['total_return']:.2%}")
print(f"   Win rate:      {m.get('win_rate', float('nan')):.1%}")
print(f"   Sharpe:        {m.get('sharpe', float('nan')):.2f}")
print(f"   Max drawdown:  {m.get('max_drawdown', float('nan')):.2%}")
print(f"   Expectancy:    {m.get('expectancy', float('nan')):.4%}")

# ──────────────────────────────────────────────────────────────────────────
# 6. Robustness — Deflated Sharpe
# ──────────────────────────────────────────────────────────────────────────
print("\n── 6. Deflated Sharpe ───────────────────────────────────────────────")
if m['n_trades'] >= 5 and not (m.get('sharpe') != m.get('sharpe')):   # not nan
    n_trials = len(splits)    # we tried one model per split
    dsr = deflated_sharpe(m['sharpe'], n_trials=max(1, n_trials), n_obs=max(2, m['n_trades']))
    print(f"   DSR: {dsr:.3f}  (>0.95 = credible after {n_trials} trials)")
else:
    dsr = float('nan')
    print("   DSR: n/a (too few trades)")

# ──────────────────────────────────────────────────────────────────────────
# 7. HTML report
# ──────────────────────────────────────────────────────────────────────────
print("\n── 7. HTML report ───────────────────────────────────────────────────")
report_path = OUT / "e2e_report.html"
render_spot_result(result, report_path, signal_info="btc_lgbm_e2e  threshold=0.55  fee=5bps")
print(f"   Written: {report_path}  ({report_path.stat().st_size:,} bytes)")

# ──────────────────────────────────────────────────────────────────────────
# 8. Summary JSON
# ──────────────────────────────────────────────────────────────────────────
summary = {
    "n_bars_total": len(df_raw),
    "n_bars_test":  len(bars_te),
    "n_features":   len(feat_cols),
    "base_rate":    float(base_rate),
    "train_rows":   len(X_tr),
    "test_rows":    len(X_te),
    **{k: (float(v) if v == v else None) for k, v in m.items()},
    "dsr": float(dsr) if dsr == dsr else None,
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2))
print(f"\n── Summary ──────────────────────────────────────────────────────────")
print(json.dumps(summary, indent=2))
print("\n✓  End-to-end live run PASSED")
