"""Snapshot merge rules (no network)."""

from datetime import date, datetime, timezone

import pandas as pd

from src.data.snapshot import last_business_day_before, merge_history, new_stamp


def _frame(days: list[str], values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"x": values}, index=pd.to_datetime(days))


def test_last_business_day_before_skips_weekend():
    assert last_business_day_before(date(2026, 10, 12)) == date(2026, 10, 9)
    assert last_business_day_before(date(2026, 10, 9)) == date(2026, 10, 8)


def test_new_stamp_uses_berlin_time():
    assert new_stamp(datetime(2026, 10, 12, 7, 35, tzinfo=timezone.utc)) == "2026-10-12T0935"


def test_merge_replaces_partial_row_drops_weekend_and_today():
    frozen = _frame(["2026-10-07", "2026-10-08", "2026-10-09"], [1.0, 2.0, 99.0])
    fresh = _frame(
        ["2026-10-08", "2026-10-09", "2026-10-10", "2026-10-12"], [2.5, 3.0, 4.0, 5.0]
    )
    merged, rep = merge_history(
        frozen, fresh, ref_date=date(2026, 10, 9), cutoff=date(2026, 10, 9), compare=["x"]
    )
    assert list(merged.index.strftime("%Y-%m-%d")) == ["2026-10-07", "2026-10-08", "2026-10-09"]
    assert merged["x"].tolist() == [1.0, 2.0, 3.0]
    assert rep.frozen_rows == 2 and rep.fresh_rows_added == 1
    assert rep.first_added == "2026-10-09" and rep.last_date == "2026-10-09"
    assert rep.overlap_rows == 1 and rep.overlap_max_abs_diff == {"x": 0.5}


def test_merge_with_no_fresh_rows_keeps_frozen_history():
    frozen = _frame(["2026-10-07", "2026-10-08"], [1.0, 2.0])
    merged, rep = merge_history(
        frozen, frozen.iloc[:0], ref_date=date(2026, 10, 9), cutoff=date(2026, 10, 9)
    )
    assert merged["x"].tolist() == [1.0, 2.0]
    assert rep.fresh_rows_added == 0 and rep.first_added is None
