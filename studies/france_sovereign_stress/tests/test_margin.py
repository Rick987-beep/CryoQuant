"""Margin ladder (no network)."""

from src.calibrate import FutCalib
from src.margin import entry_contracts, ladder_with_margin, margin_im, margin_report


def _fc() -> FutCalib:
    return FutCalib(
        eur_per_bp={"FOAT": 88.32, "FGBL": 97.43},
        duration={"FOAT": 8.0, "FGBL": 8.1},
        carry_bp_per_day={"FOAT": 0.117, "FGBL": 0.014},
        corr_price_yield={"FOAT": -0.98, "FGBL": -0.98},
        mean_price={"FOAT": 110.0, "FGBL": 120.0},
        calendar_points={"FOAT": 0.65, "FGBL": 0.09},
        hedge_ratio=0.906,
        days=20,
    )


def test_entry_contracts_scale_with_budget():
    fc = _fc()
    assert entry_contracts(10_000, fc) == (3, 3)
    assert entry_contracts(15_000, fc)[0] >= 4
    assert entry_contracts(20_000, fc)[0] >= 5


def test_margin_im_is_additive():
    assert margin_im(3, 3, im_foat=3247, im_fgbl=2363) == 3 * 3247 + 3 * 2363


def test_ladder_cap_im_exceeds_entry():
    fc = _fc()
    out = ladder_with_margin(
        s0=137.3, fc=fc, budget=10_000, im_foat=3247, im_fgbl=2363
    )
    assert out["entry_foat"] == 3 and out["entry_fgbl"] == 3
    assert out["cap_im_eur"] > out["entry_im_eur"]
    assert out["rows"][0]["im_eur"] == out["entry_im_eur"]


def test_margin_report_has_three_budgets():
    fc = _fc()
    rep = margin_report(
        s0=137.3,
        fc=fc,
        budgets=[10_000, 15_000, 20_000],
        im_foat=3247,
        im_fgbl=2363,
        asof="2026-10-12",
        source="test",
    )
    assert set(rep["budgets"]) == {"10000", "15000", "20000"}
    assert rep["budgets"]["20000"]["entry_im_eur"] > rep["budgets"]["10000"]["entry_im_eur"]
