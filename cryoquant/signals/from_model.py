"""Adapters that wrap trained models as signals.

    bool_from_rule(rule_model, name)           -> BoolSignal
    prob_from_model(model, ...)                -> ProbSignal
    state_from_model(model, up_thr, down_thr)  -> StateSignal
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from cryoquant.signals.base import BoolSignal, ProbSignal, StateSignal


def bool_from_rule(rule_model: object, name: str | None = None) -> BoolSignal:
    """Wrap a RuleModel's condition as a BoolSignal.

    The rule must have a `condition` attribute that is callable.
    """
    condition = getattr(rule_model, "condition", None)
    if condition is None or not callable(condition):
        raise TypeError("rule_model must have a callable .condition attribute")
    signal_id = name or getattr(rule_model, "name", getattr(rule_model, "model_id", "rule"))
    return BoolSignal(signal_id=signal_id, condition=condition)


def prob_from_model(
    model: object,
    horizon_h: int = 24,
    default_threshold: float = 0.5,
    direction: Literal["up", "down", "magnitude"] = "magnitude",
    signal_id: str | None = None,
) -> ProbSignal:
    """Wrap any model with predict_proba() as a ProbSignal."""
    sid = signal_id or getattr(model, "model_id", "model")
    return ProbSignal(
        signal_id=sid,
        model=model,
        horizon_h=horizon_h,
        direction=direction,
        default_threshold=default_threshold,
    )


def state_from_model(
    model: object,
    up_thr: float = 0.6,
    down_thr: float = 0.4,
    signal_id: str | None = None,
) -> StateSignal:
    """Derive a three-state signal from a probability model.

    Bars where prob >= up_thr → +1, <= down_thr → -1, otherwise → 0.
    """
    sid = signal_id or getattr(model, "model_id", "state")

    def _state_fn(df: pd.DataFrame) -> pd.Series:
        probs = model.predict_proba(df)  # type: ignore[union-attr]
        states = np.where(probs >= up_thr, 1, np.where(probs <= down_thr, -1, 0))
        return pd.Series(states, index=df.index, dtype="int8")

    return StateSignal(signal_id=sid, state_fn=_state_fn)
