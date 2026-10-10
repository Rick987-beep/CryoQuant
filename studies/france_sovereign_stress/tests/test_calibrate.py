"""Phase 2 calibration tests (v5 reference inputs, no network)."""

from __future__ import annotations

from src.calibrate import (
    calibrate_futures,
    calibrate_vol,
    duration_cross_check,
    eur_per_bp_from_duration,
    live_spread_pnl,
    stock_betas,
)
from src.data.reference import load_eurex_settles, load_stocks_daily, load_yields_daily


def test_futcalib_matches_v5() -> None:
    fc = calibrate_futures(load_eurex_settles(), load_yields_daily())
    assert fc.days == 20
    assert abs(fc.eur_per_bp["FOAT"] - 87.58349276838244) < 1e-6
    assert abs(fc.eur_per_bp["FGBL"] - 96.5658919031578) < 1e-6
    assert abs(fc.hedge_ratio - 0.9069816582465425) < 1e-9
    assert abs(fc.carry_bp_per_day["FOAT"] - 0.11417676646494913) < 1e-9
    assert abs(fc.duration["FOAT"] - 7.925641728620709) < 1e-9


def test_duration_identity() -> None:
    fc = calibrate_futures(load_eurex_settles(), load_yields_daily())
    x = duration_cross_check(fc)
    for code in ("FOAT", "FGBL"):
        assert abs(x[code]["identity_diff"]) < 1e-9
        assert abs(
            eur_per_bp_from_duration(fc.duration[code], fc.mean_price[code])
            - fc.eur_per_bp[code]
        ) < 1e-9


def test_live_pnl_11490() -> None:
    pnl = live_spread_pnl(load_eurex_settles(), load_yields_daily())
    assert pnl.pnl_ok
    assert abs(pnl.pnl_eur - 11_490.0) < 0.01
    assert abs(pnl.spread_change_bp - 44.83) < 0.02


def test_vol_matches_v5() -> None:
    vol = calibrate_vol(load_yields_daily(), window=126)
    assert abs(vol.sig_s - 3.178634324899386) < 1e-9
    assert abs(vol.sig_b - 3.953033005536023) < 1e-9
    assert abs(vol.rho - 0.14392426764339208) < 1e-9


def test_cac_beta_present() -> None:
    betas = stock_betas(
        load_stocks_daily(), load_yields_daily(), tickers=["^FCHI"]
    )
    assert "^FCHI" in betas
    assert betas["^FCHI"].beta_s < 0  # short-spread beta: stocks fall as spread widens
