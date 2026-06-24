"""Per-phase JSON summaries for study reporting."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def write_phase_summary(
    path: Path | str,
    *,
    phase_id: str,
    metrics: dict[str, Any] | None = None,
    artifacts: dict[str, str] | None = None,
    status: str = "ok",
    notes: str | None = None,
) -> Path:
    """Write a ``phase_<n>_<name>.json`` style summary file."""
    out = Path(path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "phase_id": phase_id,
        "status": status,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metrics": metrics or {},
        "artifacts": artifacts or {},
    }
    if notes:
        payload["notes"] = notes
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return out
