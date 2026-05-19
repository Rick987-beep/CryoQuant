"""Pine Script v5 emitter.

emit_pine(signal, name) -> str
    Generate a Pine Script v5 indicator stub for a BoolSignal or StateSignal.
    Raises TypeError for ProbSignal (probabilities cannot be expressed in Pine).

The output string:
    * Starts with "//@version=5"
    * Contains exactly one "indicator(" call
    * Is syntactically valid Pine v5 (as a stub — logic is not auto-generated)
"""
from __future__ import annotations

from cryoquant.signals.base import BoolSignal, ProbSignal, StateSignal


def emit_pine(
    signal: BoolSignal | StateSignal,
    name: str | None = None,
) -> str:
    """Return a Pine Script v5 snippet for *signal*.

    Args:
        signal: A BoolSignal or StateSignal.  ProbSignal raises TypeError.
        name:   Override the indicator title.  Defaults to signal.signal_id.

    Returns:
        Pine v5 source string, ready to paste into TradingView.

    Raises:
        TypeError: If *signal* is a ProbSignal.
    """
    if isinstance(signal, ProbSignal):
        raise TypeError(
            "ProbSignal cannot be expressed as Pine Script v5. "
            "Convert to BoolSignal or StateSignal first (e.g. via signals.from_model)."
        )

    title = name or signal.signal_id
    sid = signal.signal_id
    ver = signal.version

    if isinstance(signal, BoolSignal):
        return _bool_stub(title, sid, ver)
    if isinstance(signal, StateSignal):
        return _state_stub(title, sid, ver)

    raise TypeError(f"Unsupported signal type: {type(signal)}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bool_stub(title: str, signal_id: str, version: str) -> str:
    return f"""\
//@version=5
indicator("{title}", overlay=true, max_labels_count=500)

// Auto-generated stub by CryoQuant signals.publishers.pine_emitter
// Signal ID : {signal_id}
// Version   : {version}
//
// Replace the placeholder condition below with your actual Pine logic.
// All feature variables must be computed from closed-bar data only.

// ── Placeholder condition ─────────────────────────────────────────────────
signal = false  // TODO: implement signal logic

// ── Visualisation ─────────────────────────────────────────────────────────
plotshape(signal, title="{signal_id} Entry",
     style=shape.triangleup, location=location.belowbar,
     color=color.new(color.green, 0), size=size.small)
bgColor = signal ? color.new(color.green, 90) : na
bgcolor(bgColor, title="{signal_id} Background")
"""


def _state_stub(title: str, signal_id: str, version: str) -> str:
    return f"""\
//@version=5
indicator("{title}", overlay=false)

// Auto-generated stub by CryoQuant signals.publishers.pine_emitter
// Signal ID : {signal_id}
// Version   : {version}
//
// Replace the placeholder state below with your actual Pine logic.
// State values: +1 (bullish), 0 (neutral), -1 (bearish).

// ── Placeholder state ─────────────────────────────────────────────────────
state = 0  // TODO: implement state logic (+1 / 0 / -1)

// ── Visualisation ─────────────────────────────────────────────────────────
hline(1,  "Bull",  color.green, linestyle=hline.style_dashed)
hline(0,  "Flat",  color.gray,  linestyle=hline.style_dotted)
hline(-1, "Bear",  color.red,   linestyle=hline.style_dashed)
plot(state, title="{signal_id} State", color=color.blue, linewidth=2)
bgColor = state == 1  ? color.new(color.green, 90) :
          state == -1 ? color.new(color.red,   90) : na
bgcolor(bgColor, title="{signal_id} Background")
"""
