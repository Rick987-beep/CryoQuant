"""Unit tests for Black-76 / skew / structure costing."""

from __future__ import annotations

import numpy as np
import pytest

from src.options import (
    Quote,
    Skew,
    Structure,
    Leg,
    b76,
    implied_vol,
    single,
    vertical,
    fit_skew,
    parity_forward,
)


def test_b76_atm_call_put_parity():
    f, k, t, sig = 100.0, 100.0, 0.5, 0.10
    c = float(b76(f, k, t, sig, True))
    p = float(b76(f, k, t, sig, False))
    # Put-call parity for futures options: C - P = DF*(F-K) = 0 when F=K.
    assert abs(c - p) < 1e-6
    assert c > 0


def test_implied_vol_roundtrip():
    f, k, t, sig = 108.5, 106.0, 0.15, 0.09
    px = float(b76(f, k, t, sig, False))
    iv = implied_vol(px, f, k, t, False)
    assert iv is not None
    assert abs(iv - sig) < 1e-3


def test_skew_vol_atm():
    sk = Skew(atm=0.10, b=-0.2, c=0.5)
    assert abs(sk.vol(100, 100, 0.25) - 0.10) < 1e-9


def test_structure_live_cost_requires_two_sided():
    from src.options import Expiry
    from datetime import date

    quotes = {
        "P": {
            105.0: Quote(bid=0.50, ask=0.60),
            102.0: Quote(bid=0.20, ask=0.28),
            100.0: Quote(bid=None, ask=0.10),  # one-sided
        },
        "C": {105.0: Quote(bid=1.0, ask=1.1)},
    }
    exp = Expiry(
        product="OOAT",
        label="20/11/2026",
        date=date(2026, 11, 20),
        t=0.1,
        quotes=quotes,
        fwd=108.0,
        skew=Skew(0.1, 0, 0),
        ivs=[],
    )
    s = single("OOAT", "P", 105.0)
    assert s.live_cost(exp) == pytest.approx(0.60)
    v = vertical("OOAT", "P", 105.0, 102.0)
    # Buy 105 ask 0.60, sell 102 bid 0.20 → debit 0.40
    assert v.live_cost(exp) == pytest.approx(0.40)
    bad = single("OOAT", "P", 100.0)
    assert bad.live_cost(exp) is None


def test_parity_forward():
    quotes = {
        "C": {108.0: Quote(0.80, 0.84), 108.5: Quote(0.60, 0.64)},
        "P": {108.0: Quote(0.70, 0.74), 108.5: Quote(0.85, 0.90)},
    }
    # mid C-P at 108: 0.82 - 0.72 = 0.10 → F = 108.10
    f = parity_forward(quotes, 108.0)
    assert abs(f - 108.1) < 0.15
