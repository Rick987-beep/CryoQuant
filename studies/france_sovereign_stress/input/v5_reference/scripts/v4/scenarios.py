"""Scenario paths for the OAT–Bund spread and the Bund leg from today to mid-2027, evaluated at any day t.

Regime (relief / grind / stress / contested) fixes the end spread anchor and its probability.
Relief and grind drift linearly from today's spread to the anchor over the whole horizon.
Stress and contested drift like grind (towards 150 bp) until an event day te ~ U(0, horizon), then widen to the
anchor over EVENT_DAYS and stay there. Spread noise: N(0, 25 bp) at the horizon, scaled by sqrt(t / horizon).

Bund yield change = −f · spread widening + noise: f = 0.22 in relief/grind, f ~ U(0.10, 0.70) in stress/contested
(f ≈ 0.23 is the 2018 pattern, f ≈ 0.67 a break-up flight to quality). OAT yield change = spread change + Bund change.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

REGIMES = [("relief", "Relief", 85, 0.15), ("grind", "Grind", 150, 0.50),
           ("stress", "Stress", 240, 0.30), ("contested", "Contested", 340, 0.05)]
HALF = (0.20, 0.625, 0.15, 0.025)
SPREAD_NOISE = 25.0
PRE_EVENT = 150.0
EVENT_DAYS = 21
F_CALM = 0.22
F_STRESS = (0.10, 0.70)
BUND_NOISE = (40.0, 25.0)
STRESS_2018_BUND = -24.0
BREAKUP_BUND = -70.0
NEVER = 1e9


@dataclass
class Paths:
    s0: float
    horizon: float
    regime: np.ndarray
    s_end: np.ndarray
    f: np.ndarray
    te: np.ndarray
    zs: np.ndarray
    zb: np.ndarray

    @property
    def n(self) -> int:
        return len(self.regime)

    @property
    def stressed(self) -> np.ndarray:
        return self.regime >= 2

    @property
    def t_exit(self) -> np.ndarray:
        return np.where(self.stressed, self.te + EVENT_DAYS, NEVER)

    def _widening(self, t):
        t = np.broadcast_to(np.asarray(t, dtype=float), self.regime.shape)
        frac = np.clip(t / self.horizon, 0, 1)
        calm = (self.s_end - self.s0) * frac
        pre = (PRE_EVENT - self.s0) * np.clip(np.minimum(t, self.te) / self.horizon, 0, 1)
        pre_te = (PRE_EVENT - self.s0) * np.clip(self.te / self.horizon, 0, 1)
        jump = np.clip((t - self.te) / EVENT_DAYS, 0, 1) * (self.s_end - self.s0 - pre_te)
        return np.where(self.stressed, pre + jump, calm), frac

    def ds(self, t) -> np.ndarray:
        w, frac = self._widening(t)
        return w + SPREAD_NOISE * np.sqrt(frac) * self.zs

    def db(self, t) -> np.ndarray:
        w, frac = self._widening(t)
        sig = np.where(self.stressed, BUND_NOISE[1], BUND_NOISE[0])
        return -np.where(self.stressed, self.f, F_CALM) * w + sig * np.sqrt(frac) * self.zb


def simulate(n: int, s0: float, horizon: float, seed: int = 23) -> Paths:
    rng = np.random.default_rng(seed)
    regime = rng.choice(4, n, p=[r[3] for r in REGIMES])
    stressed = regime >= 2
    s_end = np.array([r[2] for r in REGIMES], dtype=float)[regime]
    f = np.where(stressed, rng.uniform(*F_STRESS, n), F_CALM)
    te = np.where(stressed, rng.uniform(0, horizon, n), NEVER)
    return Paths(s0, horizon, regime, s_end, f, te, rng.standard_normal(n), rng.standard_normal(n))


def stress_grid(s0: float, horizon: float, fs, n_t: int = 40, spread: float = 240.0) -> Paths:
    """Deterministic stress paths: end spread fixed, f on a grid, event day on midpoints of U(0, horizon)."""
    fs = np.asarray(fs, dtype=float)
    te = (np.arange(n_t) + 0.5) / n_t * horizon
    ff, tt = (x.ravel() for x in np.meshgrid(fs, te, indexing="ij"))
    z = np.zeros(ff.shape)
    return Paths(s0, horizon, np.full(ff.shape, 2), np.full(ff.shape, spread), ff, tt, z, z)


def stress_fs(s0: float, spread: float = 240.0) -> dict:
    """Flight shares for the named stress paths: small rally, 2018 pattern, mid flight, break-up."""
    d = spread - s0
    return {"small rally (−10 bp)": 0.10, "2018 pattern (−24 bp)": -STRESS_2018_BUND / d,
            "mid flight (−45 bp)": 45.0 / d, "break-up (−70 bp)": -BREAKUP_BUND / d}
