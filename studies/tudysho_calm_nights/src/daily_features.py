"""Build daily session extrusion feature table for slot A days."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd

from extrusion import (
    drop_weekend_bars,
    normalize_extrusion,
    parkinson_extrusion,
    path_extrusion,
    quiet_tertile_flags,
    range_extrusion,
    slice_bars,
)
from sessions import (
    SESSIONS_SLOT_A,
    hold_from_entry_bounds_utc,
    hold_night_bounds_utc,
    predictor_bounds_utc,
    session_bounds_utc,
    slot_a_entry_days,
)


def _session_metrics(bars: pd.DataFrame, prefix: str, *, exclude_weekends: bool = False) -> dict[str, float]:
    if exclude_weekends:
        bars = drop_weekend_bars(bars)
    return {
        f"{prefix}_range": range_extrusion(bars),
        f"{prefix}_path": path_extrusion(bars),
        f"{prefix}_parkinson": parkinson_extrusion(bars),
    }


def build_daily_table(
    bars: pd.DataFrame,
    start: date,
    end: date,
    *,
    predictor_variant: str = "us_morning",
    rolling_days: int = 60,
    quiet_tertile: float = 0.33,
    exclude_weekends: bool = False,
    entry_times_nyc: list[str] | None = None,
) -> pd.DataFrame:
    """One row per slot-A NYSE day with session and hold extrusion metrics."""
    if entry_times_nyc is None:
        entry_times_nyc = ["12:00", "14:00", "16:00"]

    rows: list[dict] = []
    for entry_day in slot_a_entry_days(start, end):
        row: dict = {"entry_date": entry_day.isoformat(), "predictor_variant": predictor_variant}

        p0, p1 = predictor_bounds_utc(entry_day, predictor_variant)
        pb = slice_bars(bars, pd.Timestamp(p0), pd.Timestamp(p1))
        row.update(_session_metrics(pb, "predictor", exclude_weekends=exclude_weekends))

        for sess in SESSIONS_SLOT_A:
            s0, s1 = session_bounds_utc(entry_day, sess)
            sb = slice_bars(bars, pd.Timestamp(s0), pd.Timestamp(s1))
            row.update(_session_metrics(sb, sess.name, exclude_weekends=exclude_weekends))

        hold_start, hold_end = hold_night_bounds_utc(entry_day)
        hold_bars = slice_bars(bars, pd.Timestamp(hold_start), pd.Timestamp(hold_end))
        row.update(_session_metrics(hold_bars, "hold_night", exclude_weekends=exclude_weekends))

        for et in entry_times_nyc:
            tag = et.replace(":", "")
            h0, h1 = hold_from_entry_bounds_utc(entry_day, et)
            hb = slice_bars(bars, pd.Timestamp(h0), pd.Timestamp(h1))
            row.update(_session_metrics(hb, f"hold_from_{tag}", exclude_weekends=exclude_weekends))

        rows.append(row)

    daily = pd.DataFrame(rows)
    if daily.empty:
        return daily

    daily["predictor_range_norm"] = normalize_extrusion(
        daily["predictor_range"],
        rolling=rolling_days,
        exclude_weekends=exclude_weekends,
        entry_dates=daily["entry_date"],
    )
    daily["predictor_quiet"] = quiet_tertile_flags(
        daily["predictor_range_norm"],
        q=quiet_tertile,
        rolling=rolling_days,
        exclude_weekends=exclude_weekends,
        entry_dates=daily["entry_date"],
    )

    # Legacy aliases when predictor is US morning (backward-compatible column names)
    if predictor_variant == "us_morning":
        daily["us_morning_range"] = daily["predictor_range"]
        daily["us_morning_path"] = daily["predictor_path"]
        daily["us_morning_parkinson"] = daily["predictor_parkinson"]
        daily["us_morning_range_norm"] = daily["predictor_range_norm"]
        daily["us_morning_quiet"] = daily["predictor_quiet"]
        daily["us_morning_quiet_norm_below_075"] = daily["predictor_range_norm"] < 0.75

    hold_cols = [c for c in daily.columns if c.endswith("_range") and c.startswith("hold_")]
    for col in hold_cols:
        prefix = col[: -len("_range")]
        norm_col = f"{prefix}_range_norm"
        quiet_col = f"{prefix}_quiet"
        daily[norm_col] = normalize_extrusion(
            daily[col],
            rolling=rolling_days,
            exclude_weekends=exclude_weekends,
            entry_dates=daily["entry_date"],
        )
        daily[quiet_col] = quiet_tertile_flags(
            daily[norm_col],
            q=quiet_tertile,
            rolling=rolling_days,
            exclude_weekends=exclude_weekends,
            entry_dates=daily["entry_date"],
        )

    return daily


def parse_date_range(cfg: dict) -> tuple[date, date]:
    dr = cfg["data"]["date_range"]
    start = datetime.fromisoformat(dr["start"]).date()
    end = datetime.fromisoformat(dr["end"]).date()
    return start, end


def filter_for_analysis(daily: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Subset for hypothesis gates: post-options floor + warmup burn-in."""
    analysis = cfg.get("analysis", {})
    effective = analysis.get("effective_start")
    warmup = int(analysis.get("warmup_days", 0))

    sub = daily.sort_values("entry_date").reset_index(drop=True)
    if warmup > 0 and len(sub) > warmup:
        sub = sub.iloc[warmup:].reset_index(drop=True)
    if effective:
        sub = sub[sub["entry_date"] >= effective].reset_index(drop=True)
    return sub
