"""Tests for cryoquant.features.panel."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from cryocore.instruments import Symbol
from cryoquant.features.builders import DatasetRef
from cryoquant.features.panel import DataPanel


START = datetime(2024, 1, 1, tzinfo=timezone.utc)
END = datetime(2024, 1, 15, tzinfo=timezone.utc)


def _bars(n: int = 10) -> pd.DataFrame:
    idx = pd.date_range(START, periods=n, freq="1D", tz="UTC")
    close = 100.0 + np.arange(n, dtype=float)
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1e6},
        index=idx,
    )


class TestDataPanel:
    def test_from_loads(self, monkeypatch) -> None:
        bars = _bars()
        vix = pd.Series(np.linspace(15, 20, len(bars)), index=bars.index, name="VIX")

        def fake_load(sym, tf, start, end):
            if sym.venue == "fred":
                return vix
            return bars

        monkeypatch.setattr("cryoquant.features.panel.load_track", fake_load)
        panel = DataPanel.from_loads(
            (Symbol("yahoo", "SPY"), "1d"),
            [("vix", Symbol("fred", "VIX"), "1d")],
            START,
            END,
        )
        assert len(panel.primary) == len(bars)
        assert "vix" in panel.tracks

    def test_align_track(self) -> None:
        bars = _bars()
        vix_idx = bars.index[::2]
        vix = pd.Series([18.0, 19.0, 20.0, 21.0, 22.0], index=vix_idx)
        ref = DatasetRef(Symbol("yahoo", "SPY"), "1d")
        panel = DataPanel(
            primary_ref=ref,
            primary=bars,
            tracks={"vix": vix},
            track_refs={"vix": DatasetRef(Symbol("fred", "VIX"), "1d")},
        )
        aligned = panel.align_track("vix")
        assert len(aligned) == len(bars)
        assert aligned.iloc[0] == 18.0

    def test_to_frames_series_macro(self) -> None:
        bars = _bars()
        vix = pd.Series([20.0] * len(bars), index=bars.index)
        ref_spy = DatasetRef(Symbol("yahoo", "SPY"), "1d")
        ref_vix = DatasetRef(Symbol("fred", "VIX"), "1d")
        panel = DataPanel(
            primary_ref=ref_spy,
            primary=bars,
            tracks={"vix": vix},
            track_refs={"vix": ref_vix},
        )
        frames = panel.to_frames()
        assert ref_spy in frames
        assert ref_vix in frames
        assert "value" in frames[ref_vix].columns

    def test_with_features(self) -> None:
        bars = _bars()
        ref = DatasetRef(Symbol("yahoo", "SPY"), "1d")
        panel = DataPanel(primary_ref=ref, primary=bars)
        feat = pd.DataFrame({"rsi": [50.0] * len(bars)}, index=bars.index)
        out = panel.with_features(feat)
        assert "rsi" in out.columns
        assert "close" in out.columns

    def test_align_track_missing_raises(self) -> None:
        panel = DataPanel(
            primary_ref=DatasetRef(Symbol("yahoo", "SPY"), "1d"),
            primary=_bars(),
        )
        with pytest.raises(KeyError):
            panel.align_track("nope")
