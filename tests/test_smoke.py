"""Smoke test: package imports and basic config is sane."""

from pathlib import Path


def test_cryoquant_imports() -> None:
    import cryoquant

    assert cryoquant.__version__


def test_cryocore_imports() -> None:
    import cryocore

    assert cryocore.__version__


def test_config_paths_are_paths() -> None:
    from cryoquant import config

    assert isinstance(config.ROOT, Path)
    assert isinstance(config.CRYOBACKTESTER_DATA_DIR, Path)
    assert config.ROOT.exists()


def test_reference_material_present() -> None:
    """The reference/ tree must exist — it's what the next agent learns from."""
    from cryoquant import config

    ref = config.ROOT / "reference"
    assert (ref / "long_tradable_options" / "V2_PLAN.md").exists()
    assert (ref / "pineforge_snapshot" / "data.py").exists()
    assert (ref / "pineforge_snapshot" / "schemas.py").exists()


def test_docs_present() -> None:
    from cryoquant import config

    docs = config.ROOT / "docs"
    assert (docs / "quant_plan.md").exists()
    assert (docs / "decisions.md").exists()
    assert (docs / "glossary.md").exists()
