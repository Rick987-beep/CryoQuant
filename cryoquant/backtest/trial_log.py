"""Append-only trial log for deflated Sharpe trial counting."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def trial_log_path(data_dir: Path) -> Path:
    return data_dir / "trial_log.jsonl"


def count_trials(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def append_trial(path: Path, entry: dict[str, Any]) -> int:
    """Append one JSON line; return assigned trial_id (1-based)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    trial_id = count_trials(path) + 1
    record = {
        "trial_id": trial_id,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        **entry,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
    return trial_id


def append_training_session(
    path: Path,
    *,
    session_id: str,
    phase: str,
    runs: list[dict[str, Any]],
    reproducibility: dict[str, Any],
) -> None:
    for run in runs:
        append_trial(
            path,
            {
                "phase": phase,
                "session_id": session_id,
                "run_id": run.get("run_id"),
                "head": run.get("head"),
                "asset": run.get("asset"),
                "horizon_id": run.get("horizon_id"),
                "label_name": run.get("label_name"),
                "params": {
                    "model_id": run.get("model_id"),
                    "feature_count": run.get("feature_count"),
                    "folds_used": run.get("folds_used"),
                },
                "metric": run.get("aggregate_metrics"),
                "baseline_metric": run.get("baseline_metrics"),
                "metric_delta": run.get("metric_delta"),
                "reproducibility": reproducibility,
            },
        )
