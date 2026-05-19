"""Signal protocol and concrete implementations.

Signal is the common interface over rules and trained models:

    BoolSignal   — fires True/False (entry/no-entry condition).
    StateSignal  — fires -1 / 0 / +1 (trend state or directional bias).
    ProbSignal   — fires [0, 1] probability from a trained model.

All three implement:
    emit(t, X)       -> BoolEmit | StateEmit | ProbEmit
    as_feature(df)   -> pd.Series  (vectorised application over a DataFrame)
"""
from __future__ import annotations

from typing import Callable, Literal, Protocol, runtime_checkable

import numpy as np
import pandas as pd

from cryocore.schemas import BoolEmit, ProbEmit, StateEmit


@runtime_checkable
class Signal(Protocol):
    """Minimal interface every CryoQuant signal must satisfy."""

    signal_id: str
    version: str

    def emit(self, t: pd.Timestamp, X: pd.DataFrame) -> BoolEmit | StateEmit | ProbEmit: ...

    def as_feature(self, df: pd.DataFrame) -> pd.Series: ...


# ---------------------------------------------------------------------------
# BoolSignal
# ---------------------------------------------------------------------------

class BoolSignal:
    """Rule-based binary signal.

    Parameters
    ----------
    signal_id:  Unique identifier.
    condition:  Callable(df) -> bool Series (one row per bar).
    version:    Semantic version string.
    symbol_str: "venue:ticker" used in emit records.
    """

    def __init__(
        self,
        signal_id: str,
        condition: Callable[[pd.DataFrame], pd.Series],
        version: str = "1",
        symbol_str: str = "",
    ) -> None:
        self.signal_id = signal_id
        self.version = version
        self.condition = condition
        self.symbol_str = symbol_str

    def emit(self, t: pd.Timestamp, X: pd.DataFrame) -> BoolEmit:
        row = X.loc[[t]] if t in X.index else X.tail(1)
        value = bool(self.condition(row).iloc[0])
        return BoolEmit(
            ts=t.to_pydatetime(),
            signal_id=self.signal_id,
            symbol_str=self.symbol_str,
            value=value,
        )

    def as_feature(self, df: pd.DataFrame) -> pd.Series:
        return self.condition(df).fillna(False).astype(bool).rename(self.signal_id)


# ---------------------------------------------------------------------------
# StateSignal
# ---------------------------------------------------------------------------

class StateSignal:
    """Three-state signal: -1 (bearish), 0 (neutral), +1 (bullish).

    Parameters
    ----------
    signal_id:  Unique identifier.
    state_fn:   Callable(df) -> int8 Series with values in {-1, 0, 1}.
    version:    Semantic version string.
    symbol_str: "venue:ticker" used in emit records.
    """

    def __init__(
        self,
        signal_id: str,
        state_fn: Callable[[pd.DataFrame], pd.Series],
        version: str = "1",
        symbol_str: str = "",
    ) -> None:
        self.signal_id = signal_id
        self.version = version
        self.state_fn = state_fn
        self.symbol_str = symbol_str

    def emit(self, t: pd.Timestamp, X: pd.DataFrame) -> StateEmit:
        row = X.loc[[t]] if t in X.index else X.tail(1)
        raw = int(self.state_fn(row).iloc[0])
        if raw not in (-1, 0, 1):
            raise ValueError(f"StateSignal state must be -1/0/1, got {raw}")
        return StateEmit(
            ts=t.to_pydatetime(),
            signal_id=self.signal_id,
            symbol_str=self.symbol_str,
            state=raw,  # type: ignore[arg-type]
        )

    def as_feature(self, df: pd.DataFrame) -> pd.Series:
        return self.state_fn(df).astype("int8").rename(self.signal_id)


# ---------------------------------------------------------------------------
# ProbSignal
# ---------------------------------------------------------------------------

class ProbSignal:
    """Probability signal backed by a trained model.

    Parameters
    ----------
    signal_id:         Unique identifier.
    model:             Any object with predict_proba(X) -> 1-D array.
    version:           Semantic version string.
    symbol_str:        "venue:ticker" used in emit records.
    horizon_h:         Forward horizon (hours) the model was trained for.
    direction:         "up" | "down" | "magnitude".
    default_threshold: Probability cut for binary decisions.
    """

    def __init__(
        self,
        signal_id: str,
        model: object,
        version: str = "1",
        symbol_str: str = "",
        horizon_h: int = 24,
        direction: Literal["up", "down", "magnitude"] = "magnitude",
        default_threshold: float = 0.5,
    ) -> None:
        self.signal_id = signal_id
        self.version = version
        self._model = model
        self.symbol_str = symbol_str
        self.horizon_h = horizon_h
        self.direction: Literal["up", "down", "magnitude"] = direction
        self.default_threshold = default_threshold

    def emit(self, t: pd.Timestamp, X: pd.DataFrame) -> ProbEmit:
        row = X.loc[[t]] if t in X.index else X.tail(1)
        prob = float(self._model.predict_proba(row)[0])  # type: ignore[union-attr]
        return ProbEmit(
            ts=t.to_pydatetime(),
            signal_id=self.signal_id,
            symbol_str=self.symbol_str,
            prob=prob,
            direction=self.direction,
            horizon_hours=self.horizon_h,
            threshold_used=self.default_threshold,
        )

    def as_feature(self, df: pd.DataFrame) -> pd.Series:
        probs = self._model.predict_proba(df)  # type: ignore[union-attr]
        return pd.Series(probs, index=df.index, name=self.signal_id, dtype=float)
