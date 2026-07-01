"""Reproducibility metadata for study artifacts."""
from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_prefix(path: Path, n: int = 16) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:n]


def git_commit_short(repo_root: Path) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()[:12]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def build_repro_bundle(
    *,
    files: dict[str, Path],
    metadata: dict[str, Any] | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Return git commit + SHA256 prefixes for replay audit.

    Field names align with ``RunBundle`` meta conventions (``git_commit``, file hashes).
    """
    meta = dict(metadata or {})
    file_hashes = {name: sha256_prefix(p) for name, p in files.items()}
    bundle: dict[str, Any] = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "file_hashes": file_hashes,
        **meta,
    }
    if repo_root is not None:
        bundle["git_commit"] = git_commit_short(repo_root)
    return bundle


def repro_bundle_complete(
    bundle: dict[str, Any],
    *,
    required_files: tuple[str, ...],
) -> bool:
    hashes = bundle.get("file_hashes") or {}
    return all(hashes.get(k) for k in required_files)
