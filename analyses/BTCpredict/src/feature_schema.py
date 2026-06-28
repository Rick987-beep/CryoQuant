"""Feature schema from features.yaml — column registry and validation.

Bridges the signed-off catalog (``FEATURE_CATALOG.md`` / ``features.yaml``) to
the built panel:

  - ``catalog_feature_columns()`` — expected column names (``{a}`` expanded).
  - ``finalize_panel(df)`` — drop builder extras, NaN-fill unavailable cols.
  - ``write_features_schema()`` — emit ``data/features_schema.json`` after build.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.paths import ANALYSIS_ROOT

ASSETS = ("btc", "eth", "sol")
META_COLS = ("timestamp", "asset", "options_source")


def features_yaml_path() -> Path:
    return ANALYSIS_ROOT / "features.yaml"


def load_features_yaml(path: Path | None = None) -> dict[str, Any]:
    p = path or features_yaml_path()
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def expand_asset_placeholders(name: str) -> list[str]:
    if "{a}" in name:
        return [name.replace("{a}", a) for a in ASSETS]
    return [name]


def catalog_feature_columns(yaml_doc: dict[str, Any] | None = None) -> list[str]:
    """Flat ordered list of feature column names from features.yaml."""
    doc = yaml_doc or load_features_yaml()
    names: list[str] = []
    for tier in ("core", "extended"):
        groups = doc.get("columns", {}).get(tier, {})
        for group_cols in groups.values():
            for col in group_cols:
                names.extend(expand_asset_placeholders(col))
    return names


def column_tags(yaml_doc: dict[str, Any] | None = None) -> dict[str, str]:
    """Map column name → core | extended."""
    doc = yaml_doc or load_features_yaml()
    tags: dict[str, str] = {}
    for tier in ("core", "extended"):
        groups = doc.get("columns", {}).get(tier, {})
        for group_cols in groups.values():
            for col in group_cols:
                for name in expand_asset_placeholders(col):
                    tags[name] = tier
    return tags


def build_schema_dict(panel_columns: list[str], yaml_doc: dict[str, Any] | None = None) -> dict[str, Any]:
    doc = yaml_doc or load_features_yaml()
    tags = column_tags(doc)
    features = [c for c in panel_columns if c not in META_COLS]
    missing = [c for c in catalog_feature_columns(doc) if c not in panel_columns]
    extra = [c for c in features if c not in tags and c not in META_COLS]
    return {
        "version": doc.get("version", 1),
        "review_status": doc.get("review_status"),
        "review_date": doc.get("review_date"),
        "panel_index": doc.get("panel", {}).get("index", ["timestamp", "asset"]),
        "column_count": len(features),
        "tier_counts": doc.get("tier_counts"),
        "columns": [
            {"name": c, "tag": tags.get(c, "unknown"), "dtype": "float64"}
            for c in sorted(features)
        ],
        "meta_columns": list(META_COLS),
        "missing_from_panel": missing,
        "extra_in_panel": extra,
    }


def write_features_schema(panel_columns: list[str], out_path: Path) -> dict[str, Any]:
    schema = build_schema_dict(panel_columns)
    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return schema


def ordered_panel_columns(yaml_doc: dict[str, Any] | None = None) -> list[str]:
    """Column order: timestamp, asset, catalog features, options_source."""
    features = catalog_feature_columns(yaml_doc)
    meta_lead = [c for c in META_COLS if c in ("timestamp", "asset")]
    meta_tail = [c for c in META_COLS if c not in meta_lead]
    feat = [c for c in features if c not in META_COLS]
    return meta_lead + feat + meta_tail


def finalize_panel(df: pd.DataFrame, yaml_doc: dict[str, Any] | None = None) -> pd.DataFrame:
    """Ensure exact catalog columns; drop TrendFeatures extras; NaN-fill unavailable."""
    import numpy as np

    doc = yaml_doc or load_features_yaml()
    catalog = catalog_feature_columns(doc)
    missing = [c for c in catalog if c not in df.columns]
    if missing:
        fill = pd.DataFrame(np.nan, index=df.index, columns=missing)
        out = pd.concat([df, fill], axis=1)
    else:
        out = df.copy()
    return out[ordered_panel_columns(doc)]


def validate_panel_columns(df_columns: list[str], yaml_doc: dict[str, Any] | None = None) -> list[str]:
    """Return list of catalog columns missing from the panel."""
    expected = set(catalog_feature_columns(yaml_doc))
    present = set(df_columns)
    return sorted(expected - present)
