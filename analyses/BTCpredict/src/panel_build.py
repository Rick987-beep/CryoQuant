"""Load study data and build Phase 2 feature matrix.

Panel contract (FEATURE_CATALOG.md, SPEC §8):
  - Long format: one row per ``(timestamp, asset)`` with ``asset ∈ {BTC, ETH, SOL}``.
  - ``timestamp`` = UTC **bar open** for interval ``[T, T+1)`` (Binance daily convention).
  - Global features (macro, cross-asset, network on BTC rows) are replicated on each asset row.
  - Output columns match ``features.yaml`` exactly (via ``finalize_panel``).

Bar / lag conventions:
  - Price-derived (TrendFeatures): ``.shift(1)`` — feature at ``T`` uses closes through ``T-1``.
  - DVOL / macro levels: same-calendar-date ``align_series`` asof (no extra shift).
  - ETF / MSTR / on-chain: ``available_utc`` backward asof (DATA_SOURCES §E.1, §G.3).
  - Chain IV: only dates ≥ ``CHAIN_FIRST``; CryoBacktester parquets are BTC-only today.

Entry point: ``build_study_panel(cfg)`` — used by ``run_phase2_features.py``.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import pandas as pd

from cryocore.instruments import Symbol
from cryoquant.data import macro_store
from cryoquant.data.resolve import load_track
from cryoquant.data.sources import deribit_options
from cryoquant.features.align import align_series
from cryoquant.features.builders import DatasetRef
from cryoquant.features.crypto_builders import (
    CryptoFeatures,
    NetworkFeatures,
    build_study_cross_global,
)
from cryoquant.features.options import build_chain_feature_frame, dvol_features
from cryoquant.features.trend_builders import MacroFeatures, TrendFeatures

from src.feature_schema import finalize_panel
from src.config_models import StudyConfig
from src.feature_align import align_by_available_utc, build_fomc_calendar_features, union_daily_index

log = logging.getLogger(__name__)

ASSETS = ("BTC", "ETH", "SOL")
TICKERS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
CHAIN_FIRST = date(2025, 4, 11)
NETWORK_COLS = (
    "hr_change_7d",
    "hr_zscore_90d",
    "active_addr_change_7d",
    "active_addr_z30",
    "tx_cnt_z21",
    "fee_btc_z21",
)
OPTIONS_ASSET_COL_PREFIX = {"BTC": "btc_", "ETH": "eth_"}


def _sym(asset: str) -> Symbol:
    return Symbol("binance.spot", TICKERS[asset])


def _load_ohlcv(asset: str, tf: str, start: datetime, end: datetime) -> pd.DataFrame:
    try:
        return load_track(_sym(asset), tf, start, end)
    except FileNotFoundError:
        log.warning("No %s %s bars in [%s, %s]", asset, tf, start.date(), end.date())
        return pd.DataFrame()


def _load_macro_series(source: str, series_id: str, start: datetime, end: datetime) -> pd.Series:
    try:
        return macro_store.load_series(source, series_id, start, end)
    except FileNotFoundError:
        log.warning("Missing macro series %s/%s", source, series_id)
        return pd.Series(dtype=float)


def _load_macro_frame(source: str, series_id: str, start: datetime, end: datetime) -> pd.DataFrame:
    try:
        return macro_store.load_frame(source, series_id, start, end)
    except FileNotFoundError:
        log.warning("Missing macro frame %s/%s", source, series_id)
        return pd.DataFrame()


def _prefix_columns(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    if df.empty:
        return df
    return df.rename(columns={c: f"{prefix}{c}" for c in df.columns})


def _normalize_index(df: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    """Unify DatetimeIndex to UTC nanoseconds for merge_asof compatibility."""
    out = df.copy()
    idx = pd.DatetimeIndex(out.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    out.index = idx.as_unit("ns")
    return out


def _normalize_series(s: pd.Series) -> pd.Series:
    if s.empty:
        return s
    return _normalize_index(s)  # type: ignore[return-value]


def _load_track_close(symbol: Symbol, tf: str, start: datetime, end: datetime) -> pd.Series:
    try:
        data = load_track(symbol, tf, start, end)
    except FileNotFoundError:
        log.warning("Missing track %s@%s", symbol, tf)
        return pd.Series(dtype=float)
    if isinstance(data, pd.DataFrame):
        return data["close"]
    return data


def _build_macro_block(index: pd.DatetimeIndex, start: datetime, end: datetime) -> pd.DataFrame:
    """MacroFeatures + SOFR + FOMC calendar + raw level extensions."""
    index = pd.DatetimeIndex(index).tz_convert("UTC").as_unit("ns")
    btc = _normalize_index(_load_ohlcv("BTC", "1d", start, end))
    ref_btc = DatasetRef(_sym("BTC"), "1d")
    frames: dict[DatasetRef, pd.DataFrame] = {ref_btc: btc}

    vix = _load_macro_series("cboe", "VIX_CLOSE", start, end)
    if not vix.empty:
        frames[DatasetRef(Symbol("cboe", "VIX"), "1d")] = _normalize_index(vix.rename("value").to_frame())

    for sym in (Symbol("fred", "DX-Y.NYB"),):
        s = _load_macro_series(sym.venue, "DXY", start, end)
        if not s.empty:
            frames[DatasetRef(sym, "1d")] = _normalize_index(s.rename("value").to_frame())

    t10y2y = _load_macro_series("fred", "T10Y2Y", start, end)
    if not t10y2y.empty:
        frames[DatasetRef(Symbol("fred", "T10Y2Y"), "1d")] = _normalize_index(t10y2y.rename("value").to_frame())

    for sym in (Symbol("yahoo", "SPY"), Symbol("yahoo", "GLD")):
        s = _load_track_close(sym, "1d", start, end)
        if not s.empty:
            frames[DatasetRef(sym, "1d")] = _normalize_index(s.rename("close").to_frame())

    macro = MacroFeatures().build(frames)

    dxy = _normalize_series(_load_macro_series("fred", "DXY", start, end))
    if not dxy.empty:
        macro["dxy_level"] = align_series(index, dxy, name="dxy_level")

    sofr = _normalize_series(_load_macro_series("fred", "SOFR", start, end))
    if not sofr.empty:
        sofr_a = align_series(index, sofr, name="sofr_level")
        macro["sofr_level"] = sofr_a
        macro["sofr_chg_63d"] = sofr_a - sofr_a.shift(63)

    fomc = build_fomc_calendar_features(index)
    macro = macro.join(fomc, how="outer")

    return macro.reindex(index)


def _load_chain_cache(
    chain_dates: list[date],
    index: pd.DatetimeIndex,
) -> list[tuple[date, pd.DataFrame]]:
    """Load option chains once for dates overlapping the panel index."""
    lo, hi = index.min().date(), index.max().date()
    chains: list[tuple[date, pd.DataFrame]] = []
    for d in chain_dates:
        if d < lo or d > hi:
            continue
        try:
            chains.append((d, deribit_options.load_chain(d)))
        except Exception:
            continue
    return chains


def _build_options_block(
    index: pd.DatetimeIndex,
    start: datetime,
    end: datetime,
    rv_by_asset: dict[str, pd.Series],
) -> pd.DataFrame:
    """DVOL + gated chain features for BTC/ETH."""
    out = pd.DataFrame(index=index)
    chain_dates = [d for d in deribit_options.list_dates() if d >= CHAIN_FIRST]
    cached_chains = _load_chain_cache(chain_dates, index)

    for asset in ("BTC", "ETH"):
        prefix = OPTIONS_ASSET_COL_PREFIX[asset]
        dvol = _normalize_series(_load_macro_series("deribit", f"{asset}_DVOL", start, end))
        rv = rv_by_asset.get(asset)
        if rv is not None and not dvol.empty:
            dvol_df = dvol_features(dvol, rv, prefix=prefix)
            out = out.join(dvol_df.reindex(index), how="outer")

    # CryoBacktester chains are BTC-only; attach under btc_ prefix.
    if cached_chains:
        chain_df = build_chain_feature_frame(cached_chains, prefix="btc_")
        out = out.join(chain_df.reindex(index), how="outer")

    return out


def _options_source_row(row: pd.Series, asset: str) -> str:
    if asset == "SOL":
        return "none"
    prefix = OPTIONS_ASSET_COL_PREFIX[asset]
    if pd.notna(row.get(f"{prefix}atm_iv_30d")):
        return "chain"
    if pd.notna(row.get(f"{prefix}dvol_30d")):
        return "dvol"
    return "none"


def build_study_features(
    cfg: StudyConfig,
    end: datetime | None = None,
    *,
    include_labels: bool = False,
) -> pd.DataFrame:
    """Long panel: one row per (timestamp, asset). Columns per FEATURE_CATALOG.

  Labels are built separately in Phase 3 (``label_build.py``). ``include_labels``
  must remain False for the feature matrix (P-4 / SPEC §9).
    """
    if include_labels:
        raise ValueError("include_labels must be False — use build_study_labels() for targets")
    end_dt = end or datetime.now(timezone.utc)
    start_dt = datetime.combine(cfg.splits.dev_start, datetime.min.time(), tzinfo=timezone.utc)

    bars_1d = {a: _load_ohlcv(a, "1d", start_dt, end_dt) for a in ASSETS}
    bars_1h: dict[str, pd.DataFrame] = {}
    for a in ASSETS:
        try:
            bars_1h[a] = _load_ohlcv(a, "1h", start_dt, end_dt)
        except Exception:
            log.warning("No hourly bars for %s", a)
            bars_1h[a] = pd.DataFrame()

    index = union_daily_index(bars_1d)
    if index.empty:
        raise RuntimeError("No daily OHLCV bars loaded for feature panel")
    index = pd.DatetimeIndex(index).tz_convert("UTC").as_unit("ns")
    bars_1d = {a: _normalize_index(b) for a, b in bars_1d.items()}
    bars_1h = {a: _normalize_index(b) if not b.empty else b for a, b in bars_1h.items()}

    trend_parts: list[pd.DataFrame] = []
    rv_by_asset: dict[str, pd.Series] = {}
    for asset in ASSETS:
        prefix = f"{asset.lower()}_"
        ref_1d = DatasetRef(_sym(asset), "1d")
        frames: dict[DatasetRef, pd.DataFrame] = {ref_1d: bars_1d[asset]}
        h1 = bars_1h.get(asset)
        if h1 is not None and not h1.empty:
            frames[DatasetRef(_sym(asset), "1h")] = h1
        tdf = TrendFeatures().build(frames)
        if "rv_24" in tdf.columns:
            rv_by_asset[asset] = tdf["rv_24"]
        trend_parts.append(_prefix_columns(tdf, prefix))

    trend_block = trend_parts[0]
    for part in trend_parts[1:]:
        trend_block = trend_block.join(part, how="outer")

    macro_block = _build_macro_block(index, start_dt, end_dt)

    crypto = CryptoFeatures()
    etf = _load_macro_frame("farside", "etf_flow_aggregate_us", start_dt, end_dt)
    etf_flow = align_by_available_utc(index, etf, ffill_limit=5) if not etf.empty else None
    mstr_p = _load_macro_frame("strategy", "mstr_btc_purchases", start_dt, end_dt)
    mstr_h = _load_macro_frame("strategy", "mstr_btc_holdings", start_dt, end_dt)
    global_crypto = crypto.build_global(
        index,
        fear_greed=_normalize_series(_load_macro_series("fear_greed", "CRYPTO_FEAR_GREED", start_dt, end_dt)),
        stablecoin=_normalize_series(_load_macro_series("defillama", "STABLECOIN_SUPPLY", start_dt, end_dt)),
        etf_flow=etf_flow,
        mstr_acq=align_by_available_utc(index, mstr_p, value_col="btc_acq", ffill_limit=5)
        if not mstr_p.empty
        else None,
        mstr_holdings=align_by_available_utc(index, mstr_h, value_col="btc_holding", ffill_limit=5)
        if not mstr_h.empty
        else None,
    )

    per_asset_crypto: dict[str, pd.DataFrame] = {}
    for asset in ASSETS:
        ticker = TICKERS[asset]
        funding = _normalize_series(_load_macro_series("binance_perp", f"{ticker}_funding", start_dt, end_dt))
        oi = None
        if asset in ("BTC", "ETH"):
            oi = _normalize_series(_load_macro_series("xoomar", f"{ticker}_open_interest_usd", start_dt, end_dt))
            if oi.empty:
                oi = _normalize_series(_load_macro_series("xoomar", f"{ticker}_open_interest", start_dt, end_dt))
        per_asset_crypto[asset] = crypto.build_per_asset(
            index,
            funding=funding,
            oi_usd=oi,
            prefix=f"{asset.lower()}_",
        )

    network_block = NetworkFeatures().build(
        index,
        hash_rate=align_by_available_utc(
            index, _load_macro_frame("coinmetrics", "btc_HashRate", start_dt, end_dt), ffill_limit=7
        ),
        active_addr=align_by_available_utc(
            index, _load_macro_frame("coinmetrics", "btc_AdrActCnt", start_dt, end_dt), ffill_limit=7
        ),
        tx_cnt=align_by_available_utc(
            index, _load_macro_frame("coinmetrics", "btc_TxCnt", start_dt, end_dt), ffill_limit=7
        ),
        fee_btc=align_by_available_utc(
            index, _load_macro_frame("coinmetrics", "btc_FeeTotNtv", start_dt, end_dt), ffill_limit=7
        ),
    )

    options_block = _build_options_block(index, start_dt, end_dt, rv_by_asset)

    cross_block = build_study_cross_global(
        index,
        btc_close=bars_1d["BTC"]["close"],
        eth_close=bars_1d["ETH"]["close"] if not bars_1d["ETH"].empty else None,
        sol_close=bars_1d["SOL"]["close"] if not bars_1d["SOL"].empty else None,
        spy_close=_load_track_close(Symbol("yahoo", "SPY"), "1d", start_dt, end_dt),
        gld_close=_load_track_close(Symbol("yahoo", "GLD"), "1d", start_dt, end_dt),
    )

    shared = trend_block.join(
        [macro_block, global_crypto, network_block, options_block, cross_block],
        how="outer",
    )

    all_crypto_cols = per_asset_crypto["BTC"]
    for asset in ("ETH", "SOL"):
        all_crypto_cols = all_crypto_cols.join(per_asset_crypto[asset], how="outer")

    wide = shared.join(all_crypto_cols, how="outer")
    wide = wide.loc[index]

    frames: list[pd.DataFrame] = []
    for asset in ASSETS:
        mask = index.isin(bars_1d[asset].index)
        if not mask.any():
            continue
        sub = wide.loc[mask].copy()
        sub["timestamp"] = sub.index
        sub["asset"] = asset
        sub["options_source"] = sub.apply(lambda r: _options_source_row(r, asset), axis=1)
        if asset != "BTC":
            for col in NETWORK_COLS:
                if col in sub.columns:
                    sub[col] = float("nan")
        frames.append(sub.reset_index(drop=True))

    df = pd.concat(frames, ignore_index=True)
    if df.empty:
        raise RuntimeError("Feature panel is empty after row assembly")
    df = df.sort_values(["timestamp", "asset"]).reset_index(drop=True)
    return finalize_panel(df)


def build_study_panel(
    cfg: StudyConfig,
    end: datetime | None = None,
    *,
    include_labels: bool = False,
) -> pd.DataFrame:
    """Alias for ``build_study_features`` (SPEC §8 contract)."""
    return build_study_features(cfg, end=end, include_labels=include_labels)
