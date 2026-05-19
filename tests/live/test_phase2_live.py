"""Phase 2 live integration test.

Fetches 180d of BTC 1h data from Binance, runs SpotFeatures, loads
30 days of Deribit option chains, computes atm_iv + risk_reversal_25d +
iv_minus_rv, and writes a brief HTML summary and a small PNG.

Markers: live, slow
Run with: pytest tests/live/test_phase2_live.py -m live -v
"""
from __future__ import annotations

import json
from datetime import timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytestmark = [pytest.mark.live, pytest.mark.slow]


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _utcnow():
    from datetime import datetime
    return datetime.now(tz=timezone.utc).replace(second=0, microsecond=0)


def _artefact_dir() -> Path:
    d = Path(__file__).parent.parent / "artefacts" / "phase2_live"
    d.mkdir(parents=True, exist_ok=True)
    return d


# -----------------------------------------------------------------------
# Sign-off test
# -----------------------------------------------------------------------

def test_spot_features_on_real_data(tmp_path, monkeypatch):
    """Fetch 180d BTC 1h, build SpotFeatures, assert no look-ahead."""
    from cryoquant.data.loader import load
    from cryoquant.features.builders import DatasetRef, SpotFeatures
    from cryoquant.features import store as store_mod
    from cryocore.instruments import Symbol

    monkeypatch.setattr(store_mod.config, "FEATURE_STORE_DIR", tmp_path / "features")

    end = _utcnow()
    start = end - timedelta(days=180)

    sym = Symbol("binance.spot", "BTCUSDT")
    df = load(sym, "1h", start, end)

    assert len(df) > 1000, "Expected at least 1000 bars of data"

    ref = DatasetRef(sym, "1h")
    builder = SpotFeatures()
    features = builder.build({ref: df})

    # --- sanity: no forward-looking leak ---
    # Compute with full and half the data; overlap rows must match
    mid = len(df) // 2
    f_cut = builder.build({ref: df.iloc[:mid]})
    overlap = f_cut.index
    price_cols = ["ret_1h", "rv_24h", "bb_width"]
    for col in price_cols:
        pd.testing.assert_series_equal(
            features.loc[overlap, col].rename(None),
            f_cut[col].rename(None),
            check_names=False,
            rtol=1e-6,
        )

    # --- write summary ---
    summary = {
        "rows": len(features),
        "cols": list(features.columns),
        "start": str(features.index.min()),
        "end":   str(features.index.max()),
        "nan_pct": float(features.isna().mean().mean() * 100),
        "rv_24h_mean": float(features["rv_24h"].dropna().mean()),
    }
    out_dir = _artefact_dir()
    (out_dir / "spot_features_summary.json").write_text(json.dumps(summary, indent=2))

    # HTML describe table
    html = features.describe().to_html()
    (out_dir / "features_describe.html").write_text(html)

    print(f"\nSpotFeatures: {summary['rows']} rows, nan_pct={summary['nan_pct']:.1f}%")


def test_options_features_on_real_data():
    """Load 30 Deribit chain days and compute ATM IV, RR25, iv-minus-rv."""
    pytest.importorskip("matplotlib", reason="matplotlib required for PNG output")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    try:
        from cryoquant.data.sources.deribit_options import list_dates, load_chain, load_spot
    except ImportError:
        pytest.skip("deribit_options not importable")

    dates = list_dates()
    if len(dates) < 10:
        pytest.skip("Fewer than 10 chain dates available — skipping options features test")

    dates = sorted(dates)[-30:]

    chains = []
    spot_prices = {}
    for d in dates:
        try:
            df = load_chain(d)
        except Exception:
            continue
        if df is not None and len(df) > 0:
            chains.append((d, df))
        try:
            spot = load_spot(d)
            if spot is not None and len(spot) > 0:
                spot_prices[d] = float(spot["close"].iloc[-1])
        except Exception:
            pass

    if len(chains) < 5:
        pytest.skip("Fewer than 5 chains loaded — skipping")

    from cryoquant.features.options import atm_iv, risk_reversal_25d, iv_minus_rv
    from cryoquant.features.primitives import realised_vol

    atm_iv_s = atm_iv(chains, dte_target=30)
    rr_s     = risk_reversal_25d(chains)

    # Realised vol from spot prices
    if len(spot_prices) >= 10:
        sp_idx = pd.DatetimeIndex(
            [pd.Timestamp(d.year, d.month, d.day, tzinfo=timezone.utc) for d in spot_prices]
        )
        sp_series = pd.Series(list(spot_prices.values()), index=sp_idx, name="close")
        rv_s = realised_vol(sp_series, min(len(sp_series) - 1, 10), annualise_factor=252)
        ivmrv_s = iv_minus_rv(atm_iv_s, rv_s)
    else:
        ivmrv_s = None

    # PNG
    out_dir = _artefact_dir()
    fig, axes = plt.subplots(3 if ivmrv_s is not None else 2, 1, figsize=(10, 8), sharex=True)
    axes[0].plot(atm_iv_s.index, atm_iv_s.values, label="ATM IV 30d")
    axes[0].set_ylabel("ATM IV (%)")
    axes[0].legend()
    axes[1].plot(rr_s.index, rr_s.values, label="RR 25d", color="orange")
    axes[1].set_ylabel("Risk Reversal")
    axes[1].legend()
    if ivmrv_s is not None:
        axes[2].plot(ivmrv_s.index, ivmrv_s.values, label="IV - RV", color="purple")
        axes[2].set_ylabel("IV - RV")
        axes[2].legend()
    fig.tight_layout()
    fig.savefig(out_dir / "iv_minus_rv.png", dpi=120)
    plt.close(fig)

    assert atm_iv_s.dropna().gt(0).any(), "Expected some positive ATM IV values"
    print(f"\nATM IV (mean): {atm_iv_s.dropna().mean():.1f}%")
