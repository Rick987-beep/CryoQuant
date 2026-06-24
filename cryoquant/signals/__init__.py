"""CryoQuant signals package.

Phase-4 signal publication layer.
"""
from cryoquant.signals.base import BoolSignal, ProbSignal, ScoreSignal, Signal, StateSignal
from cryoquant.signals.from_model import bool_from_rule, prob_from_model, state_from_model
from cryoquant.signals.thresholds import pick_threshold

__all__ = [
    # Protocol + concrete signals
    "Signal",
    "BoolSignal",
    "ScoreSignal",
    "StateSignal",
    "ProbSignal",
    # Adapters
    "bool_from_rule",
    "prob_from_model",
    "state_from_model",
    # Threshold selection
    "pick_threshold",
]
