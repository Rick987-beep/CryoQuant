"""CryoBacktester bridge — adapt a CryoQuant Signal to CryoBacktester's Strategy protocol.

CryoBacktester is a sibling repo discovered via ``config.CRYOBACKTESTER_ROOT``.
This module provides ``CryoBTAdapter``, which wraps a CryoQuant signal and
presents the interface CryoBacktester expects from a ``Strategy``.

**No actual CryoBacktester import at module level** — import is lazy so this
module loads fine without CryoBacktester present.

Duck-typed Strategy interface (as expected by CryoBacktester)::

    class Strategy(Protocol):
        name: str
        description: str
        def generate_signals(df: pd.DataFrame) -> pd.Series: ...
        def get_parameters() -> dict: ...

Usage::

    from cryoquant.backtest.cryobt_bridge import CryoBTAdapter
    from cryoquant.signals.base import BoolSignal

    signal = BoolSignal("pullback_v1", condition_fn)
    adapter = CryoBTAdapter(signal, threshold=0.5)
    # Optionally:
    adapter.run(start="2025-01-01", end="2025-06-01")
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)


class CryoBTAdapter:
    """Wraps a CryoQuant BoolSignal or ProbSignal as a CryoBacktester Strategy.

    This adapter satisfies CryoBacktester's duck-typed ``Strategy`` interface:
    - ``name`` attribute
    - ``description`` attribute
    - ``generate_signals(df) -> pd.Series`` of {-1, 0, 1}
    - ``get_parameters() -> dict``

    Parameters
    ----------
    signal:     A CryoQuant BoolSignal, StateSignal, or ProbSignal.
    threshold:  Probability threshold for ProbSignal (ignored for Bool/State).
    """

    def __init__(self, signal: Any, threshold: float = 0.5) -> None:
        self._signal = signal
        self.threshold = threshold
        self.name = f"cryoquant_{getattr(signal, 'signal_id', 'unknown')}"
        self.description = (
            f"CryoQuant signal '{getattr(signal, 'signal_id', '?')}' "
            f"v{getattr(signal, 'version', '?')} via CryoBTAdapter"
        )

    # ── Duck-typed Strategy interface ─────────────────────────────────────────

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Generate {-1, 0, 1} position signals from *df*.

        ProbSignal fires are mapped to +1 when prob >= threshold, else 0.
        BoolSignal fires map True -> +1, False -> 0.
        StateSignal passes through {-1, 0, 1} directly.
        """
        from cryoquant.signals.base import ProbSignal, StateSignal

        if isinstance(self._signal, ProbSignal):
            probs = self._signal.as_feature(df)
            return (probs >= self.threshold).astype(int).rename(self.name)
        elif isinstance(self._signal, StateSignal):
            states = self._signal.as_feature(df)
            return states.fillna(0).astype(int).rename(self.name)
        else:
            # BoolSignal or duck-typed object
            bools = self._signal.as_feature(df).fillna(False)
            return bools.astype(int).rename(self.name)

    def get_parameters(self) -> dict:
        """Return strategy parameters as a plain dict."""
        return {
            "signal_id": getattr(self._signal, "signal_id", None),
            "version": getattr(self._signal, "version", None),
            "threshold": self.threshold,
            "signal_type": type(self._signal).__name__,
        }

    # ── Optional: run via CryoBacktester ─────────────────────────────────────

    def run(
        self,
        start: str | None = None,
        end: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Discover CryoBacktester and run this strategy.

        Requires ``config.CRYOBACKTESTER_ROOT`` to point to the CryoBacktester
        source root. Returns whatever CryoBacktester's run entrypoint returns.

        Parameters
        ----------
        start: ISO date string for the backtest window start.
        end:   ISO date string for the backtest window end.
        **kwargs: Passed through to CryoBacktester's run call.

        Raises
        ------
        ImportError  if CRYOBACKTESTER_ROOT is not set or CryoBacktester
                     cannot be imported.
        """
        import sys
        from cryoquant import config

        root = config.CRYOBACKTESTER_ROOT if hasattr(config, "CRYOBACKTESTER_ROOT") else None
        if root is None or not root.exists():
            raise ImportError(
                "CRYOBACKTESTER_ROOT is not set or does not exist. "
                "Set config.CRYOBACKTESTER_ROOT to the CryoBacktester source root."
            )

        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        try:
            import backtester  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                f"Could not import CryoBacktester from {root}: {exc}"
            ) from exc

        log.info("CryoBTAdapter.run: start=%s end=%s root=%s", start, end, root)
        return backtester.run_strategy(self, start=start, end=end, **kwargs)
