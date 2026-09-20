"""Tests for Cboe VX front-month helpers."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from cryoquant.data.sources.cboe_vx_futures import (
    third_friday,
    vx_expiration_for_contract_month,
    _parse_vx_csv,
)


def test_third_friday_known():
    assert third_friday(2026, 10) == date(2026, 10, 16)


def test_vx_expiration_sep_2026():
    assert vx_expiration_for_contract_month(2026, 9) == date(2026, 9, 16)


def test_parse_vx_csv_settlement_day_zeros():
    csv = (
        "Trade Date,Futures,Open,High,Low,Close,Settle,Change,Total Volume,EFP,Open Interest\n"
        "2026-09-16,U (Sep 2026),0,0,0,0,16.79,0,0,0,1000\n"
    )
    df = _parse_vx_csv(csv, date(2026, 9, 16))
    assert float(df["close"].iloc[0]) == 16.79
    assert float(df["settle"].iloc[0]) == 16.79
