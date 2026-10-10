"""Phase 5 evaluate helpers (small n, no network)."""

from __future__ import annotations

from datetime import date

from src.calibrate import calibrate_futures, calibrate_vol, stock_betas
from src.data.reference import load_eurex_settles, load_stocks_daily, load_yields_daily
from src.evaluate import evaluate_cac, evaluate_spread_levels, mix_multiples, payout_stats, scale_vol
from src.rules import Rule
from src.scenarios import ScenarioConfig, simulate_worlds


def test_payout_stats_and_spread_eval() -> None:
    fc = calibrate_futures(load_eurex_settles(), load_yields_daily())
    vol = calibrate_vol(load_yields_daily(), window=126)
    cfg = ScenarioConfig(n_paths=80, seed=11, end=date(2027, 7, 1))
    worlds = simulate_worlds(
        vol, s0=138.0, start=date(2026, 10, 9), levels=[240.0, 300.0], cfg=cfg
    )
    out = evaluate_spread_levels(
        worlds, fc, Rule(40, 20, 0.0), 10_000.0, [240.0, 300.0], execution="daily_close"
    )
    assert "300" in out["by_level"]
    assert out["wrong"]["mean"] < out["by_level"]["300"]["mean"]


def test_mix_and_cac() -> None:
    import numpy as np

    a = np.array([1.0, 2.0, 3.0])
    b = np.array([3.0, 2.0, 1.0])
    m = mix_multiples(a, b, 0.75)
    assert abs(m[0] - 1.5) < 1e-9
    st = payout_stats(m)
    assert st.mean > 0

    fc = calibrate_futures(load_eurex_settles(), load_yields_daily())
    vol = scale_vol(calibrate_vol(load_yields_daily(), window=126), 1.0)
    cfg = ScenarioConfig(n_paths=40, seed=11, end=date(2027, 7, 1))
    worlds = simulate_worlds(
        vol, s0=138.0, start=date(2026, 10, 9), levels=[300.0], cfg=cfg
    )
    beta = stock_betas(load_stocks_daily(), load_yields_daily(), tickers=["^FCHI"])["^FCHI"]
    cac = evaluate_cac(worlds, beta, Rule(12, 6, 0.0), 10_000.0)
    assert "mean" in cac["right"]
