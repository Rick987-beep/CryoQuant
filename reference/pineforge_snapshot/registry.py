"""YAML registry loader for the bake-off.

Translates `registry.yaml` into a `(baseline_run_id, list[RunSpec])` pair the
agent_api.bakeoff can consume. Default params come from
`pineforge.trend.CANDIDATES[id].defaults`; any keys under `params:` in the
YAML override them.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .schemas import RunSpec
from .trend import CANDIDATES


def load_registry(path: Path | str = "registry.yaml") -> tuple[str | None, list[RunSpec]]:
    """Parse a registry YAML and return (baseline_run_id, specs).

    Resolution rules:
        - Workspace common config (`symbol`, `tf`, `start`, `end`) is applied
          to every spec, then per-entry overrides win.
        - Each candidate's defaults from `CANDIDATES[id].defaults` are merged
          with the entry's `params` (entry params win).
        - Entries with `enabled: false` are silently dropped.

    Returns:
        baseline_run_id : str or None — the RunSpec.run_id() of the entry
                          whose `id` matches the YAML's top-level `baseline:`,
                          or None if no baseline is declared.
        specs           : list[RunSpec] in YAML order, with code_git_ref unset.
    """
    path = Path(path)
    if not path.is_absolute():
        # search relative to workspace root (parent of `pineforge` package dir)
        ws_root = Path(__file__).resolve().parent.parent.parent
        candidate = ws_root / path
        if candidate.exists():
            path = candidate
    cfg = yaml.safe_load(path.read_text())

    common = {
        "symbol": cfg.get("symbol", "BTCUSDT"),
        "tf": cfg.get("tf", "1h"),
        "start": cfg.get("start"),
        "end": cfg.get("end"),
    }
    baseline_id: str | None = cfg.get("baseline")

    specs: list[RunSpec] = []
    baseline_run_id: str | None = None

    for entry in cfg.get("candidates", []) or []:
        if not entry.get("enabled", True):
            continue
        cid = entry["id"]
        if cid not in CANDIDATES:
            raise KeyError(f"unknown candidate {cid!r}; known: {list(CANDIDATES)}")

        merged_params = {**CANDIDATES[cid].defaults, **(entry.get("params") or {})}
        spec = RunSpec(
            candidate=cid,
            symbol=entry.get("symbol", common["symbol"]),
            tf=entry.get("tf", common["tf"]),
            start=entry.get("start", common["start"]),
            end=entry.get("end", common["end"]),
            params=merged_params,
            feeds=list(entry.get("feeds") or []),
            hold_bars=entry.get("hold_bars"),
        )
        specs.append(spec)
        if baseline_id is not None and cid == baseline_id and baseline_run_id is None:
            baseline_run_id = spec.run_id()

    return baseline_run_id, specs
