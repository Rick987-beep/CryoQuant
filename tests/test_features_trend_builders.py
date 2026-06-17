"""Unit tests for cryoquant.features.trend_builders — Tier-2 trend feature builders."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cryocore.instruments import Symbol
from cryoquant.features.builders import DatasetRef
from cryoquant.features.trend_builders import (
    CrossAssetFeatures,
    MacroFeatures,
    TrendFeatures,
    friday_monday_stress,
    trend_regime,
    vol_expansion,
)


def _ohlcv(n: int = 300, start: str = "2020-01-01", freq: str = "1D") -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 100.0 + rng.standard_normal(n).cumsum()
    close = np.clip(close, 10, None)
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
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


def _macro_series(values: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(values), freq="1D", tz="UTC")
    return pd.DataFrame({"close": values}, index=idx)


class TestTrendFeatures:
    def test_build_returns_expected_columns(self) -> None:
        bars = _ohlcv()
        ref = DatasetRef(Symbol("yahoo", "SPY"), "1d")
        feat = TrendFeatures().build({ref: bars})

        for col in ("ema_20", "donchian_pos_55", "trend_regime", "dow", "rsi_14", "adx_14"):
            assert col in feat.columns, f"Missing column: {col}"
        assert len(feat) == len(bars)

    def test_price_derived_columns_shifted(self) -> None:
        bars = _ohlcv()
        ref = DatasetRef(Symbol("yahoo", "SPY"), "1d")
        feat = TrendFeatures().build({ref: bars})
        # First row should be NaN for shifted price-derived columns
        assert pd.isna(feat["ema_20"].iloc[0])
        assert pd.isna(feat["donchian_pos_55"].iloc[0])

    def test_no_duplicate_rsi_adx_keys(self) -> None:
        bars = _ohlcv()
        ref = DatasetRef(Symbol("yahoo", "SPY"), "1d")
        feat = TrendFeatures().build({ref: bars})
        assert feat.columns.tolist().count("rsi_14") == 1
        assert feat.columns.tolist().count("adx_14") == 1

    def test_requires_1d_ref(self) -> None:
        ref = DatasetRef(Symbol("yahoo", "SPY"), "1h")
        with pytest.raises(ValueError, match="requires a 1d"):
            TrendFeatures().build({ref: _ohlcv()})

    def test_optional_1h_addons(self) -> None:
        bars_1d = _ohlcv(n=200)
        bars_1h = _ohlcv(n=200 * 6, freq="1h")
        ref_1d = DatasetRef(Symbol("yahoo", "SPY"), "1d")
        ref_1h = DatasetRef(Symbol("yahoo", "SPY"), "1h")
        feat = TrendFeatures().build({ref_1d: bars_1d, ref_1h: bars_1h})
        for col in ("close_vs_ema24_1h_pct", "ret_4h", "vol_z_1h"):
            assert col in feat.columns


class TestMacroFeatures:
    def test_vix_columns_when_vix_provided(self) -> None:
        bars = _ohlcv()
        vix = _macro_series([20.0 + i * 0.01 for i in range(len(bars))])
        ref_spy = DatasetRef(Symbol("yahoo", "SPY"), "1d")
        ref_vix = DatasetRef(Symbol("cboe", "VIX"), "1d")
        feat = MacroFeatures().build({ref_spy: bars, ref_vix: vix})
        assert "vix_level" in feat.columns
        assert "vix_z20" in feat.columns
        assert "macro_risk_off" in feat.columns

    def test_missing_macro_refs_only_emits_risk_off_flag(self) -> None:
        bars = _ohlcv()
        ref = DatasetRef(Symbol("yahoo", "SPY"), "1d")
        feat = MacroFeatures().build({ref: bars})
        # macro_risk_off is always emitted; no macro inputs → all zeros
        assert list(feat.columns) == ["macro_risk_off"]
        assert (feat["macro_risk_off"] == 0.0).all()

    def test_requires_non_macro_primary_ref(self) -> None:
        vix = _macro_series([20.0] * 50)
        ref_vix = DatasetRef(Symbol("cboe", "VIX"), "1d")
        with pytest.raises(ValueError, match="non-macro"):
            MacroFeatures().build({ref_vix: vix})


class TestCrossAssetFeatures:
    def test_rs_vs_spy_when_spy_provided(self) -> None:
        xle = _ohlcv()
        spy = _ohlcv()
        ref_xle = DatasetRef(Symbol("yahoo", "XLE"), "1d")
        ref_spy = DatasetRef(Symbol("yahoo", "SPY"), "1d")
        feat = CrossAssetFeatures().build({ref_xle: xle, ref_spy: spy})
        for col in ("rs_vs_spy_20d", "rs_vs_spy_60d", "rs_trend"):
            assert col in feat.columns

    def test_gld_uso_ratio_when_both_provided(self) -> None:
        gld = _ohlcv()
        uso = _ohlcv()
        ref_gld = DatasetRef(Symbol("yahoo", "GLD"), "1d")
        ref_uso = DatasetRef(Symbol("yahoo", "USO"), "1d")
        feat = CrossAssetFeatures().build({ref_gld: gld, ref_uso: uso})
        assert "gld_uso_ratio" in feat.columns

    def test_requires_1d_ref(self) -> None:
        ref = DatasetRef(Symbol("yahoo", "SPY"), "1h")
        with pytest.raises(ValueError, match="1d"):
            CrossAssetFeatures().build({ref: _ohlcv()})


class TestCompositeFunctions:
    def test_trend_regime_values_bounded(self) -> None:
        bars = _ohlcv()
        regime = trend_regime(bars).dropna()
        assert set(regime.unique()) <= {-1.0, 0.0, 1.0}

    def test_vol_expansion_binary(self) -> None:
        bars = _ohlcv()
        flag = vol_expansion(bars).dropna()
        assert set(flag.unique()) <= {0.0, 1.0}

    def test_friday_monday_stress_values_bounded(self) -> None:
        bars = _ohlcv()
        stress = friday_monday_stress(bars).dropna()
        assert set(stress.unique()) <= {-1.0, 0.0}
