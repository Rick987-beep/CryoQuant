"""Append-only trial log — re-export shim."""
from cryoquant.backtest.trial_log import (
    append_training_session,
    append_trial,
    count_trials,
    trial_log_path,
)

__all__ = [
    "append_training_session",
    "append_trial",
    "count_trials",
    "trial_log_path",
]
