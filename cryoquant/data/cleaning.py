"""OHLCV cleaning and normalisation utilities.

Public interface::

    normalize_ohlcv(df, tf)          -> pd.DataFrame   # enforce canonical schema
    clean_ohlcv(df, tf, calendar_id) -> pd.DataFrame   # remove bad bars
    audit_bars(df, tf, calendar_id)  -> list[AuditWarning]  # non-destructive QA

All functions are pure (no I/O).  They are called by the loader after
source-specific fetching and before writing to Parquet.

Canonical schema (output guarantee):
  • DatetimeIndex named "timestamp", UTC tz-aware, bar-open convention
  • Columns: open, high, low, close, volume — all float64
  • No duplicate timestamps
  • Sorted ascending
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import pandas as pd

from cryocore.time import floor_to_tf

log = logging.getLogger(__name__)

AssetClass = str | None  # equity, fx, commodity, …


def _price_spike_threshold(calendar_id: str, asset_class: AssetClass) -> float:
    """Calendar- and asset-class-aware close-to-close spike threshold."""
    if asset_class == "fx" or calendar_id in ("fx_24_5", "fx_eur"):
        return 0.05
    if asset_class in ("commodity", "crypto") or calendar_id == "cme_futures":
        return 0.35
    return 0.20


def _stale_close_threshold(calendar_id: str) -> int:
    if calendar_id in ("fx_24_5", "fx_eur"):
        return 8
    return 5


# ---------------------------------------------------------------------------
# AuditWarning — lightweight issue report
# ---------------------------------------------------------------------------

@dataclass
class AuditWarning:
    level: Literal["error", "warning", "info"]
    code: str
    message: str
    affected_rows: int = 0
    meta: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.code}: {self.message} (rows={self.affected_rows})"


# ---------------------------------------------------------------------------
# normalize_ohlcv
# ---------------------------------------------------------------------------

def normalize_ohlcv(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Enforce the canonical OHLCV schema with minimal data loss.

    Steps:
    1. Ensure float64 OHLCV columns (add volume=0 if absent).
    2. Ensure UTC tz-aware DatetimeIndex named "timestamp".
    3. Floor timestamps to the bar-open boundary for the given tf.
    4. Drop fully-duplicate rows (same timestamp AND same OHLCV values).
    5. On duplicate timestamps with different values keep the first occurrence
       and log a warning (prefer latest source data — caller should de-dup
       before calling if order matters).
    6. Sort ascending.
    """
    out = df.copy()

    # --- column coercion ---
    for col in ("open", "high", "low", "close"):
        if col not in out.columns:
            raise ValueError(f"normalize_ohlcv: missing required column {col!r}")
    if "volume" not in out.columns:
        out["volume"] = 0.0
    out = out[["open", "high", "low", "close", "volume"]].astype(float)

    # --- index → UTC tz-aware ---
    idx = pd.DatetimeIndex(out.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    out.index = idx
    out.index.name = "timestamp"

    # --- floor to bar-open boundary (skip daily/weekly — already date-aligned) ---
    if tf not in ("1d", "1wk"):
        floored = []
        for ts in out.index:
            try:
                floored.append(floor_to_tf(ts, tf))
            except Exception:
                floored.append(ts)
        out.index = pd.DatetimeIndex(floored, name="timestamp")

    # --- deduplicate ---
    n_before = len(out)
    out = out[~out.index.duplicated(keep="first")]
    n_dupes = n_before - len(out)
    if n_dupes > 0:
        log.warning("normalize_ohlcv: dropped %d duplicate timestamps", n_dupes)

    return out.sort_index()


# ---------------------------------------------------------------------------
# clean_ohlcv
# ---------------------------------------------------------------------------

def clean_ohlcv(
    df: pd.DataFrame,
    tf: str,
    calendar_id: str = "nyse",
    *,
    asset_class: AssetClass = None,
    drop_zero_volume_ratio: float = 0.0,
) -> pd.DataFrame:
    """Remove bars that are clearly wrong or outside market hours.

    Steps (in order):
    1. Normalize (calls normalize_ohlcv).
    2. Drop bars where any OHLC is NaN or zero (bad ticks).
    3. Drop bars where low > high (inverted — data error).
    4. Drop bars where close < 0 (impossible price).
    5. Drop bars where volume < 0 (impossible volume).
    6. For FX calendars (fx_24_5): drop Saturday bars and early-Sunday bars.
    7. Drop the in-progress bar (last bar within one bar-period of now).

    Args:
        df:                      Raw/normalised DataFrame.
        tf:                      Timeframe (e.g. "1d", "1h").
        calendar_id:             Calendar key for session filtering.
        drop_zero_volume_ratio:  Drop bars with volume==0 only if they represent
                                 more than this fraction of the series (0 = never drop).

    Returns:
        Cleaned DataFrame (subset of rows; same column schema).
    """
    out = normalize_ohlcv(df, tf)
    original_len = len(out)

    # Bad OHLC values
    bad_nan = out[["open", "high", "low", "close"]].isnull().any(axis=1)
    bad_zero = (out[["open", "high", "low", "close"]] == 0).any(axis=1)
    bad_ohlc = bad_nan | bad_zero
    if bad_ohlc.any():
        log.warning("clean_ohlcv: dropping %d bars with NaN/zero OHLC", bad_ohlc.sum())
    out = out[~bad_ohlc]

    # Inverted OHLC
    inverted = out["low"] > out["high"]
    if inverted.any():
        log.warning("clean_ohlcv: dropping %d bars with low > high", inverted.sum())
    out = out[~inverted]

    # Negative prices
    neg_price = (out[["open", "high", "low", "close"]] < 0).any(axis=1)
    if neg_price.any():
        log.warning("clean_ohlcv: dropping %d bars with negative prices", neg_price.sum())
    out = out[~neg_price]

    # Negative volume
    neg_vol = out["volume"] < 0
    if neg_vol.any():
        log.warning("clean_ohlcv: dropping %d bars with negative volume", neg_vol.sum())
    out = out[~neg_vol]

    # FX off-market bars — use calendar.is_open() as single source of truth
    if calendar_id in ("fx_24_5", "fx_eur"):
        from cryocore.calendars import get_calendar
        cal = get_calendar(calendar_id)
        ts_series = pd.Series(out.index, index=out.index)
        off_market = ~ts_series.apply(cal.is_open)
        if off_market.any():
            log.debug("clean_ohlcv: dropping %d off-market FX bars", off_market.sum())
        out = out[~off_market]

    # Zero-volume guard (optional — equities intraday; never for FX which has no volume)
    if drop_zero_volume_ratio > 0:
        zero_vol = out["volume"] == 0
        ratio = zero_vol.mean()
        if ratio > drop_zero_volume_ratio:
            log.warning(
                "clean_ohlcv: NOT dropping zero-volume bars (ratio=%.1f%% > threshold=%.1f%%); "
                "review manually",
                ratio * 100, drop_zero_volume_ratio * 100,
            )

    # In-progress bar (last bar whose open_time + bar_period > now)
    try:
        bar_secs = _tf_to_seconds_safe(tf)
        if bar_secs is not None:
            cutoff = pd.Timestamp(datetime.now(timezone.utc)) - pd.Timedelta(seconds=bar_secs)
            in_progress = out.index > cutoff
            if in_progress.any():
                log.debug("clean_ohlcv: dropping %d in-progress bar(s)", in_progress.sum())
            out = out[~in_progress]
    except Exception:
        pass

    n_dropped = original_len - len(out)
    if n_dropped > 0:
        log.info("clean_ohlcv: %d bars removed (%.1f%% of input)",
                 n_dropped, 100 * n_dropped / max(original_len, 1))

    return out


# ---------------------------------------------------------------------------
# audit_bars
# ---------------------------------------------------------------------------

def audit_bars(
    df: pd.DataFrame,
    tf: str,
    calendar_id: str = "nyse",
    *,
    asset_class: AssetClass = None,
) -> list[AuditWarning]:
    """Non-destructive quality check.  Returns a list of AuditWarning objects.

    Checks performed:
    • Duplicate timestamps
    • NaN in OHLC
    • Negative volume
    • low > high (inverted bar)
    • Gaps larger than expected (> 3× bar period for market hours)
    • Price spikes — threshold is calendar-aware:
        - fx_24_5 / fx_eur  : > 5%  (flash-crash level for FX)
        - cme_futures        : > 35% (energy commodities can move 30%+ legitimately)
        - default (nyse)     : > 20%
    • Stale bars — threshold is calendar-aware:
        - fx_24_5 / fx_eur  : ≥ 8 consecutive unchanged closes (off-peak FX sessions
                               routinely flatline for 5–7 bars; 8+ is genuinely anomalous)
        - default            : ≥ 5 consecutive unchanged closes
    """
    warnings: list[AuditWarning] = []
    if df.empty:
        warnings.append(AuditWarning("warning", "EMPTY", "DataFrame is empty"))
        return warnings

    # UTC index check
    if not isinstance(df.index, pd.DatetimeIndex):
        warnings.append(AuditWarning("error", "NO_DATETIME_INDEX", "Index is not DatetimeIndex"))
        return warnings
    if df.index.tz is None:
        warnings.append(AuditWarning("error", "NO_TZ", "DatetimeIndex has no timezone"))

    # Duplicates
    n_dupes = df.index.duplicated().sum()
    if n_dupes:
        warnings.append(AuditWarning("error", "DUPLICATE_TS",
                                     f"{n_dupes} duplicate timestamps", n_dupes))

    # NaN OHLC
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            n_nan = df[col].isnull().sum()
            if n_nan:
                warnings.append(AuditWarning("error", f"NAN_{col.upper()}",
                                             f"{n_nan} NaN in {col!r}", n_nan))

    # Negative volume
    if "volume" in df.columns:
        n_neg_vol = (df["volume"] < 0).sum()
        if n_neg_vol:
            warnings.append(AuditWarning("error", "NEG_VOLUME",
                                         f"{n_neg_vol} negative volume bars", n_neg_vol))

    # Inverted OHLC
    if "low" in df.columns and "high" in df.columns:
        n_inv = (df["low"] > df["high"]).sum()
        if n_inv:
            warnings.append(AuditWarning("error", "INVERTED_OHLC",
                                         f"{n_inv} bars with low > high", n_inv))

    # Gaps
    bar_secs = _tf_to_seconds_safe(tf)
    if bar_secs is not None and len(df) > 1:
        diffs = df.index.to_series().diff().dropna().dt.total_seconds()
        # For calendar-constrained assets, gaps of 1 weekend (~2.5 days) are normal
        gap_threshold = bar_secs * 3
        if calendar_id in ("nyse", "cme_futures"):
            gap_threshold = max(bar_secs * 3, 86_400 * 3)  # allow weekend+holiday
        elif calendar_id in ("fx_24_5", "fx_eur"):
            gap_threshold = max(bar_secs * 3, 86_400 * 2.5)
        big_gaps = diffs[diffs > gap_threshold]
        if not big_gaps.empty:
            warnings.append(AuditWarning(
                "warning", "GAPS",
                f"{len(big_gaps)} gaps larger than {gap_threshold/3600:.1f}h",
                len(big_gaps),
                meta={"max_gap_hours": float(big_gaps.max() / 3600)},
            ))

    # Price spikes (threshold from asset_class + calendar)
    if "close" in df.columns and len(df) > 1:
        pct = df["close"].pct_change().abs().dropna()
        spike_thr = _price_spike_threshold(calendar_id, asset_class)
        n_spikes = (pct > spike_thr).sum()
        if n_spikes:
            warnings.append(AuditWarning(
                "warning", "PRICE_SPIKE",
                f"{n_spikes} bars with close-to-close move > {spike_thr:.0%}",
                n_spikes,
                meta={"max_move": float(pct.max()), "threshold": spike_thr},
            ))

    # Stale close (flatline streaks)
    if "close" in df.columns and len(df) >= 5:
        stale_streak_thr = _stale_close_threshold(calendar_id)
        stale_mask = (df["close"].diff() == 0)
        stale_streak = (stale_mask != stale_mask.shift()).cumsum()
        streak_len = stale_mask.groupby(stale_streak).transform("sum")
        n_stale = int((streak_len[stale_mask] >= stale_streak_thr).sum())
        if n_stale:
            warnings.append(AuditWarning(
                "warning", "STALE_CLOSE",
                f"{n_stale} bars in flatline streaks (≥{stale_streak_thr} unchanged close)",
                n_stale,
            ))

    return warnings


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _tf_to_seconds_safe(tf: str) -> int | None:
    """Return tf in seconds, or None if tf is non-standard (e.g. "1wk")."""
    try:
        from cryocore.time import tf_to_seconds
        return tf_to_seconds(tf)
    except Exception:
        _TF_STATIC = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
                      "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}
        return _TF_STATIC.get(tf)
