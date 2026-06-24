"""Optional QuantStats tearsheet export (requires ``[reports]`` extra)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_REPORTS_EXTRA_MSG = "Install optional reporting deps: pip install 'cryoquant[reports]'"


def _require_quantstats():
    try:
        import quantstats as qs
    except ImportError as exc:
        raise ImportError(_REPORTS_EXTRA_MSG) from exc
    return qs


def render_tearsheet(
    returns: pd.Series,
    out_html: str | Path,
    *,
    benchmark: pd.Series | str | None = None,
    title: str = "Strategy",
) -> Path:
    """Write a QuantStats HTML tearsheet for a return series.

    *returns* should be a datetime-indexed return series (e.g. daily pct changes).
    Requires the ``[reports]`` optional dependency group.
    """
    qs = _require_quantstats()
    out_path = Path(out_html).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    qs.reports.html(returns, benchmark=benchmark, title=title, output=str(out_path))
    return out_path
