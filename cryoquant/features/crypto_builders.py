"""Crypto-native feature builders (sentiment, flows, network, cross-asset ratios).

Implements tier-2 builders for on-chain, institutional, and sentiment overlays.
Global columns are replicated on every asset row in multi-asset panels; network metrics
are typically anchored to a single reference asset (NaN on other rows).

Global columns (fear/greed, ETF, cross ratios) are replicated on every asset row
in ``panel_build.py``. Network metrics are BTC-only (NaN on ETH/SOL rows).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from cryoquant.features import primitives as P

log = logging.getLogger(__name__)

ETF_FFILL_LIMIT = 5


class CryptoFeatures:
    """Funding, sentiment, stablecoins, institutional flows (global + per-asset)."""

    id = "crypto_features"
    version = "1"

    def build_per_asset(
        self,
        index: pd.DatetimeIndex,
        *,
        funding: pd.Series | None,
        oi_usd: pd.Series | None,
        prefix: str,
    ) -> pd.DataFrame:
        cols: dict[str, pd.Series] = {}
        if funding is not None and not funding.empty:
            fr = align_like(index, funding)
            cols[f"{prefix}funding_rate"] = fr
            cols[f"{prefix}funding_z21"] = P.vol_z(fr, 21).replace([np.inf, -np.inf], np.nan)
        if oi_usd is not None and not oi_usd.empty:
            oi = align_like(index, oi_usd)
            cols[f"{prefix}oi_usd"] = oi
            cols[f"{prefix}oi_chg_7d"] = oi.pct_change(7) * 100.0
        if not cols:
            return pd.DataFrame(index=index)
        return pd.DataFrame(cols, index=index)

    def build_global(
        self,
        index: pd.DatetimeIndex,
        *,
        fear_greed: pd.Series | None,
        stablecoin: pd.Series | None,
        etf_flow: pd.Series | None,
        mstr_acq: pd.Series | None,
        mstr_holdings: pd.Series | None,
    ) -> pd.DataFrame:
        cols: dict[str, pd.Series] = {}

        if fear_greed is not None and not fear_greed.empty:
            fg = align_like(index, fear_greed)
            cols["fear_greed"] = fg
            cols["fear_greed_z21"] = P.vol_z(fg, 21).replace([np.inf, -np.inf], np.nan)

        if stablecoin is not None and not stablecoin.empty:
            sc = align_like(index, stablecoin)
            cols["stablecoin_supply"] = sc
            cols["stablecoin_chg_7d_pct"] = sc.pct_change(7) * 100.0
            mu = sc.rolling(30, min_periods=15).mean()
            sd = sc.rolling(30, min_periods=15).std(ddof=0).replace(0, np.nan)
            cols["stablecoin_z30"] = (sc - mu) / sd

        if etf_flow is not None and not etf_flow.empty:
            ef = align_like(index, etf_flow)
            cols["etf_flow_1d_usd"] = ef
            cols["etf_flow_5d_usd"] = ef.rolling(5, min_periods=1).sum()
            mu = ef.rolling(21, min_periods=10).mean()
            sd = ef.rolling(21, min_periods=10).std(ddof=0).replace(0, np.nan)
            cols["etf_flow_z21"] = (ef - mu) / sd

        if mstr_acq is not None and not mstr_acq.empty:
            cols["mstr_btc_acq"] = align_like(index, mstr_acq)
        if mstr_holdings is not None and not mstr_holdings.empty:
            cols["mstr_holdings_btc"] = align_like(index, mstr_holdings)

        if not cols:
            return pd.DataFrame(index=index)
        return pd.DataFrame(cols, index=index)


class NetworkFeatures:
    """BTC L1 network momentum (NaN on non-BTC asset rows at panel stage)."""

    id = "network_features"
    version = "1"

    def build(
        self,
        index: pd.DatetimeIndex,
        *,
        hash_rate: pd.Series | None,
        active_addr: pd.Series | None,
        tx_cnt: pd.Series | None,
        fee_btc: pd.Series | None,
    ) -> pd.DataFrame:
        cols: dict[str, pd.Series] = {}

        if hash_rate is not None and not hash_rate.empty:
            hr = align_like(index, hash_rate)
            cols["hr_change_7d"] = hr.pct_change(7) * 100.0
            mu = hr.rolling(90, min_periods=30).mean()
            sd = hr.rolling(90, min_periods=30).std(ddof=0).replace(0, np.nan)
            cols["hr_zscore_90d"] = (hr - mu) / sd

        if active_addr is not None and not active_addr.empty:
            aa = align_like(index, active_addr)
            cols["active_addr_change_7d"] = aa.pct_change(7) * 100.0
            mu = aa.rolling(30, min_periods=10).mean()
            sd = aa.rolling(30, min_periods=10).std(ddof=0).replace(0, np.nan)
            cols["active_addr_z30"] = (aa - mu) / sd

        if tx_cnt is not None and not tx_cnt.empty:
            tx = align_like(index, tx_cnt)
            mu = tx.rolling(21, min_periods=10).mean()
            sd = tx.rolling(21, min_periods=10).std(ddof=0).replace(0, np.nan)
            cols["tx_cnt_z21"] = (tx - mu) / sd

        if fee_btc is not None and not fee_btc.empty:
            fee = align_like(index, fee_btc)
            mu = fee.rolling(21, min_periods=10).mean()
            sd = fee.rolling(21, min_periods=10).std(ddof=0).replace(0, np.nan)
            cols["fee_btc_z21"] = (fee - mu) / sd

        if not cols:
            return pd.DataFrame(index=index)
        return pd.DataFrame(cols, index=index)


def align_like(index: pd.DatetimeIndex, series: pd.Series) -> pd.Series:
    s = series.copy()
    if s.index.tz is None:
        s.index = s.index.tz_localize("UTC")
    else:
        s.index = s.index.tz_convert("UTC")
    return s.reindex(index)


def build_crypto_cross_ratios(
    index: pd.DatetimeIndex,
    *,
    btc_close: pd.Series,
    eth_close: pd.Series | None,
    sol_close: pd.Series | None,
    spy_close: pd.Series | None,
    gld_close: pd.Series | None,
) -> pd.DataFrame:
    """Global cross-asset features (replicated on every asset row)."""
    cols: dict[str, pd.Series] = {}
    btc = align_like(index, btc_close)

    if eth_close is not None and not eth_close.empty:
        eth = align_like(index, eth_close)
        ratio = eth / btc.replace(0, np.nan)
        cols["eth_btc_ratio"] = ratio
        cols["eth_btc_ratio_chg_7d"] = ratio.pct_change(7) * 100.0

    if sol_close is not None and not sol_close.empty:
        sol = align_like(index, sol_close)
        ratio = sol / btc.replace(0, np.nan)
        cols["sol_btc_ratio"] = ratio
        cols["sol_btc_ratio_chg_7d"] = ratio.pct_change(7) * 100.0

    if spy_close is not None and not spy_close.empty:
        spy = align_like(index, spy_close)
        cols["rs_vs_spy_20d"] = P.relative_strength(btc, spy, 20)
        cols["rs_vs_spy_60d"] = P.relative_strength(btc, spy, 60)

    if gld_close is not None and not gld_close.empty:
        gld = align_like(index, gld_close)
        cols["gld_btc_ratio"] = gld / btc.replace(0, np.nan)

    if not cols:
        return pd.DataFrame(index=index)
    return pd.DataFrame(cols, index=index)

