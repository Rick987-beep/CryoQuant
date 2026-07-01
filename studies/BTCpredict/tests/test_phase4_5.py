"""Phase 4.5 transparency — repro bundle, trial log, QA gates."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.phase4_qa import run_phase4_qa
from src.repro_bundle import build_repro_bundle, repro_bundle_complete
from src.trial_log import append_trial, count_trials, trial_log_path


@pytest.fixture
def cfg():
    from src.paths import load_study_config

    return load_study_config()


def test_repro_bundle_has_required_hashes(cfg, tmp_path, monkeypatch) -> None:
    from src import paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    (tmp_path / "features_schema.json").write_text("{}")
    (tmp_path / "labels_schema.json").write_text("{}")
    bundle = build_repro_bundle(cfg)
    assert bundle.get("git_commit")
    assert bundle.get("file_hashes", {}).get("config.yaml")
    assert repro_bundle_complete(bundle)


def test_trial_log_append_only(tmp_path) -> None:
    path = trial_log_path(tmp_path)
    assert count_trials(path) == 0
    tid1 = append_trial(path, {"run_id": "a"})
    tid2 = append_trial(path, {"run_id": "b"})
    assert tid1 == 1 and tid2 == 2
    assert count_trials(path) == 2
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["trial_id"] == 1


def test_qa_rejects_v1_manifest_without_baseline(tmp_path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "runs": [
                    {
                        "run_id": "x",
                        "head": "directional",
                        "asset": "BTC",
                        "status": "ok",
                        "baseline_metrics": {},
                        "aggregate_metrics": {"auc": 0.53},
                        "folds_used": 6,
                    }
                ],
            }
        )
    )
    report = run_phase4_qa(manifest)
    assert report.errors >= 2  # version + no baseline


def test_qa_passes_minimal_v2_manifest(tmp_path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 2,
                "session_id": "abc123",
                "reproducibility": {
                    "file_hashes": {
                        "config.yaml": "aaa",
                        "training.yaml": "bbb",
                        "features_schema.json": "ccc",
                        "labels_schema.json": "ddd",
                    }
                },
                "runs": [
                    {
                        "run_id": "smoke_btc_up_h1",
                        "head": "directional",
                        "asset": "BTC",
                        "status": "ok",
                        "baseline_metrics": {"auc": 0.50},
                        "aggregate_metrics": {"auc": 0.53},
                        "metric_delta": {"auc_delta": 0.03},
                        "fold_ledger": [{"fold_id": 0}],
                        "folds_used": 6,
                        "folds_scheduled": 6,
                        "gates": {"beats_baseline": True},
                        "n_oos": 100,
                    }
                ],
            }
        )
    )
    report = run_phase4_qa(manifest)
    assert report.errors == 0
