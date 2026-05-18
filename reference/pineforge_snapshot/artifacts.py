"""Artifact persistence: write/read run directories.

Layout:
    pineforge/runs/<run_id>/
        spec.json
        result.json
        state.parquet
        report.html      (optional)

Run dirs are content-addressable via RunSpec.run_id(). Re-running the same
spec overwrites the same dir, so re-runs are idempotent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .schemas import SCHEMA_VERSION, RunResult, RunSpec

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
RUNS_DIR = WORKSPACE_ROOT / "pineforge" / "runs"
COMPARISONS_DIR = WORKSPACE_ROOT / "pineforge" / "comparisons"


def _rel(path: Path) -> str:
    """Workspace-relative POSIX path string."""
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT))
    except ValueError:
        return str(path)


def run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id


def write_run(
    *,
    spec: RunSpec,
    result_kwargs: dict,
    state_df: pd.DataFrame,
    report_html_src: Path | None,
) -> RunResult:
    """Materialize all artifacts for one run; return the RunResult.

    `result_kwargs` is everything needed to construct RunResult except the
    artifact paths and run_id (which we set here).
    """
    rid = spec.run_id()
    out = run_dir(rid)
    out.mkdir(parents=True, exist_ok=True)

    # 1. state.parquet
    state_path = out / "state.parquet"
    state_df.to_parquet(state_path)

    # 2. spec.json
    (out / "spec.json").write_text(spec.model_dump_json(indent=2))

    # 3. report.html (move/copy if the caller produced one)
    report_rel: str | None = None
    if report_html_src is not None and Path(report_html_src).exists():
        dst = out / "report.html"
        dst.write_bytes(Path(report_html_src).read_bytes())
        report_rel = _rel(dst)

    # 4. RunResult
    result = RunResult(
        run_id=rid,
        spec=spec,
        created_at=datetime.now(tz=timezone.utc),
        state_parquet=_rel(state_path),
        report_html=report_rel,
        **result_kwargs,
    )
    (out / "result.json").write_text(result.model_dump_json(indent=2))
    return result


def read_run(run_id: str) -> RunResult:
    out = run_dir(run_id)
    text = (out / "result.json").read_text()
    return RunResult.model_validate_json(text)


def read_state(run_id: str) -> pd.DataFrame:
    return pd.read_parquet(run_dir(run_id) / "state.parquet")


def list_runs() -> list[str]:
    if not RUNS_DIR.exists():
        return []
    return sorted(p.name for p in RUNS_DIR.iterdir() if p.is_dir() and (p / "result.json").exists())


def find_run(spec: RunSpec) -> RunResult | None:
    """Return the existing RunResult for this spec, or None if not yet run."""
    from pydantic import ValidationError
    rid = spec.run_id()
    result_path = run_dir(rid) / "result.json"
    if result_path.exists():
        try:
            r = read_run(rid)
            if r.schema_version != SCHEMA_VERSION:
                return None  # stale schema — will be recomputed with new metrics
            return r
        except (ValidationError, Exception):
            # Cached result is incompatible with current schema — treat as cache miss.
            return None
    return None


# ---------------------------------------------------------------------------
# Comparison persistence
# ---------------------------------------------------------------------------

def comparison_dir(comparison_id: str) -> Path:
    return COMPARISONS_DIR / comparison_id


def write_comparison(comparison, *, overview_html: str | None = None) -> Path:
    """Persist a Comparison + optional human overview HTML."""
    out = comparison_dir(comparison.comparison_id)
    out.mkdir(parents=True, exist_ok=True)
    (out / "comparison.json").write_text(comparison.model_dump_json(indent=2))
    if overview_html is not None:
        (out / "overview.html").write_text(overview_html)
    return out


def read_comparison(comparison_id: str):
    from .schemas import Comparison
    text = (comparison_dir(comparison_id) / "comparison.json").read_text()
    return Comparison.model_validate_json(text)
