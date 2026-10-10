"""Forward scenario paths: right / wrong worlds (v5 event model + common RNGs).

Wrong world: driftless correlated Student-t walks of spread and Bund to the horizon.
Right world: same pre-event noise; from ``tc − event_bdays`` the spread is bridged to
exactly the target level at ``tc`` (doubled noise bridge); Bund falls by ``f × jump``
with ``f ~ U(lo, hi)``. Exit index is ``tc``.

v6 improvement vs v5: one shared noise draw per seed for all levels (and wrong world),
so level-to-level comparisons are on common random numbers. v5 used ``seed + i`` per level.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Sequence

import numpy as np

from src.calibrate import StockBeta, VolCalib


def business_days(start: date, end: date) -> np.ndarray:
    """Inclusive weekday dates from ``start`` through ``end``."""
    if end < start:
        raise ValueError(f"end {end} before start {start}")
    days = [
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() < 5
    ]
    return np.array(days, dtype=object)


def _student_t(rng: np.random.Generator, shape: tuple[int, ...], dof: float) -> np.ndarray:
    """Unit-variance Student-t draws (scale so Var=1 for dof>2)."""
    if dof <= 2:
        raise ValueError("Student-t dof must be > 2 for finite variance")
    return rng.standard_t(dof, shape) * np.sqrt((dof - 2) / dof)


@dataclass
class World:
    """Path bundle in cumulative bp changes from ``s0`` / Bund start.

    ``ds[i, t]`` / ``db[i, t]`` are cumulative changes through business day index ``t``.
    Level path is ``s0 + ds``. Exit at ``tc[i]`` (index into ``days``).
    """

    s0: float
    days: np.ndarray
    ds: np.ndarray
    db: np.ndarray
    tc: np.ndarray
    f: np.ndarray
    level: float | None
    seed: int

    @property
    def n(self) -> int:
        return int(self.ds.shape[0])

    @property
    def T(self) -> int:
        return int(self.ds.shape[1] - 1)

    def spread_level(self) -> np.ndarray:
        """Absolute spread in bp: ``s0 + ds``."""
        return self.s0 + self.ds

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "n": self.n,
            "T": self.T,
            "s0": self.s0,
            "level": self.level,
            "seed": self.seed,
            "start": str(self.days[0]),
            "end": str(self.days[-1]),
            "mean_tc": float(self.tc.mean()),
            "ds_end_mean": float(self.ds[np.arange(self.n), self.tc].mean()),
            "spread_at_exit_mean": float((self.s0 + self.ds[np.arange(self.n), self.tc]).mean()),
        }
        if self.level is not None:
            at = self.s0 + self.ds[np.arange(self.n), self.tc]
            out["hit_level_max_err"] = float(np.max(np.abs(at - self.level)))
            out["f_mean"] = float(self.f.mean())
            out["f_min"] = float(self.f.min())
            out["f_max"] = float(self.f.max())
        return out


@dataclass(frozen=True)
class ScenarioConfig:
    n_paths: int = 10_000
    seed: int = 11
    event_bdays: int = 15
    event_vol_mult: float = 2.0
    bund_flight_share: tuple[float, float] = (0.10, 0.70)
    dof: float = 4.0
    end: date = date(2027, 7, 1)

    @classmethod
    def from_study_config(cls, cfg: dict[str, Any]) -> ScenarioConfig:
        sim = cfg["simulation"]
        lo, hi = sim["bund_flight_share"]
        return cls(
            n_paths=int(sim["n_paths"]),
            seed=int(sim["seed"]),
            event_bdays=int(sim["event_bdays"]),
            event_vol_mult=float(sim["event_vol_mult"]),
            bund_flight_share=(float(lo), float(hi)),
            dof=float(sim["noise"]["dof"]),
            end=date.fromisoformat(cfg["horizon"]["end"]),
        )


@dataclass
class NoiseDraw:
    """Shared random draws for common-RNG worlds."""

    es: np.ndarray  # (n, T) spread increments
    eb: np.ndarray  # (n, T) Bund increments
    tc: np.ndarray  # (n,) completion indices for right worlds
    f: np.ndarray  # (n,) Bund flight share
    bridge_raw: np.ndarray  # (n, event_bdays) unit-t then scaled outside


def draw_noise(
    vol: VolCalib,
    *,
    n: int,
    T: int,
    event_bdays: int,
    seed: int,
    dof: float,
    f_range: tuple[float, float],
) -> NoiseDraw:
    """One RNG stream: correlated walks + right-world timing / flight / bridge noise."""
    rng = np.random.default_rng(seed)
    es = vol.sig_s * _student_t(rng, (n, T), dof)
    z = _student_t(rng, (n, T), dof)
    eb = vol.sig_b * (vol.rho * es / vol.sig_s + np.sqrt(max(0.0, 1.0 - vol.rho**2)) * z)
    tc = rng.integers(event_bdays, T + 1, n)
    f = rng.uniform(f_range[0], f_range[1], n)
    bridge_raw = _student_t(rng, (n, event_bdays), dof)
    return NoiseDraw(es=es, eb=eb, tc=tc, f=f, bridge_raw=bridge_raw)


def _wrong_from_noise(s0: float, days: np.ndarray, noise: NoiseDraw, seed: int) -> World:
    n, T = noise.es.shape
    ds = np.concatenate([np.zeros((n, 1)), np.cumsum(noise.es, axis=1)], axis=1)
    db = np.concatenate([np.zeros((n, 1)), np.cumsum(noise.eb, axis=1)], axis=1)
    return World(
        s0=s0,
        days=days,
        ds=ds,
        db=db,
        tc=np.full(n, T, dtype=int),
        f=np.zeros(n),
        level=None,
        seed=seed,
    )


def _right_from_noise(
    s0: float,
    days: np.ndarray,
    noise: NoiseDraw,
    *,
    level: float,
    vol: VolCalib,
    event_bdays: int,
    event_vol_mult: float,
    seed: int,
) -> World:
    n, T = noise.es.shape
    ds = np.concatenate([np.zeros((n, 1)), np.cumsum(noise.es, axis=1)], axis=1)
    db = np.concatenate([np.zeros((n, 1)), np.cumsum(noise.eb, axis=1)], axis=1)

    tc = noise.tc
    f = noise.f
    ts = tc - event_bdays
    rows = np.arange(n)
    jump = (level - s0) - ds[rows, ts]

    k = np.arange(T + 1)[None, :] - ts[:, None]
    frac = np.clip(k / event_bdays, 0, 1)

    walk = vol.sig_s * event_vol_mult * np.cumsum(noise.bridge_raw, axis=1)
    bridge = walk - (np.arange(1, event_bdays + 1) / event_bdays)[None, :] * walk[:, -1:]
    noise_pad = np.zeros((n, T + 1))
    idx = ts[:, None] + np.arange(1, event_bdays + 1)[None, :]
    noise_pad[rows[:, None], idx] = bridge
    in_event = (k > 0) & (k <= event_bdays)

    ds = np.where(
        k <= 0,
        ds,
        ds[rows, ts][:, None] + jump[:, None] * frac + np.where(in_event, noise_pad, 0.0),
    )
    db = db - (f * jump)[:, None] * frac
    return World(s0=s0, days=days, ds=ds, db=db, tc=tc, f=f, level=float(level), seed=seed)


def simulate_worlds(
    vol: VolCalib,
    *,
    s0: float,
    start: date,
    levels: Sequence[float],
    cfg: ScenarioConfig,
) -> dict[float | None, World]:
    """Wrong world + right worlds for each level, on **common random numbers**.

    Keys: each level in ``levels``, plus ``None`` for the wrong world.
    """
    days = business_days(start, cfg.end)
    if len(days) < cfg.event_bdays + 2:
        raise ValueError("horizon too short for event window")
    T = len(days) - 1
    noise = draw_noise(
        vol,
        n=cfg.n_paths,
        T=T,
        event_bdays=cfg.event_bdays,
        seed=cfg.seed,
        dof=cfg.dof,
        f_range=cfg.bund_flight_share,
    )
    out: dict[float | None, World] = {
        None: _wrong_from_noise(s0, days, noise, cfg.seed),
    }
    for level in levels:
        out[float(level)] = _right_from_noise(
            s0,
            days,
            noise,
            level=float(level),
            vol=vol,
            event_bdays=cfg.event_bdays,
            event_vol_mult=cfg.event_vol_mult,
            seed=cfg.seed,
        )
    return out


def stock_cum_returns(
    world: World,
    beta: StockBeta,
    *,
    seed_offset: int = 1000,
) -> np.ndarray:
    """Cumulative log returns: β_s Δspread + β_b ΔBund + idio Student-t (v5-style)."""
    rng = np.random.default_rng(world.seed + seed_offset)
    inc = beta.beta_s * np.diff(world.ds, axis=1) + beta.beta_b * np.diff(world.db, axis=1)
    dof = 4.0
    inc = inc + beta.idio * _student_t(rng, inc.shape, dof)
    return np.concatenate([np.zeros((world.n, 1)), np.cumsum(inc, axis=1)], axis=1)
