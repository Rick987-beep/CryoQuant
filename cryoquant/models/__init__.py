"""CryoQuant models package.

Phase-3 model layer: baselines, tabular LightGBM, CV utilities, metrics,
and a DuckDB-backed model registry.
"""
from cryoquant.models.base import Model, ModelMetadata
from cryoquant.models.baselines import RuleModel, make_bear_burst, make_pullback, make_vol_burst
from cryoquant.models.cv import purged_kfold, walk_forward
from cryoquant.models.metrics import compute_metrics, reliability_diagram
from cryoquant.models.registry import generate_model_id, get_model, list_models, register
from cryoquant.models.tabular import TabularModel

__all__ = [
    # Protocol + metadata
    "Model",
    "ModelMetadata",
    # Baselines
    "RuleModel",
    "make_pullback",
    "make_vol_burst",
    "make_bear_burst",
    # Tabular
    "TabularModel",
    # CV
    "purged_kfold",
    "walk_forward",
    # Metrics
    "compute_metrics",
    "reliability_diagram",
    # Registry
    "register",
    "get_model",
    "list_models",
    "generate_model_id",
]
