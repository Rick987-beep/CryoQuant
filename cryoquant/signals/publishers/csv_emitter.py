"""CSV (parquet) emitter — materialises a signal's history to disk.

emit_history(signal, X, out_path) -> Path

Output schema
-------------
ts (index, DatetimeIndex UTC)
signal_id    str
version      str
value        bool     — True if the signal fired (or prob >= threshold for ProbSignal)
prob         float    — probability (NaN for Bool/State signals)
state        int8     — state (-1/0/1 for StateSignal, NaN otherwise)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from cryoquant.signals.base import BoolSignal, ProbSignal, StateSignal


def emit_history(
    signal: BoolSignal | StateSignal | ProbSignal,
    X: pd.DataFrame,
    out_path: Path | str,
) -> Path:
    """Apply *signal* to every row of *X* and write a parquet file.

    Args:
        signal:   A BoolSignal, StateSignal, or ProbSignal instance.
        X:        Feature DataFrame with a tz-aware DatetimeIndex.
        out_path: Destination path (.parquet recommended).

    Returns:
        Absolute Path to the written file.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    n = len(X)
    signal_id_col = [signal.signal_id] * n
    version_col = [signal.version] * n

    if isinstance(signal, BoolSignal):
        values = signal.as_feature(X).values.astype(bool)
        df_out = pd.DataFrame(
            {
                "signal_id": signal_id_col,
                "version": version_col,
                "value": values,
                "prob": np.full(n, np.nan, dtype=float),
                "state": np.full(n, np.nan, dtype=float),
            },
            index=X.index,
        )

    elif isinstance(signal, ProbSignal):
        probs = signal.as_feature(X).values
        values = probs >= signal.default_threshold
        df_out = pd.DataFrame(
            {
                "signal_id": signal_id_col,
                "version": version_col,
                "value": values.astype(bool),
                "prob": probs.astype(float),
                "state": np.full(n, np.nan, dtype=float),
            },
            index=X.index,
        )

    elif isinstance(signal, StateSignal):
        states = signal.as_feature(X).values
        df_out = pd.DataFrame(
            {
                "signal_id": signal_id_col,
                "version": version_col,
                "value": (states != 0).astype(bool),
                "prob": np.full(n, np.nan, dtype=float),
                "state": states.astype(float),
            },
            index=X.index,
        )

    else:
        raise TypeError(f"Unsupported signal type: {type(signal)}")

    df_out.index.name = "ts"
    df_out.to_parquet(out_path)
    return out_path.resolve()
