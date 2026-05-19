"""DuckDB model registry.

Table schema
------------
models(
    model_id             TEXT PRIMARY KEY,
    class                TEXT NOT NULL,
    feature_set_id       TEXT,
    feature_set_version  TEXT,
    labeler              TEXT,
    hparams_json         TEXT,
    train_start          TIMESTAMP,
    train_end            TIMESTAMP,
    metrics_json         TEXT,
    artifact_path        TEXT,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)

model_id generation
-------------------
Deterministic SHA-1 of (class, feature_set_id, feature_set_version, labeler, hparams)
so the same logical model always gets the same id — guaranteed across processes.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from cryoquant import config

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS models (
    model_id             TEXT PRIMARY KEY,
    class                TEXT NOT NULL,
    feature_set_id       TEXT,
    feature_set_version  TEXT,
    labeler              TEXT,
    hparams_json         TEXT,
    train_start          TIMESTAMPTZ,
    train_end            TIMESTAMPTZ,
    metrics_json         TEXT,
    artifact_path        TEXT,
    created_at           TIMESTAMPTZ DEFAULT current_timestamp
);
"""


def generate_model_id(
    model_class: str,
    feature_set_id: str | None = None,
    feature_set_version: str | None = None,
    labeler: str | None = None,
    hparams: dict[str, Any] | None = None,
) -> str:
    """Generate a deterministic model_id from its logical identity.

    The id is a 12-character hex prefix of SHA-1(canonical JSON).
    Same inputs always produce the same id, even across processes.
    """
    key = {
        "class": model_class,
        "feature_set_id": feature_set_id,
        "feature_set_version": feature_set_version,
        "labeler": labeler,
        "hparams": dict(sorted((hparams or {}).items())),
    }
    digest = hashlib.sha1(
        json.dumps(key, sort_keys=True, default=str).encode()
    ).hexdigest()
    return digest[:12]


def _conn(db_path: Path | None = None) -> duckdb.DuckDBPyConnection:
    path = db_path or config.CATALOG_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(_DDL)
    return con


def register(
    model_id: str,
    model_class: str,
    *,
    feature_set_id: str | None = None,
    feature_set_version: str | None = None,
    labeler: str | None = None,
    hparams: dict[str, Any] | None = None,
    train_start: datetime | None = None,
    train_end: datetime | None = None,
    metrics: dict[str, float] | None = None,
    artifact_path: str | Path | None = None,
    db_path: Path | None = None,
) -> None:
    """Insert or replace a model record.  Idempotent — safe to call twice."""
    con = _conn(db_path)
    con.execute(
        """
        INSERT OR REPLACE INTO models
            (model_id, class, feature_set_id, feature_set_version,
             labeler, hparams_json, train_start, train_end,
             metrics_json, artifact_path, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
        """,
        [
            model_id,
            model_class,
            feature_set_id,
            feature_set_version,
            labeler,
            json.dumps(hparams or {}),
            train_start,
            train_end,
            json.dumps({k: float(v) for k, v in (metrics or {}).items()}),
            str(artifact_path) if artifact_path is not None else None,
        ],
    )
    log.debug("Registered model %s (class=%s)", model_id, model_class)


def get_model(model_id: str, *, db_path: Path | None = None) -> dict | None:
    """Return raw registry row as a dict, or None if not found."""
    con = _conn(db_path)
    rows = con.execute(
        "SELECT * FROM models WHERE model_id = ?", [model_id]
    ).fetchall()
    if not rows:
        return None
    cols = [d[0] for d in con.description]
    return dict(zip(cols, rows[0]))


def list_models(*, db_path: Path | None = None) -> pd.DataFrame:
    """Return all registered models as a DataFrame, newest first."""
    con = _conn(db_path)
    return con.execute("SELECT * FROM models ORDER BY created_at DESC").df()
