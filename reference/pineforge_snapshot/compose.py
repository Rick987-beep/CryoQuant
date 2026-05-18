"""Tiny composition DSL for trend candidates.

Phase 3 scope: just enough surface area to express ADX-gated EMA-slope-style
candidates as ~5-line recipes that produce the same state Series as the
hand-coded implementation.

Anatomy of a recipe:

    direction(expr)              # callable df -> pd.Series of {-1, 0, +1, NaN}
    .gate(enter=expr_bool,       # callable df -> pd.Series of bool/NaN
          exit=expr_bool)        # callable df -> pd.Series of bool/NaN
    .dwell(n)
    .build()                     # returns a callable (df) -> pd.Series

The state machine implemented by `.build()` mirrors `candidate_a_adx_ema`:

    state starts at 0.
    while state == 0:
        if enter is True and direction != 0: state = sign(direction)
    while state != 0:
        if exit is True or (direction != 0 and sign(direction) != state):
            state = 0
        # else: state unchanged

NaN handling: any NaN on the bar (direction, enter, or exit) forces state=0
on that bar (mirrors the hand-coded warmup guard).

Dwell smoothing: identical to the helper in trend.py — a new run must
persist `dwell` bars before it is reported; otherwise the previously reported
state holds.

This is deliberately small. We will extend it (vetoes, confirms, multi-
condition AND/OR, feed integration) in later phases when concrete candidates
need it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from . import trend as _trend

ExprCallable = Callable[[pd.DataFrame], pd.Series]


def _run_state_machine(
    direction: np.ndarray,
    enter: np.ndarray,
    exit_: np.ndarray,
) -> np.ndarray:
    """Pure function — same semantics as candidate_a_adx_ema's inner loop."""
    n = len(direction)
    raw = np.zeros(n, dtype=np.int8)
    state = 0
    for i in range(n):
        d = direction[i]
        en = enter[i]
        ex = exit_[i]
        if np.isnan(d) or np.isnan(en) or np.isnan(ex):
            raw[i] = 0
            state = 0
            continue
        if state == 0:
            if en > 0.5 and d != 0:
                state = int(d)
        else:
            if ex > 0.5 or (d != 0 and int(d) != state):
                state = 0
        raw[i] = state
    return raw


def _apply_dwell(raw: np.ndarray, dwell: int) -> np.ndarray:
    if dwell <= 1:
        return raw.astype(np.int8)
    n = len(raw)
    out = np.zeros(n, dtype=np.int8)
    reported = 0
    run_state = raw[0] if n else 0
    run_len = 1
    for i in range(n):
        if raw[i] == run_state:
            run_len += 1
        else:
            run_state = raw[i]
            run_len = 1
        if run_len >= dwell:
            reported = run_state
        out[i] = reported
    return out


@dataclass
class Composer:
    """Fluent builder. Methods return self; `build()` returns a callable."""
    _direction: ExprCallable | None = None
    _gate_enter: ExprCallable | None = None
    _gate_exit: ExprCallable | None = None
    _dwell: int = 1

    def direction(self, expr: ExprCallable) -> "Composer":
        self._direction = expr
        return self

    def gate(
        self,
        *,
        enter: ExprCallable,
        exit: ExprCallable,  # noqa: A002 — DSL keyword
    ) -> "Composer":
        self._gate_enter = enter
        self._gate_exit = exit
        return self

    def dwell(self, n: int) -> "Composer":
        if n < 1:
            raise ValueError("dwell must be >= 1")
        self._dwell = n
        return self

    def build(self) -> Callable[[pd.DataFrame], pd.DataFrame]:
        if self._direction is None:
            raise ValueError("direction(...) is required")
        if self._gate_enter is None or self._gate_exit is None:
            raise ValueError("gate(enter=..., exit=...) is required")

        direction_fn = self._direction
        enter_fn = self._gate_enter
        exit_fn = self._gate_exit
        dwell = self._dwell

        def _classify(df: pd.DataFrame) -> pd.DataFrame:
            d = np.asarray(direction_fn(df), dtype=float)
            en = np.asarray(enter_fn(df), dtype=float)
            ex = np.asarray(exit_fn(df), dtype=float)
            if not (len(d) == len(en) == len(ex) == len(df)):
                raise ValueError(
                    "compose: direction/enter/exit must align with df index"
                )
            raw = _run_state_machine(d, en, ex)
            smoothed = _apply_dwell(raw, dwell)
            state = pd.Series(smoothed, index=df.index, dtype="int8", name="state")
            return _trend.state_to_contract(state)

        return _classify


def compose() -> Composer:
    """Entry point: `recipe = compose().direction(...).gate(...).dwell(n).build()`"""
    return Composer()
