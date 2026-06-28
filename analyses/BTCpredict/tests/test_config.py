"""Phase 0 config and split manifest tests (SPEC §6.3)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from src.config_models import (
    HorizonId,
    HorizonSpec,
    build_split_manifest,
    load_study_config,
    write_splits_json,
)
from src.paths import ANALYSIS_ROOT

# --- P0-T01: parse YAML; reject unknown keys ---


def test_load_study_config_parses_project_config() -> None:
    cfg = load_study_config(ANALYSIS_ROOT / "config.yaml")
    assert cfg.study_id == "btcpredict_v1"
    assert len(cfg.horizons) == 3
    assert cfg.splits.holdout_start == date(2024, 6, 1)
    assert cfg.splits.dev_end == date(2024, 5, 31)
    assert cfg.data_sources_reviewed is True
    assert cfg.data_sources_review_date == date(2026, 6, 28)
    assert cfg.phase1_complete is True
    assert cfg.phase1_complete_date == date(2026, 6, 28)
    assert cfg.phase2_catalog_reviewed is True
    assert cfg.phase2_catalog_review_date == date(2026, 6, 28)
    assert cfg.phase2_complete is True
    assert cfg.phase2_complete_date == date(2026, 6, 28)
    assert cfg.phase3_complete is True
    assert cfg.phase3_complete_date == date(2026, 6, 28)


def test_unknown_config_keys_rejected(tmp_path: Path) -> None:
    base = yaml.safe_load((ANALYSIS_ROOT / "config.yaml").read_text(encoding="utf-8"))
    base["bogus_key"] = True
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(ValidationError, match="bogus_key"):
        load_study_config(path)


# --- P0-T02: holdout_start ordering ---


def test_holdout_before_today() -> None:
    cfg = load_study_config(ANALYSIS_ROOT / "config.yaml")
    assert cfg.splits.holdout_start < date.today()
    assert cfg.splits.dev_start < cfg.splits.holdout_start


def test_holdout_in_future_rejected(tmp_path: Path) -> None:
    base = yaml.safe_load((ANALYSIS_ROOT / "config.yaml").read_text(encoding="utf-8"))
    base["splits"]["holdout_start"] = "2099-01-01"
    base["splits"]["dev_start"] = "2018-01-01"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(ValidationError, match="holdout_start"):
        load_study_config(path)


def test_dev_start_after_holdout_rejected(tmp_path: Path) -> None:
    base = yaml.safe_load((ANALYSIS_ROOT / "config.yaml").read_text(encoding="utf-8"))
    base["splits"]["holdout_start"] = "2024-06-01"
    base["splits"]["dev_start"] = "2024-06-01"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_study_config(path)


# --- P0-T03: run_phase0 idempotent splits.json ---


def test_run_phase0_writes_splits_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import run_phase0_config as phase0

    cfg_src = ANALYSIS_ROOT / "config.yaml"
    cfg_dst = tmp_path / "config.yaml"
    cfg_dst.write_text(cfg_src.read_text(encoding="utf-8"), encoding="utf-8")

    data = tmp_path / "data"
    data.mkdir()
    splits = data / "splits.json"

    monkeypatch.setattr(phase0, "config_path", lambda: cfg_dst)
    monkeypatch.setattr(phase0, "data_dir", lambda: data)
    monkeypatch.setattr(phase0, "splits_path", lambda: splits)

    assert phase0.main(["--config", str(cfg_dst)]) == 0
    assert splits.is_file()
    first = splits.read_bytes()

    assert phase0.main(["--config", str(cfg_dst)]) == 0
    second = splits.read_bytes()
    assert first == second


# --- P0-T04: SplitManifest immutability ---


def test_split_manifest_frozen() -> None:
    from src.config_models import SplitsInput

    m = build_split_manifest(
        SplitsInput(holdout_start=date(2024, 6, 1), dev_start=date(2018, 1, 1))
    )
    with pytest.raises(ValidationError):
        m.holdout_start = date(2020, 1, 1)  # type: ignore[misc]


# --- P0-T05: horizon specs ---


def test_horizon_bars_match_kickoff_mapping() -> None:
    cfg = load_study_config(ANALYSIS_ROOT / "config.yaml")
    by_id = {h.id: h for h in cfg.horizons}
    assert by_id[HorizonId.H1].horizon_bars == 1
    assert by_id[HorizonId.H5].horizon_bars == 5
    assert 10 <= by_id[HorizonId.H21].horizon_bars <= 21
    for h in cfg.horizons:
        assert len(h.dte_targets) >= 1


def test_horizon_wrong_bars_rejected() -> None:
    with pytest.raises(ValidationError, match="horizon_bars"):
        HorizonSpec(id=HorizonId.H1, horizon_bars=5, dte_targets=[1])


def test_write_splits_json_roundtrip(tmp_path: Path) -> None:
    cfg = load_study_config(ANALYSIS_ROOT / "config.yaml")
    out = tmp_path / "splits.json"
    write_splits_json(cfg, out)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["holdout_start"] == "2024-06-01"
    assert loaded["dev_end"] == "2024-05-31"


def test_phase2_complete_requires_phase1(tmp_path: Path) -> None:
    base = yaml.safe_load((ANALYSIS_ROOT / "config.yaml").read_text(encoding="utf-8"))
    base["phase2_complete"] = True
    base["phase1_complete"] = False
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(ValidationError, match="phase1_complete"):
        load_study_config(path)


def test_phase2_complete_requires_catalog(tmp_path: Path) -> None:
    base = yaml.safe_load((ANALYSIS_ROOT / "config.yaml").read_text(encoding="utf-8"))
    base["phase2_complete"] = True
    base["phase2_catalog_reviewed"] = False
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(ValidationError, match="phase2_catalog_reviewed"):
        load_study_config(path)


def test_reviewed_requires_date(tmp_path: Path) -> None:
    base = yaml.safe_load((ANALYSIS_ROOT / "config.yaml").read_text(encoding="utf-8"))
    base["data_sources_reviewed"] = True
    base["data_sources_review_date"] = None
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(ValidationError, match="data_sources_review_date"):
        load_study_config(path)
