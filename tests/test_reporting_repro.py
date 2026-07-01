"""Tests for cryoquant.reporting.repro."""
from __future__ import annotations

from pathlib import Path

from cryoquant.reporting.repro import build_repro_bundle, repro_bundle_complete, sha256_prefix


def test_sha256_prefix(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("hello", encoding="utf-8")
    h = sha256_prefix(p)
    assert h is not None
    assert len(h) == 16


def test_build_repro_bundle(tmp_path: Path) -> None:
    f1 = tmp_path / "config.yaml"
    f1.write_text("x: 1\n", encoding="utf-8")
    bundle = build_repro_bundle(
        files={"config.yaml": f1},
        metadata={"study_id": "test"},
        repo_root=tmp_path,
    )
    assert bundle["study_id"] == "test"
    assert bundle["file_hashes"]["config.yaml"] is not None
    assert "built_at" in bundle


def test_repro_bundle_complete() -> None:
    assert repro_bundle_complete(
        {"file_hashes": {"config.yaml": "abc", "training.yaml": "def"}},
        required_files=("config.yaml", "training.yaml"),
    )
    assert not repro_bundle_complete(
        {"file_hashes": {"config.yaml": "abc"}},
        required_files=("config.yaml", "training.yaml"),
    )
