"""Smoke tests for france_sovereign_stress scaffolding."""

from __future__ import annotations

from src.paths import ANALYSIS_ROOT, load_config, v5_reference_dir


def test_analysis_root_layout() -> None:
    for name in ("config.yaml", "KICKOFF.md", "PLAN.md", "HANDOVER.md"):
        assert (ANALYSIS_ROOT / name).is_file()


def test_v5_reference_present() -> None:
    ref = v5_reference_dir()
    stamp = load_config()["reference"]["stamp"]
    assert (ref / "results" / f"v5_{stamp}.json").is_file()
    assert (ref / "data" / f"eurex_{stamp}.json").is_file()


def test_config_core_keys() -> None:
    cfg = load_config()
    assert cfg["budget_eur"] == 10000
    assert cfg["rules"]["spread_cap_foat"] == 20
