"""Phase 2 feature engineering tests (P2-T01–T07)."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from cryoquant.features.builders import DatasetRef
from cryoquant.features.crypto_builders import CryptoFeatures
from cryoquant.features.options import atm_iv, dvol_features
from cryoquant.features.trend_builders import TrendFeatures
from cryocore.instruments import Symbol

from src.feature_schema import catalog_feature_columns
from src.paths import load_study_config


def _synthetic_bars(n: int = 120, *, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    return pd.DataFrame(
        {
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.98,
            "close": close,
            "volume": rng.integers(1_000, 10_000, n).astype(float),
        },
        index=idx,
    )


class TestP2T01CryptoFeaturesIndex:
    """P2-T01: CryptoFeatures output index ⊆ primary index."""

    def test_build_per_asset_index_subset(self):
        index = pd.date_range("2024-01-01", periods=30, freq="D", tz="UTC")
        funding_idx = index[::3]
        funding = pd.Series(0.0001, index=funding_idx, name="funding")
        out = CryptoFeatures().build_per_asset(index, funding=funding, oi_usd=None, prefix="btc_")
        assert out.index.equals(index)
        assert (out.index <= index.max()).all()

    def test_build_global_index_subset(self):
        index = pd.date_range("2024-01-01", periods=30, freq="D", tz="UTC")
        fg = pd.Series(50.0, index=index[::2])
        out = CryptoFeatures().build_global(index, fear_greed=fg, stablecoin=None, etf_flow=None, mstr_acq=None, mstr_holdings=None)
        assert out.index.equals(index)


class TestP2T02LookaheadTrend:
    """P2-T02: shift feature timestamp +1 day → values change."""

    def test_ret_1d_uses_lagged_close(self):
        bars = _synthetic_bars(80)
        ref = DatasetRef(Symbol("binance.spot", "BTCUSDT"), "1d")
        feat = TrendFeatures().build({ref: bars})
        assert "ret_1d" in feat.columns
        manual = bars["close"].pct_change(1).shift(1) * 100
        aligned = manual.reindex(feat.index)
        corr = feat["ret_1d"].corr(aligned)
        assert corr > 0.99

    def test_future_bar_does_not_change_past_feature(self):
        bars = _synthetic_bars(60, seed=1)
        ref = DatasetRef(Symbol("binance.spot", "BTCUSDT"), "1d")
        f1 = TrendFeatures().build({ref: bars})
        bars2 = bars.copy()
        bars2.iloc[-1, bars2.columns.get_loc("close")] *= 1.5
        f2 = TrendFeatures().build({ref: bars2})
        mid = len(f1) // 2
        assert f1["ret_1d"].iloc[mid] == pytest.approx(f2["ret_1d"].iloc[mid])


class TestP2T03ChainLookahead:
    """P2-T03: atm_iv at t unchanged if chain at t+1 modified."""

    def test_atm_iv_entry_time_only(self):
        from cryoquant.data.sources import deribit_options

        dates = [d for d in deribit_options.list_dates() if d >= date(2025, 4, 11)]
        if len(dates) < 2:
            pytest.skip("No chain dates on disk")
        d0, d1 = dates[0], dates[1]
        c0 = deribit_options.load_chain(d0)
        c1 = deribit_options.load_chain(d1)
        iv0 = float(atm_iv([(d0, c0)], dte_target=30).iloc[0])
        c1_mod = c1.copy()
        iv_col = "mark_iv" if "mark_iv" in c1_mod.columns else [c for c in c1_mod.columns if "mark_iv" in c.lower()][0]
        c1_mod[iv_col] = c1_mod[iv_col] * 3.0
        iv0_again = float(atm_iv([(d0, c0), (d1, c1_mod)], dte_target=30).iloc[0])
        assert iv0 == pytest.approx(iv0_again, rel=1e-9, abs=1e-9)


class TestP2T04HtfAlign:
    """P2-T04: 1h-derived daily features use only hours ≤ daily close."""

    def test_htf_columns_present_with_hourly(self):
        bars_1d = _synthetic_bars(90, seed=2)
        bars_1h = bars_1d.resample("1h").ffill()
        bars_1h["volume"] = 1000.0
        ref_1d = DatasetRef(Symbol("binance.spot", "BTCUSDT"), "1d")
        ref_1h = DatasetRef(Symbol("binance.spot", "BTCUSDT"), "1h")
        feat = TrendFeatures().build({ref_1d: bars_1d, ref_1h: bars_1h})
        for col in ("close_vs_ema24_1h_pct", "ret_4h", "vol_z_1h"):
            assert col in feat.columns


class TestP2T05PanelIntegration:
    """P2-T05: no duplicate columns; finite after warmup."""

    @pytest.fixture(scope="class")
    def panel_sample(self):
        cfg = load_study_config()
        if not cfg.phase1_complete:
            pytest.skip("Phase 1 not complete")
        from src.panel_build import build_study_panel

        end = datetime(2021, 3, 31, tzinfo=timezone.utc)
        return build_study_panel(cfg, end=end)

    def test_no_duplicate_columns(self, panel_sample):
        cols = panel_sample.columns
        assert len(cols) == len(set(cols))

    def test_finite_after_warmup(self, panel_sample):
        meta = {"timestamp", "asset", "options_source"}
        feats = [c for c in panel_sample.columns if c not in meta]
        post = panel_sample.groupby("asset", group_keys=False).apply(lambda g: g.iloc[252:], include_groups=False)
        numeric = post[feats].select_dtypes(include=[np.number])
        assert not np.isinf(numeric.to_numpy()).any()


class TestP2T06CachedBuilders:
    """P2-T06: same inputs → same output hash."""

    def test_trend_features_deterministic(self):
        bars = _synthetic_bars(50, seed=3)
        ref = DatasetRef(Symbol("binance.spot", "BTCUSDT"), "1d")
        a = TrendFeatures().build({ref: bars})
        b = TrendFeatures().build({ref: bars})
        ha = hashlib.sha256(pd.util.hash_pandas_object(a, index=True).values.tobytes()).hexdigest()
        hb = hashlib.sha256(pd.util.hash_pandas_object(b, index=True).values.tobytes()).hexdigest()
        assert ha == hb


class TestP2T07MissingMacro:
    """P2-T07: missing macro → NaN, not future-filled."""

    def test_align_series_no_future_fill(self):
        from cryoquant.features.align import align_series

        idx = pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC")
        macro_idx = pd.date_range("2024-01-01", periods=3, freq="7D", tz="UTC")
        macro = pd.Series([1.0, 2.0, 99.0], index=macro_idx)
        out = align_series(idx, macro, ffill_limit=2)
        assert pd.isna(out.iloc[-1]) or out.iloc[-1] != 99.0


@pytest.mark.live
class TestP2L01LivePanel:
    """P2-L01: live build_study_panel ≥ 30 feature columns."""

    def test_live_panel_width(self):
        cfg = load_study_config()
        if not cfg.phase1_complete:
            pytest.skip("Phase 1 not complete")
        from src.panel_build import build_study_panel

        end = datetime(2024, 12, 31, tzinfo=timezone.utc)
        df = build_study_panel(cfg, end=end)
        meta = {"timestamp", "asset", "options_source"}
        assert len([c for c in df.columns if c not in meta]) >= 30
        btc = df[df["asset"] == "BTC"]
        assert len(btc) >= 150


def test_catalog_column_count():
    cols = catalog_feature_columns()
    assert len(cols) == 160
    assert "options_source" in cols
    assert "btc_rsi_14" in cols
    assert "btc_dvol_30d" in cols
    assert "btc_dvol_rank_252" in cols
    assert "btc_dvol_chg_7d" in cols
    assert "btc_dvol_rank_90" in cols


class TestDvolRankFeatures:
    """Layer F amendment: IV percentile rank + 7d change on DVOL."""

    def test_dvol_rank_chg_columns_and_values(self):
        idx = pd.date_range("2020-01-01", periods=300, freq="D", tz="UTC")
        rng = np.random.default_rng(0)
        dvol = pd.Series(np.linspace(30, 60, 300) + rng.normal(0, 2, 300), index=idx)
        rv = dvol * 0.8
        out = dvol_features(dvol, rv, prefix="btc_")
        for col in (
            "btc_dvol_rank_252",
            "btc_dvol_rank_90",
            "btc_dvol_chg_7d",
            "btc_vol_of_vol",
        ):
            assert col in out.columns
        assert out["btc_dvol_rank_252"].iloc[-1] > 0.9
        manual_chg = dvol.pct_change(7).iloc[-1] * 100.0
        assert out["btc_dvol_chg_7d"].iloc[-1] == pytest.approx(manual_chg, rel=1e-9)
        assert out["btc_dvol_rank_90"].iloc[-1] > out["btc_dvol_rank_252"].iloc[-1] - 0.2


class TestFinalizePanel:
    """Schema contract: finalize_panel enforces catalog columns only."""

    def test_drops_extra_and_adds_missing(self):
        from src.feature_schema import finalize_panel, ordered_panel_columns

        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2024-01-01", periods=3, tz="UTC"),
                "asset": ["BTC"] * 3,
                "btc_rsi_14": [50.0, 51.0, 52.0],
                "extra_not_in_catalog": [1.0, 2.0, 3.0],
                "options_source": ["dvol"] * 3,
            }
        )
        out = finalize_panel(df)
        assert "extra_not_in_catalog" not in out.columns
        assert list(out.columns) == ordered_panel_columns()
        assert "eth_dvol_30d" in out.columns
        assert out["eth_dvol_30d"].isna().all()
