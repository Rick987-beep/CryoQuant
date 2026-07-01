"""Model-tilted short-vol policy (D-13)."""
from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

from src.config_models import OptionBookSpec, OptionStructure

TiltMode = Literal["symmetric", "model_tilted"]


def resolve_tilt(
    p_up: float,
    cfg: OptionBookSpec,
    *,
    tilt_mode: TiltMode,
    put_below: float | None = None,
    call_above: float | None = None,
) -> Literal["symmetric", "call_heavy", "put_heavy"]:
    if tilt_mode == "symmetric" or not np.isfinite(p_up):
        return "symmetric"
    pb = put_below if put_below is not None else 1.0 - cfg.tilt_threshold
    ca = call_above if call_above is not None else cfg.tilt_threshold
    if p_up < pb:
        return "put_heavy"
    if p_up > ca:
        return "call_heavy"
    return "symmetric"


def compose_short_vol_signal(
    signals: pd.DataFrame,
    cfg: OptionBookSpec,
    *,
    vrp_threshold: float = 0.0,
    min_physical_edge: float = 0.0,
    tilt_mode: TiltMode = "symmetric",
    structure: OptionStructure | None = None,
) -> pd.DataFrame:
    """Add fire, tilt, chosen_delta, structure columns to composed signals frame."""
    out = signals.copy()
    vol_ok = out["vol_edge"] > vrp_threshold
    if out.get("exceedance_gate_active", pd.Series(True)).iloc[0] if len(out) else True:
        exc_ok = out["exceedance_edge"] > min_physical_edge
        exc_ok = exc_ok | out["exceedance_edge"].isna()
    else:
        exc_ok = pd.Series(True, index=out.index)
    out["fire"] = vol_ok & exc_ok

    tilts = []
    for p in out["p_up"]:
        tilts.append(resolve_tilt(float(p) if np.isfinite(p) else float("nan"), cfg, tilt_mode=tilt_mode))
    out["tilt"] = tilts
    out["chosen_delta"] = cfg.target_deltas[1] if len(cfg.target_deltas) > 1 else cfg.target_deltas[0]
    out["structure"] = (structure or cfg.default_structure).value
    out["vrp_threshold"] = vrp_threshold
    out["min_physical_edge"] = min_physical_edge
    out["tilt_mode"] = tilt_mode
    return out


def zero_vol_edge_signals(signals: pd.DataFrame, cfg: OptionBookSpec, **kwargs: Any) -> pd.DataFrame:
    """Policy with vol_edge forced to zero — for gate tests."""
    muted = signals.copy()
    muted["vol_edge"] = -1.0
    return compose_short_vol_signal(muted, cfg, **kwargs)
