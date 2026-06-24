"""Trend-following feature builders — Tier-2 FeatureBuilders.

Three builders:

    TrendFeatures       — per-instrument technical features for trend research.
    MacroFeatures       — FRED/CBOE macro regime features aligned to a price index.
    CrossAssetFeatures  — relative-strength and cross-instrument ratio features.

Plus standalone composite feature functions used by the builders:

    trend_regime(df)          — +1 / 0 / −1 ADX + EMA-stack composite
    vol_expansion(df)         — volatility-expansion flag
    friday_monday_stress(df)  — weekly stress pattern (equity/ETF)

All builders follow the FeatureBuilder protocol from
``cryoquant.features.builders``:

    class MyBuilder:
        id: str
        version: str
        def build(self, frames: dict[DatasetRef, pd.DataFrame]) -> pd.DataFrame: ...

Usage::

    from cryoquant.features.builders import DatasetRef
    from cryocore.instruments import Symbol

    sym   = Symbol("yahoo", "SPY")
    ref1d = DatasetRef(sym, "1d")
    ref1h = DatasetRef(sym, "1h")

    trend = TrendFeatures().build({ref1d: bars_1d})
    trend_htf = TrendFeatures().build({ref1d: bars_1d, ref1h: bars_1h})

    ref_vix = DatasetRef(Symbol("cboe",  "VIX"),    "1d")
    ref_yc  = DatasetRef(Symbol("fred",  "T10Y2Y"), "1d")
    macro = MacroFeatures().build({ref1d: bars_1d, ref_vix: vix_df, ref_yc: yc_df})

    ref_spy = DatasetRef(Symbol("yahoo", "SPY"), "1d")
    cross = CrossAssetFeatures().build({ref1d: xle_1d, ref_spy: spy_1d})
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

import cryoquant.features.primitives as P
from cryoquant.features.builders import DatasetRef
from cryoquant.features.calendar_features import dow, is_us_holiday, is_us_session
from cryoquant.features.store import cached

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Venue tags used to identify macro refs vs price refs in frames dicts
_MACRO_VENUES: frozenset[str] = frozenset({"fred", "cboe"})

# Tickers that act as benchmarks / overlays rather than primary instruments
_BENCHMARK_TICKERS: frozenset[str] = frozenset({"SPY", "GLD", "USO"})

# Macro tickers routed via _get_macro_series
_MACRO_TICKERS: frozenset[str] = frozenset({
    "VIX", "T10Y2Y", "DGS10", "BAMLH0A0HYM2", "DFF", "CPIAUCSL", "DX-Y.NYB",
})

# Max forward-fill horizon for monthly macro series (35 calendar days)
_MACRO_FFILL_LIMIT: int = 35


# ===========================================================================
# Composite / contextual feature functions
# ===========================================================================

def friday_monday_stress(
    df: pd.DataFrame,
    drop_threshold_atr_mult: float = 1.5,
) -> pd.Series:
    """ATR-normalised Friday drop + Monday bad open → −1, otherwise 0.

    Fires on Mondays that follow a Friday with an above-average ATR-
    normalised close-to-close drop.  The caller's ``build()`` applies
    the final ``shift(1)`` before including this in a feature matrix.

    Returns a Series with values in {−1, 0}.
    """
    close = df["close"]
    open_ = df["open"]
    atr_norm = P.atr(df, 14) / close.replace(0, np.nan)
    daily_ret_atr = close.pct_change() / atr_norm

    is_friday = pd.Series(df.index.dayofweek == 4, index=df.index)
    is_monday = pd.Series(df.index.dayofweek == 0, index=df.index)

    big_friday_drop = is_friday & (daily_ret_atr < -drop_threshold_atr_mult)
    # Rolling 3 bars catches the Friday even when the weekend gap pushes it back
    had_big_friday_drop = big_friday_drop.rolling(3, min_periods=1).max().astype(bool)
    monday_bad_open = is_monday & (open_ < close.shift(1))

    result = pd.Series(0.0, index=df.index)
    result[monday_bad_open & had_big_friday_drop] = -1.0
    return result


def trend_regime(df: pd.DataFrame) -> pd.Series:
    """Composite trend-regime score: +1 / 0 / −1.

    +1: ADX > 25, EMA stack aligned (20 > 50 > 200), Donchian position > 0.7.
    −1: ADX > 25, EMA stack inverted (20 < 50 < 200), Donchian position < 0.3.
    0:  choppy / ambiguous.
    """
    close   = df["close"]
    ema_20  = P.ema(close, 20)
    ema_50  = P.ema(close, 50)
    ema_200 = P.ema(close, 200)
    adx_val = P.adx(df, 14)
    dc      = P.donchian(close, 55)
    dc_range = (dc["upper"] - dc["lower"]).replace(0, np.nan)
    dc_pos   = (close - dc["lower"]) / dc_range

    trending = adx_val > 25
    bullish  = trending & (ema_20 > ema_50) & (ema_50 > ema_200) & (dc_pos > 0.7)
    bearish  = trending & (ema_20 < ema_50) & (ema_50 < ema_200) & (dc_pos < 0.3)

    result = pd.Series(0.0, index=df.index)
    result[bullish] = 1.0
    result[bearish] = -1.0
    return result


def vol_expansion(df: pd.DataFrame, mult: float = 1.5) -> pd.Series:
    """Volatility-expansion flag: 1 when current ATR% > mult × 20-bar mean ATR%.

    Above-average range often precedes breakouts.
    """
    atr_pct = P.atr_pct(df, 14)
    rolling_mean = atr_pct.rolling(20, min_periods=10).mean()
    return (atr_pct > mult * rolling_mean).astype(float).rename("vol_expansion")


# ===========================================================================
# TrendFeatures
# ===========================================================================

class TrendFeatures:
    """Per-instrument technical feature set for trend-following research.

    Outputs two groups (both shifted +1 bar for closed-bar safety):

    **Group A — rule-ready:** raw indicator values and boolean cross/state
    columns suitable for use in Tier A/B BoolSignal conditions.

    **Group B — ML-ready:** bounded and scale-invariant normalized forms
    suitable for Tier C TabularModel inputs.

    Also includes composite features and calendar columns.

    Optionally accepts a 1h frame alongside the required 1d frame to add
    higher-timeframe momentum and volume columns.

    Usage::

        ref_1d = DatasetRef(Symbol("yahoo", "SPY"), "1d")
        feat   = TrendFeatures().build({ref_1d: bars_1d})

        # With hourly add-ons:
        ref_1h = DatasetRef(Symbol("yahoo", "SPY"), "1h")
        feat   = TrendFeatures().build({ref_1d: bars_1d, ref_1h: bars_1h})
    """

    id = "trend_features"
    version = "1"

    @cached
    def build(self, frames: dict[DatasetRef, pd.DataFrame]) -> pd.DataFrame:
        ref_1d = _find_ref(frames, tf="1d")
        ref_1h = _find_ref(frames, tf="1h")

        if ref_1d is None:
            raise ValueError("TrendFeatures requires a 1d DatasetRef in frames")

        df1d = frames[ref_1d]
        df1h = frames[ref_1h] if ref_1h is not None else None
        return _compute_trend_features(df1d, df1h)


def _find_ref(
    frames: dict[DatasetRef, pd.DataFrame],
    tf: str,
) -> DatasetRef | None:
    """Return the first DatasetRef with the given timeframe, or None."""
    for ref in frames:
        if ref.tf == tf:
            return ref
    return None


def _compute_trend_features(
    df1d: pd.DataFrame,
    df1h: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Pure computation — separated from build() for testability."""
    close  = df1d["close"]
    volume = df1d["volume"]

    # ------------------------------------------------------------------
    # Shared intermediates (used by both groups; not emitted directly)
    # ------------------------------------------------------------------
    ema_20   = P.ema(close, 20)
    ema_50   = P.ema(close, 50)
    ema_100  = P.ema(close, 100)
    ema_200  = P.ema(close, 200)
    atr_pct_14 = P.atr_pct(df1d, 14)
    dc_55    = P.donchian(close, 55)
    dc_20    = P.donchian(close, 20)
    bb_bands = P.bb(close, 20, 2.0)
    rsi_14   = P.rsi(close, 14)
    adx_14   = P.adx(df1d, 14)

    # ------------------------------------------------------------------
    # Group A — rule-ready (shifted +1 bar)
    # ------------------------------------------------------------------
    cross_up_20_50 = (ema_20 > ema_50) & (ema_20.shift(1) <= ema_50.shift(1))
    cross_dn_20_50 = (ema_20 < ema_50) & (ema_20.shift(1) >= ema_50.shift(1))
    ema_stack      = (ema_20 > ema_50) & (ema_50 > ema_200)
    macd_df        = P.macd(close)
    st             = P.supertrend(df1d, 10, 3.0)
    high_52w_pct   = (close / close.rolling(252, min_periods=50).max() - 1) * 100

    # rsi_14 and adx_14 appear in Group A for rule-signal use and in Group B
    # for ML use.  They are emitted once in the merged output (Group B wins
    # in the merge, but the values are identical).
    group_a: dict[str, pd.Series] = {
        "ema_20":             ema_20,
        "ema_50":             ema_50,
        "ema_100":            ema_100,
        "ema_200":            ema_200,
        "ema_cross_up_20_50": cross_up_20_50.astype(float),
        "ema_cross_dn_20_50": cross_dn_20_50.astype(float),
        "ema_stack_aligned":  ema_stack.astype(float),
        "donchian_hi_55":     dc_55["upper"],
        "donchian_lo_55":     dc_55["lower"],
        "donchian_hi_20":     dc_20["upper"],
        "donchian_lo_20":     dc_20["lower"],
        "supertrend_dir":     st["direction"],
        "macd_hist":          macd_df["hist"],
        "close_52w_hi_pct":   high_52w_pct,
        # adx_14 and rsi_14 intentionally omitted here — they are in Group B
        # and will appear once in the final DataFrame (scale-invariant forms
        # are equally usable by rule signals).
    }

    # ------------------------------------------------------------------
    # Group B — ML-ready normalized (shifted +1 bar)
    # ------------------------------------------------------------------
    dc55_range = (dc_55["upper"] - dc_55["lower"]).replace(0, np.nan)
    dc20_range = (dc_20["upper"] - dc_20["lower"]).replace(0, np.nan)
    bb_range   = (bb_bands["upper"] - bb_bands["lower"]).replace(0, np.nan)

    obv_s    = P.obv(close, volume)
    obv_ema  = P.ema(obv_s, 20).replace(0, np.nan)
    slope_10d = P.linear_reg_slope(close, 10)

    group_b: dict[str, pd.Series] = {
        "close_vs_ema20_pct":  (close / ema_20.replace(0, np.nan) - 1) * 100,
        "close_vs_ema50_pct":  (close / ema_50.replace(0, np.nan) - 1) * 100,
        "close_vs_ema200_pct": (close / ema_200.replace(0, np.nan) - 1) * 100,
        "donchian_pos_55":     (close - dc_55["lower"]) / dc55_range,
        "donchian_pos_20":     (close - dc_20["lower"]) / dc20_range,
        "bb_pct_b":            (close - bb_bands["lower"]) / bb_range,
        "rsi_14":              rsi_14,
        "adx_14":              adx_14,
        "macd_hist_norm":      macd_df["hist"] / atr_pct_14.replace(0, np.nan),
        "slope_10d_pct":       slope_10d / close.replace(0, np.nan) * 10 * 100,
        "ret_1d":              close.pct_change(1) * 100,
        "ret_5d":              close.pct_change(5) * 100,
        "ret_20d":             close.pct_change(20) * 100,
        "rv_24":               P.realised_vol(close, 24, annualise_factor=252),
        "rv_rank":             P.rv_rank(close, 24, 252),
        "atr_pct":             atr_pct_14,
        "bb_width":            P.bb_width(close, 20),
        "vol_ratio":           volume / volume.rolling(20, min_periods=10).mean().replace(0, np.nan),
        "vol_z":               P.vol_z(volume, 24),
        "obv_vs_ema":          (obv_s / obv_ema - 1) * 100,
    }

    # ------------------------------------------------------------------
    # Composite features (shifted below with price cols)
    # ------------------------------------------------------------------
    composites: dict[str, pd.Series] = {
        "trend_regime":         trend_regime(df1d),
        "vol_expansion":        vol_expansion(df1d),
        "friday_monday_stress": friday_monday_stress(df1d),
    }

    # ------------------------------------------------------------------
    # Calendar features (timestamp-derived; no shift)
    # ------------------------------------------------------------------
    calendar: dict[str, pd.Series] = {
        "dow":           dow(df1d.index).astype("int8"),
        "is_us_session": is_us_session(df1d.index).astype("int8"),
        "is_us_holiday": is_us_holiday(df1d.index).astype("int8"),
    }

    # ------------------------------------------------------------------
    # Apply shift(1) to all price-derived columns
    # ------------------------------------------------------------------
    price_cols = {**group_a, **group_b, **composites}
    shifted = {k: v.shift(1) for k, v in price_cols.items()}

    # ------------------------------------------------------------------
    # 1h HTF add-ons (optional — silently skipped on failure)
    # ------------------------------------------------------------------
    htf_cols: dict[str, pd.Series] = {}
    if df1h is not None:
        try:
            close_1h  = df1h["close"]
            ema24_1h  = P.ema(close_1h, 24)
            vs_ema24  = (close_1h / ema24_1h.replace(0, np.nan) - 1) * 100
            vs_ema24.name = "close_vs_ema24_1h_pct"

            df4h     = P.resample(df1h, "4h")
            ret_4h   = df4h["close"].pct_change() * 100
            ret_4h.name = "ret_4h"

            vol_z_1h = P.vol_z(df1h["volume"], 24)
            vol_z_1h.name = "vol_z_1h"

            htf_cols["close_vs_ema24_1h_pct"] = P.htf_align(df1d, vs_ema24, htf="1h").shift(1)
            htf_cols["ret_4h"]                = P.htf_align(df1d, ret_4h,   htf="4h").shift(1)
            htf_cols["vol_z_1h"]              = P.htf_align(df1d, vol_z_1h, htf="1h").shift(1)
        except Exception:
            log.warning("1h HTF add-ons failed; skipping", exc_info=True)

    all_cols = {**shifted, **calendar, **htf_cols}
    return pd.DataFrame(all_cols, index=df1d.index)


# ===========================================================================
# MacroFeatures
# ===========================================================================

class MacroFeatures:
    """Daily macro regime features aligned to a primary instrument's bar index.

    Requires the target instrument's 1d frame plus any available macro frames
    in the ``frames`` dict (venue ``"fred"`` or ``"cboe"``).  Missing macro
    refs are silently skipped — the output columns that depend on them are
    simply absent.

    Recognised macro tickers: VIX, T10Y2Y, DGS10, BAMLH0A0HYM2, DFF,
    CPIAUCSL, DX-Y.NYB.

    Usage::

        ref_1d  = DatasetRef(Symbol("yahoo", "SPY"), "1d")
        ref_vix = DatasetRef(Symbol("cboe",  "VIX"),    "1d")
        ref_yc  = DatasetRef(Symbol("fred",  "T10Y2Y"), "1d")

        macro = MacroFeatures().build({
            ref_1d: bars_1d,
            ref_vix: vix_df,
            ref_yc: yc_df,
            ...
        })
    """

    id = "macro_features"
    version = "1"

    @cached
    def build(self, frames: dict[DatasetRef, pd.DataFrame]) -> pd.DataFrame:
        return _compute_macro_features(frames)


def _get_macro_series(
    frames: dict[DatasetRef, pd.DataFrame],
    ticker: str,
) -> pd.Series | None:
    """Extract a named macro series from frames, returning 'close' or 'value'."""
    for ref, df in frames.items():
        if ref.symbol.ticker == ticker:
            for col in ("close", "value"):
                if col in df.columns:
                    return df[col]
            numeric = df.select_dtypes("number")
            if not numeric.empty:
                return numeric.iloc[:, 0]
    return None


from cryoquant.features.align import align_series as _align_to_index
def _compute_macro_features(
    frames: dict[DatasetRef, pd.DataFrame],
) -> pd.DataFrame:
    """Pure computation — separated for testability."""
    primary_ref = next(
        (r for r in frames if r.symbol.venue not in _MACRO_VENUES), None
    )
    if primary_ref is None:
        raise ValueError(
            "MacroFeatures requires at least one non-macro DatasetRef (the target instrument)"
        )
    target_idx = frames[primary_ref].index

    vix      = _get_macro_series(frames, "VIX")
    t10y2y   = _get_macro_series(frames, "T10Y2Y")
    dgs10    = _get_macro_series(frames, "DGS10")
    hy_spread = _get_macro_series(frames, "BAMLH0A0HYM2")
    dff      = _get_macro_series(frames, "DFF")
    cpi      = _get_macro_series(frames, "CPIAUCSL")
    dxy      = _get_macro_series(frames, "DX-Y.NYB")

    cols: dict[str, pd.Series] = {}

    if vix is not None:
        vix_a    = _align_to_index(target_idx, vix)
        vix_mean = vix_a.rolling(20, min_periods=10).mean()
        vix_std  = vix_a.rolling(20, min_periods=10).std(ddof=0).replace(0, np.nan)
        cols["vix_level"] = vix_a
        cols["vix_z20"]   = (vix_a - vix_mean) / vix_std

    if t10y2y is not None:
        yc = _align_to_index(target_idx, t10y2y)
        cols["yc_sign"]  = np.sign(yc)
        cols["yc_trend"] = yc - yc.rolling(20, min_periods=10).mean()

    if dgs10 is not None:
        dgs10_a = _align_to_index(target_idx, dgs10)
        cols["dgs10_ema_dir"] = np.sign(P.ema(dgs10_a, 20) - P.ema(dgs10_a, 60))

    if hy_spread is not None:
        hy_a    = _align_to_index(target_idx, hy_spread)
        hy_mean = hy_a.rolling(60, min_periods=20).mean()
        hy_std  = hy_a.rolling(60, min_periods=20).std(ddof=0).replace(0, np.nan)
        cols["hy_spread_z60"] = (hy_a - hy_mean) / hy_std

    if dff is not None:
        dff_a = _align_to_index(target_idx, dff)
        cols["rate_hiking"] = (dff_a > dff_a.shift(63)).astype(float)

    if cpi is not None:
        cpi_a = _align_to_index(target_idx, cpi, ffill_limit=35)
        cols["cpi_yoy"] = cpi_a.pct_change(12) * 100  # monthly series

    if dxy is not None:
        dxy_a = _align_to_index(target_idx, dxy)
        cols["dxy_ema_dir"] = np.sign(P.ema(dxy_a, 20) - P.ema(dxy_a, 60))

    risk_off = pd.Series(False, index=target_idx)
    if "vix_z20" in cols:
        risk_off = risk_off | (cols["vix_z20"] > 1.5)
    if "hy_spread_z60" in cols:
        risk_off = risk_off | (cols["hy_spread_z60"] > 1.5)
    cols["macro_risk_off"] = risk_off.fillna(False).astype(float)

    if not cols:
        log.warning("MacroFeatures: no macro series found in frames — returning empty DataFrame")
        return pd.DataFrame(index=target_idx)

    return pd.DataFrame(cols, index=target_idx)


# ===========================================================================
# CrossAssetFeatures
# ===========================================================================

class CrossAssetFeatures:
    """Relative-strength and cross-instrument ratio features.

    Requires the target instrument's 1d frame.  SPY, GLD, and USO frames
    are optional; missing benchmark refs are silently skipped.

    Output columns (all shifted +1 bar):

    - ``rs_vs_spy_20d``  — 20-day relative strength vs SPY
    - ``rs_vs_spy_60d``  — 60-day relative strength vs SPY
    - ``rs_trend``       — 20d RS minus its own 20-bar lag
    - ``gld_uso_ratio``  — GLD/USO price ratio

    Usage::

        ref_inst = DatasetRef(Symbol("yahoo", "XLE"), "1d")
        ref_spy  = DatasetRef(Symbol("yahoo", "SPY"), "1d")
        ref_gld  = DatasetRef(Symbol("yahoo", "GLD"), "1d")

        cross = CrossAssetFeatures().build({
            ref_inst: xle_1d,
            ref_spy:  spy_1d,
            ref_gld:  gld_1d,
        })
    """

    id = "cross_asset_features"
    version = "1"

    @cached
    def build(self, frames: dict[DatasetRef, pd.DataFrame]) -> pd.DataFrame:
        return _compute_cross_asset_features(frames)


def _get_close(
    frames: dict[DatasetRef, pd.DataFrame],
    ticker: str,
) -> pd.Series | None:
    for ref, df in frames.items():
        if ref.symbol.ticker == ticker and ref.tf == "1d":
            return df["close"]
    return None


def _compute_cross_asset_features(
    frames: dict[DatasetRef, pd.DataFrame],
) -> pd.DataFrame:
    """Pure computation — separated for testability."""
    primary_ref = next(
        (r for r in frames
         if r.tf == "1d"
         and r.symbol.ticker not in _BENCHMARK_TICKERS
         and r.symbol.venue not in _MACRO_VENUES),
        None,
    )
    if primary_ref is None:
        primary_ref = next((r for r in frames if r.tf == "1d"), None)
    if primary_ref is None:
        raise ValueError("CrossAssetFeatures requires at least one 1d DatasetRef")

    close      = frames[primary_ref]["close"]
    target_idx = close.index

    spy = _get_close(frames, "SPY")
    gld = _get_close(frames, "GLD")
    uso = _get_close(frames, "USO")

    cols: dict[str, pd.Series] = {}

    if spy is not None:
        spy_a = spy.reindex(target_idx, method="ffill")
        rs20  = P.relative_strength(close, spy_a, 20)
        cols["rs_vs_spy_20d"] = rs20.shift(1)
        cols["rs_vs_spy_60d"] = P.relative_strength(close, spy_a, 60).shift(1)
        cols["rs_trend"]      = (rs20 - rs20.shift(20)).shift(1)

    if gld is not None and uso is not None:
        gld_a = gld.reindex(target_idx, method="ffill")
        uso_a = uso.reindex(target_idx, method="ffill")
        cols["gld_uso_ratio"] = (gld_a / uso_a.replace(0, np.nan)).shift(1)

    if not cols:
        log.warning("CrossAssetFeatures: no benchmark series found — returning empty DataFrame")
        return pd.DataFrame(index=target_idx)

    return pd.DataFrame(cols, index=target_idx)
