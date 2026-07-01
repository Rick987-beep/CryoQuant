"""Join features + labels into (X, y) and select feature columns for Phase 4."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from src.config_models import AssetId, ModelHeadId
from src.feature_schema import column_tags, expand_asset_placeholders, load_features_yaml
from src.paths import data_dir
from src.training_register import load_training_register

if TYPE_CHECKING:
    from src.config_models import StudyConfig

log = logging.getLogger(__name__)

META_COLS = frozenset({"timestamp", "asset", "options_source"})
ASSET_PREFIXES = {"BTC": "btc_", "ETH": "eth_", "SOL": "sol_"}


def _features_path() -> Path:
    return data_dir() / "features.parquet"


def _labels_path() -> Path:
    return data_dir() / "labels.parquet"


def load_features_frame(cfg: StudyConfig) -> pd.DataFrame:
    df = pd.read_parquet(_features_path())
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    holdout = pd.Timestamp(cfg.splits.holdout_start, tz="UTC")
    return df[df["timestamp"] < holdout].copy()


def load_features_all(cfg: StudyConfig) -> pd.DataFrame:
    df = pd.read_parquet(_features_path())
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def load_features_holdout(cfg: StudyConfig) -> pd.DataFrame:
    holdout = pd.Timestamp(cfg.splits.holdout_start, tz="UTC")
    return load_features_all(cfg)[load_features_all(cfg)["timestamp"] >= holdout].copy()


def load_features_slice(
    cfg: StudyConfig,
    *,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    df = load_features_all(cfg)
    if start is not None:
        df = df[df["timestamp"] >= start]
    if end is not None:
        df = df[df["timestamp"] < end]
    return df.copy()


def load_label_series(
    cfg: StudyConfig,
    *,
    asset: AssetId,
    horizon_id: str,
    label_name: str,
    dev_only: bool = True,
) -> pd.Series:
    df = pd.read_parquet(_labels_path())
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc="UTC")
    holdout = pd.Timestamp(cfg.splits.holdout_start, tz="UTC")
    sub = df[
        (df["asset"] == asset.value)
        & (df["horizon_id"] == horizon_id)
        & (df["label_name"] == label_name)
    ]
    if dev_only:
        sub = sub[sub["timestamp"] < holdout]
    if sub.empty:
        return pd.Series(dtype=float, name=label_name)
    s = sub.set_index("timestamp")["value"].sort_index()
    s.name = label_name
    return s


def build_training_frame(
    cfg: StudyConfig,
    *,
    asset: AssetId,
    horizon_id: str,
    label_name: str,
) -> tuple[pd.DataFrame, pd.Series]:
    """Join features.parquet + labels (dev slice). Index = timestamp UTC."""
    feat = load_features_frame(cfg)
    feat = feat[feat["asset"] == asset.value].set_index("timestamp").sort_index()
    y = load_label_series(cfg, asset=asset, horizon_id=horizon_id, label_name=label_name)
    if y.empty:
        return pd.DataFrame(), y
    X = feat.drop(columns=[c for c in feat.columns if c in META_COLS or c == "asset"], errors="ignore")
    aligned = X.join(y, how="inner").dropna(subset=[label_name])
    y_out = aligned[label_name]
    X_out = aligned.drop(columns=[label_name])
    return X_out, y_out


def _expand_hint_groups(yaml_doc: dict, group_paths: list[str]) -> list[str]:
    cols: list[str] = []
    for path in group_paths:
        tier, group = path.split(".", 1)
        for col in yaml_doc.get("columns", {}).get(tier, {}).get(group, []):
            cols.extend(expand_asset_placeholders(col))
    return cols


def _global_columns(all_cols: list[str]) -> list[str]:
    out = []
    for c in all_cols:
        if c in META_COLS:
            continue
        if c.startswith(("btc_", "eth_", "sol_")):
            continue
        out.append(c)
    return out


def _asset_trend_columns(all_cols: list[str], asset: AssetId) -> list[str]:
    prefix = ASSET_PREFIXES[asset]
    return [c for c in all_cols if c.startswith(prefix)]


def select_feature_columns(
    cfg: StudyConfig,
    asset: AssetId,
    head: ModelHeadId,
    *,
    register: dict | None = None,
    yaml_doc: dict | None = None,
) -> list[str]:
    """Core tag + head hints + never_drop; asset scope from training register."""
    reg = register or load_training_register()
    doc = yaml_doc or load_features_yaml()
    tags = column_tags(doc)
    core_cols = [c for c, t in tags.items() if t == "core"]

    hints = doc.get("phase4_defaults", {}).get("head_hints", {})
    if head in (ModelHeadId.DIRECTIONAL, ModelHeadId.LOG_RETURN_BENCH):
        hint_key = "goal1_directional"
    else:
        hint_key = "goal2_vol_exceedance"

    hinted = _expand_hint_groups(doc, hints.get(hint_key, []))
    pool = [c for c in hinted if c in core_cols]

    # SOL uses tighter asset scope
    if asset == AssetId.SOL and head in (ModelHeadId.DIRECTIONAL, ModelHeadId.LOG_RETURN_BENCH):
        globals_ = _global_columns(pool)
        asset_trend = _asset_trend_columns(pool, asset)
        pool = globals_ + asset_trend
    elif head in (ModelHeadId.REALIZED_VOL, ModelHeadId.DISTRIBUTIONAL):
        globals_ = _global_columns(pool)
        asset_trend = _asset_trend_columns(pool, asset)
        prefix = ASSET_PREFIXES[asset]
        options = [
            c
            for c in core_cols
            if c.startswith(prefix) and any(k in c for k in ("dvol", "iv_minus", "rv_"))
        ]
        pool = list(dict.fromkeys(globals_ + asset_trend + options))

    never_drop = reg.get("feature_policy", {}).get("never_drop", [])
    for col in never_drop:
        if col not in pool:
            pool.append(col)

    # Only columns that exist in catalog
    catalog = set(tags.keys())
    pool = [c for c in pool if c in catalog or c in never_drop]
    return list(dict.fromkeys(pool))


def correlation_prune(
    X: pd.DataFrame,
    columns: list[str],
    *,
    threshold: float = 0.95,
    max_columns: int,
    protected: list[str] | None = None,
) -> list[str]:
    """Drop one from each highly correlated pair; keep protected columns."""
    protected = set(protected or [])
    cols = [c for c in columns if c in X.columns]
    if len(cols) <= 1:
        return cols[:max_columns]

    sub = X[cols].dropna()
    if len(sub) < 10:
        return cols[:max_columns]

    corr = sub.corr().abs()
    drop: set[str] = set()
    for i, ci in enumerate(cols):
        if ci in drop or ci in protected:
            continue
        for cj in cols[i + 1 :]:
            if cj in drop or cj in protected:
                continue
            if corr.loc[ci, cj] >= threshold:
                drop.add(cj)

    kept = [c for c in cols if c not in drop]
    if len(kept) > max_columns:
        # Drop non-protected extended first — all core here; trim tail
        prot = [c for c in kept if c in protected]
        rest = [c for c in kept if c not in protected]
        kept = prot + rest[: max(0, max_columns - len(prot))]
    return kept


def valid_columns_for_train(
    X_train: pd.DataFrame,
    columns: list[str],
    *,
    min_valid_frac: float = 0.5,
    protected: list[str] | None = None,
) -> list[str]:
    """Keep columns with enough non-NaN values on the train slice."""
    protected = set(protected or [])
    kept: list[str] = []
    for c in columns:
        if c not in X_train.columns:
            continue
        frac = float(X_train[c].notna().mean())
        if frac <= 0:
            continue
        if frac >= min_valid_frac or c in protected:
            kept.append(c)
    return kept


class FoldScaler:
    """Train-only winsor + StandardScaler (P4-T04)."""

    def __init__(
        self,
        feature_cols: list[str],
        winsor_percentiles: tuple[float, float] = (1.0, 99.0),
    ) -> None:
        self.feature_cols = feature_cols
        self.winsor = winsor_percentiles
        self.scaler = StandardScaler()
        self._bounds: dict[str, tuple[float, float]] = {}

    def fit_transform(self, X: pd.DataFrame, y: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
        Xs = X[self.feature_cols].astype(float).copy()
        self._bounds = {}
        for c in self.feature_cols:
            lo, hi = np.nanpercentile(Xs[c], self.winsor)
            self._bounds[c] = (float(lo), float(hi))
            Xs[c] = Xs[c].clip(lo, hi)
        mask = Xs.notna().all(axis=1) & y.notna()
        Xs = Xs.loc[mask]
        y = y.loc[Xs.index]
        if Xs.empty:
            return Xs, y
        scaled = self.scaler.fit_transform(Xs)
        return pd.DataFrame(scaled, index=Xs.index, columns=self.feature_cols), y

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        Xs = X[self.feature_cols].astype(float).copy()
        for c in self.feature_cols:
            lo, hi = self._bounds.get(c, (-np.inf, np.inf))
            Xs[c] = Xs[c].clip(lo, hi)
        mask = Xs.notna().all(axis=1)
        Xs = Xs.loc[mask]
        if Xs.empty:
            return Xs
        scaled = self.scaler.transform(Xs)
        return pd.DataFrame(scaled, index=Xs.index, columns=self.feature_cols)


def select_features_for_run(
    cfg: StudyConfig,
    X: pd.DataFrame,
    *,
    asset: AssetId,
    head: ModelHeadId,
    register: dict | None = None,
) -> list[str]:
    reg = register or load_training_register()
    fp = reg.get("feature_policy", {})
    candidates = select_feature_columns(cfg, asset, head, register=reg)
    pruned = correlation_prune(
        X,
        candidates,
        threshold=float(fp.get("correlation_drop_threshold", 0.95)),
        max_columns=cfg.feature_budget_max,
        protected=fp.get("never_drop", []),
    )
    log.debug("Feature selection %s/%s: %d → %d cols", asset, head, len(candidates), len(pruned))
    return pruned
