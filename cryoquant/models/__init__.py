"""CryoQuant models package.

Model layer: baselines, tabular LightGBM, CV utilities, metrics, validation,
and a DuckDB-backed model registry.
"""
from cryoquant.models.base import Model, ModelMetadata
from cryoquant.models.baselines import (
    NaiveDirectional,
    NaiveRandomWalk,
    RidgePredictor,
    RollingMeanReturn,
    RuleModel,
    make_bear_burst,
    make_pullback,
    make_vol_burst,
)
from cryoquant.models.cv import purged_kfold, walk_forward
from cryoquant.models.fit_loop import FoldResult, concat_oos_preds, concat_oos_probs, walk_forward_fit
from cryoquant.models.metrics import compute_metrics, compute_regression_metrics, qlike, reliability_diagram
from cryoquant.models.registry import generate_model_id, get_model, list_models, register
from cryoquant.models.tabular import QuantileModel, TabularModel, TabularRegressor
from cryoquant.models.validation import (
    exceedance_prob_from_quantiles,
    leakage_feature_scan,
    permutation_test,
)
from cryoquant.models.vol_baselines import HAR_RVPredictor

# Backward-compatible alias for leakage_feature_scan
leakage_audit = leakage_feature_scan

__all__ = [
    # Protocol + metadata
    "Model",
    "ModelMetadata",
    # Baselines
    "RuleModel",
    "make_pullback",
    "make_vol_burst",
    "make_bear_burst",
    "NaiveRandomWalk",
    "RollingMeanReturn",
    "RidgePredictor",
    "NaiveDirectional",
    "HAR_RVPredictor",
    # Tabular
    "TabularModel",
    "TabularRegressor",
    "QuantileModel",
    # CV + fit loop
    "purged_kfold",
    "walk_forward",
    "walk_forward_fit",
    "FoldResult",
    "concat_oos_probs",
    "concat_oos_preds",
    # Metrics
    "compute_metrics",
    "compute_regression_metrics",
    "reliability_diagram",
    "qlike",
    # Validation
    "leakage_feature_scan",
    "leakage_audit",
    "permutation_test",
    "exceedance_prob_from_quantiles",
    # Registry
    "register",
    "get_model",
    "list_models",
    "generate_model_id",
]
