"""Robustness metrics for backtest evaluation.

Functions:
    deflated_sharpe(sharpe, n_trials, n_obs, skew, kurt) -> float
    bootstrap_ci(trades, metric_fn, n, alpha) -> tuple[float, float]

Reference: Bailey & López de Prado (2014), "The Deflated Sharpe Ratio:
Correcting for Selection Bias, Backtest Overfitting, and Non-Normality".
"""
from __future__ import annotations

import math
from typing import Callable, Sequence

import numpy as np
from scipy.stats import norm


def deflated_sharpe(
    sharpe: float,
    n_trials: int,
    n_obs: int,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> float:
    """Return the Deflated Sharpe Ratio (DSR) probability.

    The DSR corrects the observed Sharpe ratio for:
      - Multiple testing (n_trials independent strategy variants tried)
      - Non-normality of returns (skewness and kurtosis)

    Parameters
    ----------
    sharpe:   Observed annualised Sharpe ratio of the strategy under review.
    n_trials: Number of independently tested strategy variants (including this one).
    n_obs:    Number of independent return observations used to compute the Sharpe.
    skew:     Skewness of the return series (0 = normal).
    kurt:     Kurtosis of the return series (3 = normal / mesokurtic).

    Returns
    -------
    Probability that the strategy's true SR > 0 after adjusting for
    selection bias.  Values close to 1 are good; < 0.95 suggests noise.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if n_obs < 2:
        raise ValueError("n_obs must be >= 2")

    # Expected maximum Sharpe ratio across n_trials (Eq. 3 in Bailey & LdP 2014)
    # Using the approximation: E[max SR] ≈ (1 - γ) * z* + γ * z**(1-1/n_trials)
    # where z* = Phi^{-1}(1 - 1/n_trials)
    if n_trials == 1:
        sr_bm = 0.0
    else:
        # Johansen's approximation for E[max of n_trials draws from N(0,1)]
        v = (1.0 - np.euler_gamma) * norm.ppf(1.0 - 1.0 / n_trials) + \
            np.euler_gamma * norm.ppf(1.0 - 1.0 / (n_trials * math.e))
        sr_bm = v

    # Per-period (non-annualised) Sharpe denominator
    # The correction factor for non-normality
    excess_kurt = kurt - 3.0
    inner = (
        (1.0 - skew * sharpe + ((excess_kurt - 1.0) / 4.0) * sharpe ** 2)
        / (n_obs - 1)
    )
    # Clamp to avoid sqrt of negative for extreme (skew, kurt, sharpe) combos
    correction = math.sqrt(max(inner, 1e-12))
    z = (sharpe - sr_bm) / correction
    return float(norm.cdf(z))


def bootstrap_ci(
    trades: Sequence[float],
    metric_fn: Callable[[np.ndarray], float],
    n: int = 10_000,
    alpha: float = 0.05,
    rng_seed: int | None = None,
) -> tuple[float, float]:
    """Compute a bootstrap confidence interval for a metric.

    Parameters
    ----------
    trades:     Sequence of per-trade P&L values (fractions).
    metric_fn:  Function that takes an ndarray of trade P&Ls and returns a scalar.
    n:          Number of bootstrap resamples.
    alpha:      Significance level; CI is ``[alpha/2, 1 - alpha/2]``.
    rng_seed:   Optional seed for reproducibility.

    Returns
    -------
    (lower, upper) bootstrap confidence interval.
    """
    arr = np.asarray(trades, dtype=float)
    rng = np.random.default_rng(rng_seed)
    samples = rng.choice(arr, size=(n, len(arr)), replace=True)
    values = np.array([metric_fn(row) for row in samples])
    lo = float(np.percentile(values, 100.0 * alpha / 2.0))
    hi = float(np.percentile(values, 100.0 * (1.0 - alpha / 2.0)))
    return lo, hi
