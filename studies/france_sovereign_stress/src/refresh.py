"""Refresh market data and rerun the study on it.

One call takes a live snapshot (CNBC quote for the entry, closes up to the last
full session), makes it the active stamp in ``config.yaml``, and runs phases 1–5
plus both explorers against it. The outputs of the previous run are copied to
``archive/<previous stamp>/`` first so a refresh never overwrites them silently.
If a step fails, ``config.yaml`` points back at the previous stamp.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.paths import ANALYSIS_ROOT, SNAPSHOT_ENV, active_stamp, config_path, snapshots_dir

OUTPUT_FILES = ("RESULTS.md", "EXPLORE.md", "explore.html", "explore_interactive.html")
DATA_FILES = (
    "phase1_probe.json",
    "phase2_pricing.json",
    "phase3_paths.json",
    "phase4_rules.json",
    "phase5_evaluate.json",
    "exit_level_grid.json",
    "canvas_explore.json",
)
PIPELINE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("run_phase1_data.py", ()),
    ("run_phase2_pricing.py", ()),
    ("run_phase3_paths.py", ()),
    ("run_phase4_rules.py", ()),
    ("run_phase5_evaluate.py", ()),
    ("run_explore_report.py", ()),
    ("run_explore_interactive.py", ()),
)
QUOTE_MAX_AGE_MIN = 30


def set_active_stamp(stamp: str, path: Path | None = None) -> None:
    """Write ``snapshot.stamp`` in ``config.yaml``."""
    path = path or config_path()
    text = path.read_text()
    new, n = re.subn(r"(?m)^(snapshot:\n  stamp: )\S+", rf'\g<1>"{stamp}"', text)
    if n != 1:
        raise SystemExit("config.yaml: could not find the 'snapshot:\\n  stamp:' block")
    path.write_text(new)


def archive_outputs(stamp: str, root: Path = ANALYSIS_ROOT) -> Path | None:
    """Copy the current outputs to ``archive/<stamp>/`` unless already there.

    Skips when the outputs on disk belong to another stamp, so an archive is
    never labelled with the wrong snapshot.
    """
    dest = root / "archive" / stamp
    p5 = root / "data" / "phase5_evaluate.json"
    if dest.exists() or not p5.is_file():
        return None
    if json.loads(p5.read_text()).get("stamp") != stamp:
        return None
    (dest / "data").mkdir(parents=True)
    for name in OUTPUT_FILES:
        if (root / name).is_file():
            shutil.copy2(root / name, dest / name)
    for name in DATA_FILES:
        if (root / "data" / name).is_file():
            shutil.copy2(root / "data" / name, dest / "data" / name)
    return dest


def quote_age_minutes(manifest: dict, now: datetime | None = None) -> float | None:
    t = (manifest.get("quote") or {}).get("time")
    if not t:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - datetime.fromisoformat(t)).total_seconds() / 60


@dataclass
class RefreshResult:
    stamp: str
    previous: str
    archived: Path | None
    manifest: dict
    warnings: list[str] = field(default_factory=list)
    log_dir: Path | None = None


def run_pipeline(stamp: str, log_dir: Path, root: Path = ANALYSIS_ROOT) -> None:
    """Run every pipeline script against ``stamp``; raise on the first failure."""
    log_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, SNAPSHOT_ENV: stamp}
    for script, args in PIPELINE:
        log = log_dir / f"{Path(script).stem}.log"
        print(f"  {script} ...", end=" ", flush=True)
        with log.open("w") as fh:
            proc = subprocess.run(
                [sys.executable, str(root / script), *args],
                cwd=root.parents[1], env=env, stdout=fh, stderr=subprocess.STDOUT,
            )
        print("ok" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})")
        if proc.returncode != 0:
            raise RuntimeError(f"{script} failed; see {log}")


def refresh(stamp: str | None = None, *, reuse: bool = False) -> RefreshResult:
    """Take (or reuse) a snapshot, activate it and rerun the study."""
    from src.data.snapshot import build_snapshot

    previous = active_stamp()
    archived = archive_outputs(previous)

    if reuse:
        if not stamp:
            raise ValueError("reuse needs an explicit stamp")
        data = snapshots_dir() / stamp / "data"
        if not data.is_dir():
            raise FileNotFoundError(data)
    else:
        data = build_snapshot(stamp)
    manifest = json.loads((data.parent / "manifest.json").read_text())
    stamp = manifest["stamp"]

    warnings = []
    age = quote_age_minutes(manifest)
    if age is not None and age > QUOTE_MAX_AGE_MIN and not reuse:
        warnings.append(
            f"entry quote is {age:.0f} min old ({manifest['quote']['time']}); "
            "the market may be closed"
        )

    set_active_stamp(stamp)
    log_dir = ANALYSIS_ROOT / "reports" / "refresh" / stamp
    try:
        run_pipeline(stamp, log_dir)
    except Exception:
        set_active_stamp(previous)
        raise
    return RefreshResult(stamp, previous, archived, manifest, warnings, log_dir)
