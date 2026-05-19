"""Cross-repo Pydantic schemas shared by CryoQuant, CryoBacktester, and CryoTrader.

OHLCVBars — validated OHLCV DataFrame wrapper (used by loader).
ProbEmit, BoolEmit, StateEmit — signal emission records.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, field_validator, model_validator


# ---------------------------------------------------------------------------
# OHLCV validation
# ---------------------------------------------------------------------------

class OHLCVBars(BaseModel):
    """Validate that a DataFrame is a well-formed OHLCV bar series.

    Usage::

        OHLCVBars.validate_df(df)   # raises ValueError on problems
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _REQUIRED_COLS: ClassVar[tuple[str, ...]] = ("open", "high", "low", "close", "volume")

    @classmethod
    def validate_df(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Validate *df* in place; return it on success, raise ValueError on failure."""
        errors: list[str] = []

        if not isinstance(df.index, pd.DatetimeIndex):
            errors.append("index must be a DatetimeIndex")
        elif df.index.tz is None:
            errors.append("index must be tz-aware (UTC expected)")

        missing = [c for c in cls._REQUIRED_COLS if c not in df.columns]
        if missing:
            errors.append(f"missing columns: {missing}")

        if not errors:
            # Only check values if structure is sane
            if df[["open", "high", "low", "close"]].isnull().any().any():
                errors.append("OHLC columns must not contain NaN")
            if (df["volume"] < 0).any():
                errors.append("volume must not be negative")

        if errors:
            raise ValueError("OHLCVBars validation failed: " + "; ".join(errors))

        return df


# ---------------------------------------------------------------------------
# Signal emit records
# ---------------------------------------------------------------------------

class _BaseEmit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ts: datetime
    signal_id: str
    symbol_str: str        # "venue:ticker" — avoids importing instruments here
    metadata: dict[str, Any] = {}


class BoolEmit(_BaseEmit):
    value: bool


class StateEmit(_BaseEmit):
    state: Literal[-1, 0, 1]
    flipped: bool = False


class ProbEmit(_BaseEmit):
    prob: float
    direction: Literal["up", "down", "magnitude"]
    horizon_hours: int
    threshold_used: float
    confidence_band: tuple[float, float] | None = None

    @field_validator("prob")
    @classmethod
    def _prob_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"prob must be in [0, 1]; got {v}")
        return v
