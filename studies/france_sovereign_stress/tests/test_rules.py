"""Phase 4 rule-engine tests (no network)."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from src.calibrate import calibrate_futures, calibrate_vol, stock_betas
from src.data.reference import load_eurex_settles, load_stocks_daily, load_yields_daily
from src.rules import (
    Rule,
    build_cac_sleeve,
    build_spread_sleeve,
    run_continuous,
    straight_line_spread_equity,
    straight_line_spread_ladder,
)
from src.scenarios import ScenarioConfig, World, business_days, simulate_worlds


V5_STRAIGHT = {
    240: 76_563,
    300: 181_664,
    340: 251_730,
    400: 356_831,
}


@pytest.fixture(scope="module")
def fc():
    return calibrate_futures(load_eurex_settles(), load_yields_daily())


def test_straight_line_matches_handover(fc) -> None:
    s0 = 138.0
    ef = fc.eur_per_bp["FOAT"]
    for level, target in V5_STRAIGHT.items():
        eq = straight_line_spread_equity(level, s0=s0, eur_foat=ef)
        assert abs(eq - target) < 1.0, (level, eq, target)


def test_straight_line_ladder_sizes(fc) -> None:
    ladder = straight_line_spread_ladder(
        s0=138.0,
        eur_foat=fc.eur_per_bp["FOAT"],
        eur_fgbl=fc.eur_per_bp["FGBL"],
        levels=[240, 300, 340, 400],
    )
    # HANDOVER risk-box sizes: 3/3, 4/4, 6/6, 9/8, 14/13, 20/18
    by_delta = {int(r["delta_bp"]): (r["foat"], r["fgbl"]) for r in ladder["rows"]}
    assert by_delta[0] == (3, 3)
    assert by_delta[20] == (4, 4)
    assert by_delta[40] == (6, 6)
    assert by_delta[60] == (9, 8)
    assert by_delta[80] == (14, 13)
    assert by_delta[100] == (20, 18)


def _deterministic_right_world(s0: float, level: float, T: int = 30, event_bd: int = 15) -> World:
    """Single path: flat until event, then linear bridge to level (no noise)."""
    start = date(2026, 10, 9)
    days = business_days(start, start + timedelta(days=T * 2))
    days = days[: T + 1]
    assert len(days) == T + 1
    tc = T
    ts = tc - event_bd
    ds = np.zeros((1, T + 1))
    db = np.zeros((1, T + 1))
    jump = level - s0
    for k in range(1, event_bd + 1):
        t = ts + k
        ds[0, t] = jump * (k / event_bd)
    return World(
        s0=s0,
        days=days,
        ds=ds,
        db=db,
        tc=np.array([tc]),
        f=np.array([0.4]),
        level=level,
        seed=0,
    )


def test_continuous_daily_close_reaches_near_straight_line(fc) -> None:
    """No-noise path + continuous units ≈ straight line but with friction."""
    s0, level = 138.0, 300.0
    w = _deterministic_right_world(s0, level)
    sleeve = build_spread_sleeve(w, fc)
    # Zero costs for this check
    sleeve.tcost = 0.0
    sleeve.slip = 0.0
    rule = Rule(40, 20, 0.0)
    eq, _ = run_continuous(sleeve, w, rule, 10_000.0, execution="daily_close")
    # Continuous units resize every +20 without integer rounding — close to straight line
    # but not identical (continuous vs integer FOAT counts).
    target = straight_line_spread_equity(level, s0=s0, eur_foat=fc.eur_per_bp["FOAT"])
    # Should be same order of magnitude and within ~25%
    assert eq[0] > 50_000
    assert abs(eq[0] - target) / target < 0.25


def test_run_on_mc_smoke(fc) -> None:
    vol = calibrate_vol(load_yields_daily(), window=126)
    cfg = ScenarioConfig(n_paths=50, seed=11, end=date(2027, 7, 1))
    worlds = simulate_worlds(vol, s0=138.0, start=date(2026, 10, 9), levels=[300.0], cfg=cfg)
    w = worlds[300.0]
    sleeve = build_spread_sleeve(w, fc)
    eq, u0 = run_continuous(sleeve, w, Rule(40, 20, 0.0), 10_000.0, execution="daily_close")
    assert eq.shape == (50,)
    assert u0 == pytest.approx(10_000 / 40)
    assert np.isfinite(eq).all()


def test_cac_sleeve_runs(fc) -> None:
    vol = calibrate_vol(load_yields_daily(), window=126)
    cfg = ScenarioConfig(n_paths=30, seed=11, end=date(2027, 7, 1))
    worlds = simulate_worlds(vol, s0=138.0, start=date(2026, 10, 9), levels=[300.0], cfg=cfg)
    beta = stock_betas(load_stocks_daily(), load_yields_daily(), tickers=["^FCHI"])["^FCHI"]
    sleeve = build_cac_sleeve(worlds[300.0], beta)
    eq, _ = run_continuous(sleeve, worlds[300.0], Rule(12, 6, 0.0), 10_000.0, execution="daily_close")
    assert eq.shape == (30,)
    assert np.isfinite(eq).all()
