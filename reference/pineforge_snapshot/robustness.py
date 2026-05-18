"""Phase 8 — robustness, walk-forward, parameter sensitivity, locking.

Public surface (see `tests/test_phase8.py` for usage):

    walk_forward(spec, *, train_days=180, test_days=30, step_days=30)
        -> WalkForwardResult

    parameter_sensitivity(spec, perturb_pct=0.20)
        -> SensitivityResult

    lock_candidate(spec, *, name=None, baseline_spec=None,
                   min_test_sharpe=-0.25, allow_regime_negative=False)
        -> LockedSpec   # also writes pineforge/locked/<name>.yaml

The candidates we ship today have no learnable parameters — the recipe is
pure. Walk-forward therefore evaluates *parameter stability* by holding the
spec's params fixed and computing per-window strategy metrics on monthly
test slices. (A future phase can add an inner grid search over `train`.)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from . import data as _data
from . import eval as _eval
from .feeds import attach_feeds as _attach_feeds
from .schemas import RunSpec
from .trend import CANDIDATES


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class WalkForwardWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fold: int
    test_start: str
    test_end: str
    n_bars: int
    sharpe: float | None
    cagr: float | None
    max_drawdown: float | None
    n_trades: int


class WalkForwardResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: RunSpec
    train_days: int
    test_days: int
    step_days: int
    windows: list[WalkForwardWindow]
    n_windows: int
    median_sharpe: float | None
    worst_test_sharpe: float | None
    pct_positive: float | None  # fraction of windows with sharpe > 0


class SensitivityRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    param: str
    base_value: float
    perturbed_value: float
    direction: str  # "down" | "up"
    sharpe: float | None
    worst_regime_sharpe: float | None
    cagr: float | None
    max_drawdown: float | None


class SensitivityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: RunSpec
    perturb_pct: float
    base_headline: dict[str, float | None]
    rows: list[SensitivityRow]
    flips_verdict: bool  # True iff any perturbation flips sign of worst_regime_sharpe vs base


class LockedSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    locked_at: datetime
    spec: RunSpec
    walk_forward_summary: dict[str, Any]
    sensitivity_summary: dict[str, Any]
    gate_passes: bool
    gate_notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify(spec: RunSpec, df: pd.DataFrame) -> pd.DataFrame:
    cand = CANDIDATES[spec.candidate]
    if spec.feeds:
        df = _attach_feeds(df, spec.feeds, symbol=spec.symbol)
    return cand.classify(df, **spec.params)


def _load_full(spec: RunSpec) -> pd.DataFrame:
    df = _data.load(spec.symbol, spec.tf)
    if spec.start:
        df = df[df.index >= spec.start]
    if spec.end:
        df = df[df.index <= spec.end]
    return df


def _none_if_nan(x: Any) -> float | None:
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------

def walk_forward(
    spec: RunSpec,
    *,
    train_days: int = 180,
    test_days: int = 30,
    step_days: int = 30,
    cost_bps: float = 2.0,
) -> WalkForwardResult:
    """Roll non-overlapping monthly test windows after a `train_days` warmup.

    The candidate's params are held fixed (no inner grid search yet). We
    classify on a context window that includes `train_days` of warmup
    before each test slice so EMAs/ATRs are warm, then score only the
    test slice.
    """
    full = _load_full(spec)
    if len(full) < 100:
        raise ValueError("not enough bars for walk-forward")

    classified_full = _classify(spec, full)

    # Build window edges from the data span.
    start_ts = full.index[0] + pd.Timedelta(days=train_days)
    end_ts = full.index[-1]
    if start_ts >= end_ts:
        raise ValueError(
            f"train_days={train_days} exceeds span {full.index[0]} → {end_ts}"
        )

    windows: list[WalkForwardWindow] = []
    cursor = start_ts
    fold = 0
    while cursor < end_ts:
        win_end = min(cursor + pd.Timedelta(days=test_days), end_ts)
        slice_df = full[(full.index >= cursor) & (full.index < win_end)]
        slice_state = classified_full.loc[slice_df.index, "state"]
        if len(slice_df) >= 24:  # need at least a day of bars
            strat = _eval.strategy_proxy(slice_df, slice_state, cost_bps=cost_bps)
            windows.append(WalkForwardWindow(
                fold=fold,
                test_start=slice_df.index[0].isoformat(),
                test_end=slice_df.index[-1].isoformat(),
                n_bars=len(slice_df),
                sharpe=_none_if_nan(strat.sharpe),
                cagr=_none_if_nan(strat.cagr),
                max_drawdown=_none_if_nan(strat.max_drawdown),
                n_trades=int(strat.n_trades),
            ))
        cursor += pd.Timedelta(days=step_days)
        fold += 1

    sharpes = [w.sharpe for w in windows if w.sharpe is not None]
    median_s = float(np.median(sharpes)) if sharpes else None
    worst_s = float(np.min(sharpes)) if sharpes else None
    pct_pos = float(np.mean([s > 0 for s in sharpes])) if sharpes else None

    return WalkForwardResult(
        spec=spec,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        windows=windows,
        n_windows=len(windows),
        median_sharpe=median_s,
        worst_test_sharpe=worst_s,
        pct_positive=pct_pos,
    )


# ---------------------------------------------------------------------------
# Parameter sensitivity
# ---------------------------------------------------------------------------

_NUMERIC = (int, float)


def _headline_from_full(spec: RunSpec) -> dict[str, float | None]:
    """Compute headline metrics for a spec without persisting a run."""
    df = _load_full(spec)
    classified = _classify(spec, df)
    state = classified["state"]
    strat = _eval.strategy_proxy(df, state, cost_bps=2.0)
    regimes = _eval.label_regimes(df)
    per_reg = _eval.per_regime_metrics(df, state, regimes)
    regime_sharpes = [
        _none_if_nan(r.sharpe)
        for r in per_reg.values()
        if r is not None and _none_if_nan(r.sharpe) is not None
    ]
    wrs = min(regime_sharpes) if regime_sharpes else None
    return {
        "sharpe": _none_if_nan(strat.sharpe),
        "worst_regime_sharpe": wrs,
        "cagr": _none_if_nan(strat.cagr),
        "max_drawdown": _none_if_nan(strat.max_drawdown),
    }


def parameter_sensitivity(
    spec: RunSpec,
    *,
    perturb_pct: float = 0.20,
) -> SensitivityResult:
    """For each numeric param, perturb by ±perturb_pct and rerun.

    Integers are perturbed by `max(1, round(base * pct))`. Booleans, strings
    and None are skipped.
    """
    cand = CANDIDATES[spec.candidate]
    base_params = {**cand.defaults, **spec.params}

    base_headline = _headline_from_full(spec)
    base_wrs = base_headline.get("worst_regime_sharpe")

    rows: list[SensitivityRow] = []
    for key, val in base_params.items():
        if isinstance(val, bool) or not isinstance(val, _NUMERIC):
            continue
        if isinstance(val, int):
            delta = max(1, int(round(abs(val) * perturb_pct)))
            down_v: float = max(1, val - delta)
            up_v: float = val + delta
        else:
            down_v = float(val) * (1.0 - perturb_pct)
            up_v = float(val) * (1.0 + perturb_pct)
            # Guard ADX gates: ensure they remain in (0, 100).
            down_v = max(0.5, down_v)
            up_v = min(99.5, up_v) if "adx" in key else up_v

        for label, pv in (("down", down_v), ("up", up_v)):
            perturbed = {**spec.params, key: type(val)(pv)}
            try:
                p_spec = spec.model_copy(update={"params": perturbed})
                h = _headline_from_full(p_spec)
            except Exception as exc:  # noqa: BLE001
                h = {"sharpe": None, "worst_regime_sharpe": None,
                     "cagr": None, "max_drawdown": None}
                err_msg = str(exc)[:60]
                rows.append(SensitivityRow(
                    param=f"{key} (error: {err_msg})",
                    base_value=float(val),
                    perturbed_value=float(pv),
                    direction=label,
                    sharpe=None, worst_regime_sharpe=None,
                    cagr=None, max_drawdown=None,
                ))
                continue
            rows.append(SensitivityRow(
                param=key,
                base_value=float(val),
                perturbed_value=float(pv),
                direction=label,
                sharpe=h["sharpe"],
                worst_regime_sharpe=h["worst_regime_sharpe"],
                cagr=h["cagr"],
                max_drawdown=h["max_drawdown"],
            ))

    flips = False
    if base_wrs is not None:
        for r in rows:
            if r.worst_regime_sharpe is None:
                continue
            if (base_wrs >= 0) != (r.worst_regime_sharpe >= 0):
                flips = True
                break

    return SensitivityResult(
        spec=spec,
        perturb_pct=perturb_pct,
        base_headline=base_headline,
        rows=rows,
        flips_verdict=flips,
    )


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------

def _locked_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "locked"


def lock_candidate(
    spec: RunSpec,
    *,
    name: str | None = None,
    min_median_sharpe: float = 0.0,
    min_pct_positive: float = 0.5,
    allow_regime_negative: bool = False,
    train_days: int = 180,
    test_days: int = 30,
    step_days: int = 30,
    perturb_pct: float = 0.20,
    write_yaml: bool = True,
) -> LockedSpec:
    """Run walk-forward + sensitivity, evaluate gates, write locked YAML.

    Walk-forward gate is *aggregate*: the median test-window Sharpe must
    be ≥ `min_median_sharpe` and at least `min_pct_positive` of windows
    must show a positive Sharpe. We deliberately do not gate on the worst
    single window because BTC has months that destroy any trend system.
    """
    name = name or spec.candidate.lower()

    wf = walk_forward(
        spec,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
    )
    sens = parameter_sensitivity(spec, perturb_pct=perturb_pct)

    notes: list[str] = []
    passes = True

    # Gate 1: sensitivity must not flip sign of worst-regime Sharpe.
    if sens.flips_verdict:
        passes = False
        notes.append(
            f"sensitivity FAIL: a ±{perturb_pct:.0%} perturbation flips "
            f"sign of worst_regime_sharpe (base="
            f"{sens.base_headline['worst_regime_sharpe']})"
        )
    else:
        notes.append(f"sensitivity OK at ±{perturb_pct:.0%}")

    # Gate 2: walk-forward aggregate stability.
    if wf.median_sharpe is None or wf.pct_positive is None:
        passes = False
        notes.append("walk-forward FAIL: no scorable windows")
    elif wf.median_sharpe < min_median_sharpe:
        passes = False
        notes.append(
            f"walk-forward FAIL: median Sharpe {wf.median_sharpe:.3f} < "
            f"min_median_sharpe={min_median_sharpe}"
        )
    elif wf.pct_positive < min_pct_positive:
        passes = False
        notes.append(
            f"walk-forward FAIL: pct_positive {wf.pct_positive:.0%} < "
            f"min_pct_positive={min_pct_positive:.0%}"
        )
    else:
        notes.append(
            f"walk-forward OK: median={wf.median_sharpe:.3f}, "
            f"pct_positive={wf.pct_positive:.0%}, "
            f"worst={wf.worst_test_sharpe:.3f}, n={wf.n_windows}"
        )

    # Gate 3 (optional): no per-regime Sharpe collapses negative on full series.
    if not allow_regime_negative:
        df = _load_full(spec)
        classified = _classify(spec, df)
        regimes = _eval.label_regimes(df)
        per_reg = _eval.per_regime_metrics(df, classified["state"], regimes)
        neg = [
            (r, _none_if_nan(res.sharpe))
            for r, res in per_reg.items()
            if res is not None and _none_if_nan(res.sharpe) is not None
            and (_none_if_nan(res.sharpe) or 0) < 0
        ]
        if neg:
            passes = False
            notes.append(
                f"per-regime FAIL: negative Sharpe in regimes "
                f"{[r for r, _ in neg]}"
            )
        else:
            notes.append("per-regime OK: all in-sample regime Sharpes >= 0")

    locked = LockedSpec(
        name=name,
        locked_at=datetime.now(tz=timezone.utc),
        spec=spec,
        walk_forward_summary={
            "n_windows": wf.n_windows,
            "median_sharpe": wf.median_sharpe,
            "worst_test_sharpe": wf.worst_test_sharpe,
            "pct_positive": wf.pct_positive,
            "train_days": wf.train_days,
            "test_days": wf.test_days,
            "step_days": wf.step_days,
        },
        sensitivity_summary={
            "perturb_pct": sens.perturb_pct,
            "n_rows": len(sens.rows),
            "flips_verdict": sens.flips_verdict,
            "base_headline": sens.base_headline,
        },
        gate_passes=passes,
        gate_notes=notes,
    )

    if write_yaml and passes:
        out_dir = _locked_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}.yaml"
        # Strip the datetime to a plain string for YAML readability.
        payload = locked.model_dump(mode="json")
        path.write_text(yaml.safe_dump(payload, sort_keys=False))

    return locked
