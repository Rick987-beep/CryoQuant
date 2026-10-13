"""Vol-fit grounding tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.calibrate import VolCalib
from src.vol_fit import fit_vol_vs_spread, flat_vol_fit


def _synthetic_yields(n: int = 300, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-01", periods=n)
    # Wider spreads → higher vol
    level = 80 + np.cumsum(rng.normal(0, 2.0, n))
    level = np.clip(level, 40, 200)
    return pd.DataFrame(
        {"oat10": 3.5 + level / 100, "bund10": 2.5, "spread_bp": level},
        index=idx,
    )


def test_fit_produces_finite_mult():
    y = _synthetic_yields()
    vol = VolCalib(sig_s=2.5, sig_b=3.0, rho=0.1, window=126, n_obs=126)
    fit = fit_vol_vs_spread(y, vol=vol)
    m = fit.atm_mult(np.array([0.0, 50.0, 100.0]), s0=100.0)
    assert m.shape == (3,)
    assert np.all(np.isfinite(m))
    assert np.all(m <= fit.max_obs_mult + 1e-9)


def test_flat_iv_is_one():
    y = _synthetic_yields()
    fit = fit_vol_vs_spread(y, vol=VolCalib(2.5, 3.0, 0.1, 126, 126))
    flat = flat_vol_fit(fit)
    m = flat.atm_mult(np.array([0.0, 80.0]), s0=100.0)
    assert np.allclose(m, 1.0)
