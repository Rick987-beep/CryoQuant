"""Phase 3 scenario generator tests (no network)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from src.calibrate import VolCalib, calibrate_vol
from src.data.reference import load_yields_daily
from src.scenarios import ScenarioConfig, business_days, simulate_worlds, stock_cum_returns
from src.calibrate import stock_betas
from src.data.reference import load_stocks_daily


@pytest.fixture(scope="module")
def vol() -> VolCalib:
    return calibrate_vol(load_yields_daily(), window=126)


@pytest.fixture(scope="module")
def small_cfg() -> ScenarioConfig:
    return ScenarioConfig(
        n_paths=200,
        seed=11,
        event_bdays=15,
        event_vol_mult=2.0,
        bund_flight_share=(0.10, 0.70),
        dof=4.0,
        end=date(2027, 7, 1),
    )


def test_business_days_weekdays_only() -> None:
    days = business_days(date(2026, 10, 9), date(2026, 10, 16))
    assert all(d.weekday() < 5 for d in days)
    assert days[0] == date(2026, 10, 9)
    assert days[-1] == date(2026, 10, 16)


def test_wrong_world_driftless_and_exits_at_horizon(vol: VolCalib, small_cfg: ScenarioConfig) -> None:
    worlds = simulate_worlds(
        vol, s0=138.0, start=date(2026, 10, 9), levels=[300.0], cfg=small_cfg
    )
    w = worlds[None]
    assert w.level is None
    assert np.all(w.tc == w.T)
    # Mean terminal change should be near 0 (driftless); loose bound for n=200
    assert abs(float(w.ds[:, -1].mean())) < 3.0 * vol.sig_s * np.sqrt(w.T) / np.sqrt(w.n) * 4


def test_right_world_hits_level_on_tc(vol: VolCalib, small_cfg: ScenarioConfig) -> None:
    level = 300.0
    worlds = simulate_worlds(
        vol, s0=138.0, start=date(2026, 10, 9), levels=[level], cfg=small_cfg
    )
    w = worlds[level]
    at = w.s0 + w.ds[np.arange(w.n), w.tc]
    assert np.max(np.abs(at - level)) < 1e-6
    assert np.all(w.tc >= small_cfg.event_bdays)
    assert np.all(w.tc <= w.T)


def test_bund_flight_share_in_range(vol: VolCalib, small_cfg: ScenarioConfig) -> None:
    worlds = simulate_worlds(
        vol, s0=138.0, start=date(2026, 10, 9), levels=[300.0], cfg=small_cfg
    )
    f = worlds[300.0].f
    lo, hi = small_cfg.bund_flight_share
    assert float(f.min()) >= lo - 1e-12
    assert float(f.max()) <= hi + 1e-12


def test_seed_reproducibility(vol: VolCalib, small_cfg: ScenarioConfig) -> None:
    a = simulate_worlds(vol, s0=138.0, start=date(2026, 10, 9), levels=[240.0, 300.0], cfg=small_cfg)
    b = simulate_worlds(vol, s0=138.0, start=date(2026, 10, 9), levels=[240.0, 300.0], cfg=small_cfg)
    np.testing.assert_array_equal(a[300.0].ds, b[300.0].ds)
    np.testing.assert_array_equal(a[None].db, b[None].db)


def test_common_random_numbers_across_levels(vol: VolCalib, small_cfg: ScenarioConfig) -> None:
    """Pre-event noise and (tc, f) shared; only the bridge target differs by level."""
    worlds = simulate_worlds(
        vol, s0=138.0, start=date(2026, 10, 9), levels=[240.0, 400.0], cfg=small_cfg
    )
    w240, w400 = worlds[240.0], worlds[400.0]
    np.testing.assert_array_equal(w240.tc, w400.tc)
    np.testing.assert_array_equal(w240.f, w400.f)
    # Before any path's event start, cumulative paths match
    ts = w240.tc - small_cfg.event_bdays
    for i in range(w240.n):
        t0 = int(ts[i])
        np.testing.assert_allclose(w240.ds[i, : t0 + 1], w400.ds[i, : t0 + 1], atol=1e-12)


def test_cac_returns_shape(vol: VolCalib, small_cfg: ScenarioConfig) -> None:
    worlds = simulate_worlds(
        vol, s0=138.0, start=date(2026, 10, 9), levels=[300.0], cfg=small_cfg
    )
    betas = stock_betas(load_stocks_daily(), load_yields_daily(), tickers=["^FCHI"])
    r = stock_cum_returns(worlds[300.0], betas["^FCHI"])
    assert r.shape == worlds[300.0].ds.shape
    assert np.allclose(r[:, 0], 0.0)
