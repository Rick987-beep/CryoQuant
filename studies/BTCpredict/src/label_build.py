"""Build Phase 3 label store in long format (LABEL_CATALOG.md, SPEC §9).

Contract:
  - Input: daily OHLCV via ``load_track`` (not ``features.parquet``).
  - Output: long ``(timestamp, asset, horizon_id, label_name, value)``; NaN omitted.
  - Families 1–6 per LABEL_CATALOG; family 7 (path/touch) deferred to Phase 6.
  - BTC/ETH get exceedance + VRP; SOL gets directional + log-return + fwd-RV only.

Entry point: ``build_study_labels(cfg)`` — used by ``run_phase3_labels.py``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import pandas as pd

from cryocore.instruments import Symbol
from cryoquant.data import macro_store
from cryoquant.data.resolve import load_track
from cryoquant.features.labels import (
    ExceedanceLabeler,
    ForwardReturnLabeler,
    LogReturnLabeler,
    RealizedVolLabeler,
    VRPRealizationLabeler,
    VolScaledThreshold,
    causal_forward_return_quantile,
)

from src.config_models import StudyConfig
from src.feature_align import union_daily_index

log = logging.getLogger(__name__)

ASSETS = ("BTC", "ETH", "SOL")
OPTIONS_ASSETS = ("BTC", "ETH")
TICKERS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
DIRECTIONS = ("up", "down", "magnitude")


def _sym(asset: str) -> Symbol:
    return Symbol("binance.spot", TICKERS[asset])


def _normalize_index(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    idx = pd.DatetimeIndex(out.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    out.index = idx.as_unit("ns")
    return out


def _load_ohlcv(asset: str, start: datetime, end: datetime) -> pd.DataFrame:
    try:
        return _normalize_index(load_track(_sym(asset), "1d", start, end))
    except FileNotFoundError:
        log.warning("No %s 1d bars in store", asset)
        return pd.DataFrame()


def _load_dvol(asset: str, start: datetime, end: datetime) -> pd.Series:
    try:
        s = macro_store.load_series("deribit", f"{asset}_DVOL", start, end)
    except FileNotFoundError:
        log.warning("Missing DVOL for %s — VRP labels skipped", asset)
        return pd.Series(dtype=float)
    if s.empty:
        return s
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    return pd.Series(s.values, index=idx.as_unit("ns"), name=f"{asset}_dvol")


def _melt_labels(
    *,
    timestamps: pd.DatetimeIndex,
    asset: str,
    horizon_id: str,
    series_map: dict[str, pd.Series],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for label_name, values in series_map.items():
        aligned = values.reindex(timestamps)
        for ts, val in aligned.items():
            if pd.isna(val):
                continue
            rows.append(
                {
                    "timestamp": ts,
                    "asset": asset,
                    "horizon_id": horizon_id,
                    "label_name": label_name,
                    "value": float(val),
                }
            )
    return rows


def _assert_trailing_nan(series: pd.Series, horizon: int, ctx: str) -> None:
    if horizon <= 0 or series.empty:
        return
    tail = series.iloc[-horizon:]
    if tail.notna().any():
        raise AssertionError(f"Expected last {horizon} rows NaN for {ctx}")


def _labels_for_asset_horizon(
    bars: pd.DataFrame,
    asset: str,
    horizon_id: str,
    horizon_bars: int,
    cfg: StudyConfig,
    iv: pd.Series | None,
) -> list[dict[str, object]]:
    """Emit all label series for one (asset, horizon) group, then melt to rows."""
    if bars.empty:
        return []

    label_cfg = cfg.label
    h = horizon_bars
    series_map: dict[str, pd.Series] = {}

    if label_cfg.use_vol_scaled_threshold:
        thr = VolScaledThreshold.apply(
            bars["close"],
            h,
            window=label_cfg.realized_vol_window,
            k=label_cfg.vol_scale_k,
        )
        for direction in DIRECTIONS:
            lab = ForwardReturnLabeler(h, label_cfg.direction_threshold_pct, direction)
            s = lab.apply(bars, threshold_pct=thr)
            _assert_trailing_nan(s, h, f"{asset}/{horizon_id}/{direction}")
            series_map[lab.column_name_volscaled()] = s
    else:
        for direction in DIRECTIONS:
            lab = ForwardReturnLabeler(h, label_cfg.direction_threshold_pct, direction)
            s = lab.apply(bars)
            _assert_trailing_nan(s, h, f"{asset}/{horizon_id}/{direction}")
            series_map[lab.column_name] = s

    log_ret = LogReturnLabeler(h).apply(bars)
    _assert_trailing_nan(log_ret, h, f"{asset}/{horizon_id}/log_return")
    series_map[log_ret.name] = log_ret

    fwd_rv = RealizedVolLabeler(h).apply(bars)
    _assert_trailing_nan(fwd_rv, h, f"{asset}/{horizon_id}/fwd_rv")
    series_map[fwd_rv.name] = fwd_rv

    if asset in OPTIONS_ASSETS and label_cfg.vrp_enabled and iv is not None and not iv.empty:
        # Goal 2 labels — require Deribit DVOL at entry (t) only.
        vrp = VRPRealizationLabeler(h).apply(bars, iv)
        _assert_trailing_nan(vrp, h, f"{asset}/{horizon_id}/vrp")
        series_map[vrp.name] = vrp

        lookback = label_cfg.exceedance_quantile_lookback
        for delta in label_cfg.exceedance_deltas:
            # Causal strike proxy: quantile of *past* forward returns (shift in helper).
            q_call = causal_forward_return_quantile(bars["close"], h, 1.0 - delta, lookback)
            call_lab = ExceedanceLabeler(h, "call", delta=delta)
            call_s = call_lab.apply(bars, threshold_log_return=q_call)
            _assert_trailing_nan(call_s, h, f"{asset}/{horizon_id}/{call_lab.column_name}")
            series_map[call_lab.column_name] = call_s

            q_put = causal_forward_return_quantile(bars["close"], h, delta, lookback)
            put_lab = ExceedanceLabeler(h, "put", delta=delta)
            put_s = put_lab.apply(bars, threshold_log_return=q_put)
            _assert_trailing_nan(put_s, h, f"{asset}/{horizon_id}/{put_lab.column_name}")
            series_map[put_lab.column_name] = put_s

    return _melt_labels(
        timestamps=pd.DatetimeIndex(bars.index),
        asset=asset,
        horizon_id=horizon_id,
        series_map=series_map,
    )


def build_study_labels(cfg: StudyConfig, end: datetime | None = None) -> pd.DataFrame:
    """Long-format labels for all assets × horizons per LABEL_CATALOG."""
    end_dt = end or datetime.now(timezone.utc)
    start_dt = datetime.combine(cfg.splits.dev_start, datetime.min.time(), tzinfo=timezone.utc)

    bars_by_asset = {a: _load_ohlcv(a, start_dt, end_dt) for a in ASSETS}
    index = union_daily_index(bars_by_asset)
    if index.empty:
        raise RuntimeError("No OHLCV bars loaded for label build")

    iv_by_asset = {a: _load_dvol(a, start_dt, end_dt) for a in OPTIONS_ASSETS}

    all_rows: list[dict[str, object]] = []
    for horizon in cfg.horizons:
        h = horizon.horizon_bars
        hid = horizon.id.value
        for asset in ASSETS:
            bars = bars_by_asset[asset]
            if bars.empty:
                continue
            bars = bars.loc[bars.index.isin(index)]
            iv = iv_by_asset.get(asset) if asset in OPTIONS_ASSETS else None
            all_rows.extend(_labels_for_asset_horizon(bars, asset, hid, h, cfg, iv))

    if not all_rows:
        raise RuntimeError("Label build produced no rows")

    df = pd.DataFrame(all_rows)
    df = df.sort_values(["timestamp", "asset", "horizon_id", "label_name"]).reset_index(drop=True)
    return df


def write_labels_schema(df: pd.DataFrame, path) -> dict[str, object]:
    """Emit labels_schema.json summary."""
    names = sorted(df["label_name"].unique().tolist())
    schema: dict[str, object] = {
        "version": 1,
        "review_date": "2026-06-28",
        "row_count": len(df),
        "label_name_count": len(names),
        "label_names": names,
        "horizons": sorted(df["horizon_id"].unique().tolist()),
        "assets": sorted(df["asset"].unique().tolist()),
    }
    path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return schema


def validate_label_keys(df: pd.DataFrame) -> None:
    dupes = df.duplicated(subset=["timestamp", "asset", "horizon_id", "label_name"], keep=False)
    if dupes.any():
        n = int(dupes.sum())
        raise ValueError(f"Duplicate label keys: {n} rows")
