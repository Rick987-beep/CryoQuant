"""CryoTrader adapter.

to_cryotrader_condition(signal, threshold) -> Callable

Returns a callable compatible with CryoTrader's entry-condition interface:

    condition(ctx) -> bool

where ``ctx`` is a SimpleNamespace (or any object) with:
    ctx.features  — dict or pd.Series of feature values for the current bar
    ctx.timestamp — datetime or pd.Timestamp of the bar open

Usage::

    from types import SimpleNamespace
    cond = to_cryotrader_condition(pullback_signal)
    ctx = SimpleNamespace(features={"ret_4h": 1.5, "ret_1h": -0.7, ...}, timestamp=t)
    if cond(ctx):
        # enter trade
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from cryoquant.signals.base import BoolSignal, ProbSignal, StateSignal


def to_cryotrader_condition(
    signal: BoolSignal | ProbSignal | StateSignal,
    threshold: float = 0.5,
) -> Callable:
    """Wrap *signal* as a CryoTrader EntryCondition callable.

    Args:
        signal:    A BoolSignal, ProbSignal, or StateSignal.
        threshold: Probability cut-off used when *signal* is a ProbSignal.
                   For BoolSignal / StateSignal the threshold is ignored.

    Returns:
        condition(ctx) -> bool
            ctx.features  dict or pd.Series  — feature snapshot
            ctx.timestamp datetime            — bar timestamp (not used for prediction)
    """

    def _to_df(ctx) -> pd.DataFrame:
        feats = getattr(ctx, "features", {})
        if isinstance(feats, pd.DataFrame):
            return feats
        if isinstance(feats, pd.Series):
            return feats.to_frame().T
        return pd.DataFrame([feats])

    if isinstance(signal, BoolSignal):
        def _bool_cond(ctx) -> bool:
            df = _to_df(ctx)
            if df.empty:
                return False
            return bool(signal.condition(df).iloc[0])
        return _bool_cond

    if isinstance(signal, ProbSignal):
        def _prob_cond(ctx) -> bool:
            df = _to_df(ctx)
            if df.empty:
                return False
            prob = float(signal._model.predict_proba(df)[0])  # type: ignore[union-attr]
            return prob >= threshold
        return _prob_cond

    if isinstance(signal, StateSignal):
        def _state_cond(ctx) -> bool:
            df = _to_df(ctx)
            if df.empty:
                return False
            return int(signal.state_fn(df).iloc[0]) == 1
        return _state_cond

    raise TypeError(f"Unsupported signal type: {type(signal)}")
