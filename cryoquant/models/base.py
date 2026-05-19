"""Model protocol and metadata record."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


@runtime_checkable
class Model(Protocol):
    """Minimum interface every CryoQuant model must satisfy."""

    @property
    def model_id(self) -> str: ...

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None: ...

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return 1-D array of positive-class probabilities, shape (n_samples,)."""
        ...

    def save(self, path: Any) -> None: ...


class ModelMetadata(BaseModel):
    """Immutable record describing a trained model artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    model_class: str                              # "rule" | "lgbm" | "sklearn"
    feature_set_id: str | None = None
    feature_set_version: str | None = None
    labeler: str | None = None
    hparams: dict[str, Any] = Field(default_factory=dict)
    train_start: datetime | None = None
    train_end: datetime | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    artifact_path: str | None = None
