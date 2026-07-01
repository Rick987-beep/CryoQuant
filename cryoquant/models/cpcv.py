"""Combinatorial Purged Cross-Validation — stub for future PBO work."""
from __future__ import annotations

_DEFER_MSG = "CPCV and PBO are not implemented yet; use permutation_test and deflated_sharpe for now."


class CPCVNotImplemented(NotImplementedError):
    """Raised when CPCV/PBO is requested before implementation."""


def combinatorial_purged_cv(*args, **kwargs):
    """Stub — full CPCV split generation is not yet available."""
    raise CPCVNotImplemented(f"combinatorial_purged_cv is not implemented. {_DEFER_MSG}")


def probability_of_backtest_overfitting(*args, **kwargs):
    """Stub — probability of backtest overfitting is not yet available."""
    raise CPCVNotImplemented(f"probability_of_backtest_overfitting is not implemented. {_DEFER_MSG}")
