"""Refresh helpers (no network)."""

import json
from datetime import datetime, timezone

from src.refresh import archive_outputs, quote_age_minutes, set_active_stamp


def test_set_active_stamp_rewrites_only_the_snapshot_block(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text('reference:\n  stamp: "2026-10-09T1456"\nsnapshot:\n  stamp: null\n')
    set_active_stamp("2026-10-12T0941", cfg)
    assert cfg.read_text() == (
        'reference:\n  stamp: "2026-10-09T1456"\nsnapshot:\n  stamp: "2026-10-12T0941"\n'
    )


def _outputs(root, stamp):
    (root / "data").mkdir()
    (root / "data" / "phase5_evaluate.json").write_text(json.dumps({"stamp": stamp}))
    (root / "RESULTS.md").write_text("results")


def test_archive_copies_outputs_of_the_matching_stamp(tmp_path):
    _outputs(tmp_path, "2026-10-12T0941")
    dest = archive_outputs("2026-10-12T0941", root=tmp_path)
    assert (dest / "RESULTS.md").read_text() == "results"
    assert (dest / "data" / "phase5_evaluate.json").is_file()
    assert archive_outputs("2026-10-12T0941", root=tmp_path) is None


def test_archive_skips_outputs_of_another_stamp(tmp_path):
    _outputs(tmp_path, "2026-10-12T0941")
    assert archive_outputs("2026-10-13T0930", root=tmp_path) is None
    assert not (tmp_path / "archive").exists()


def test_quote_age_minutes():
    m = {"quote": {"time": "2026-10-12T09:41:38.000+0200"}}
    now = datetime(2026, 10, 12, 8, 11, 38, tzinfo=timezone.utc)
    assert quote_age_minutes(m, now) == 30
