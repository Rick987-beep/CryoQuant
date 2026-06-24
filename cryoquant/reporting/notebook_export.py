"""Optional notebook → HTML export (requires ``[reports]`` extra)."""
from __future__ import annotations

from pathlib import Path

_REPORTS_EXTRA_MSG = "Install optional reporting deps: pip install 'cryoquant[reports]'"


def _require_nbconvert() -> None:
    try:
        import nbconvert  # noqa: F401
    except ImportError as exc:
        raise ImportError(_REPORTS_EXTRA_MSG) from exc


def export_notebook(
    ipynb: str | Path,
    out_html: str | Path,
    *,
    execute: bool = False,
) -> Path:
    """Export a Jupyter notebook to static HTML.

    Requires the ``[reports]`` optional dependency group (nbconvert).
    """
    _require_nbconvert()
    import nbformat
    from nbconvert import HTMLExporter

    ipynb_path = Path(ipynb).resolve()
    out_path = Path(out_html).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if execute:
        raise NotImplementedError(
            "Notebook execution before export is not implemented; run the notebook first."
        )

    nb = nbformat.read(ipynb_path, as_version=4)
    body, _resources = HTMLExporter().from_notebook_node(nb)
    out_path.write_text(body, encoding="utf-8")
    return out_path
