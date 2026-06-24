"""Multi-track data panel for complex feature / ML studies.

Lightweight container — not a feature store.  Holds a primary OHLCV frame plus
named extra tracks (OHLCV or macro Series).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from cryocore.instruments import Symbol
from cryoquant.data.resolve import is_ohlcv_symbol, load_track
from cryoquant.features.align import align_series
from cryoquant.features.builders import DatasetRef


@dataclass
class DataPanel:
    """Aligned multi-track bag for FeatureBuilder inputs."""

    primary_ref: DatasetRef
    primary: pd.DataFrame
    tracks: dict[str, pd.DataFrame | pd.Series] = field(default_factory=dict)
    track_refs: dict[str, DatasetRef] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_loads(
        cls,
        primary: tuple[Symbol, str],
        extras: list[tuple[str, Symbol, str]],
        start: datetime,
        end: datetime,
    ) -> DataPanel:
        """Load primary OHLCV + named extra tracks via ``load_track``."""
        p_sym, p_tf = primary
        p_data = load_track(p_sym, p_tf, start, end)
        if not isinstance(p_data, pd.DataFrame):
            raise TypeError(f"primary {primary!r} must resolve to OHLCV DataFrame")
        primary_ref = DatasetRef(p_sym, p_tf)
        tracks: dict[str, pd.DataFrame | pd.Series] = {}
        track_refs: dict[str, DatasetRef] = {}
        for name, sym, tf in extras:
            track_refs[name] = DatasetRef(sym, tf)
            tracks[name] = load_track(sym, tf, start, end)
        return cls(
            primary_ref=primary_ref,
            primary=p_data,
            tracks=tracks,
            track_refs=track_refs,
        )

    def align_track(
        self,
        name: str,
        *,
        ffill_limit: int | None = 35,
    ) -> pd.Series:
        """Align a named track onto ``primary.index``."""
        if name not in self.tracks:
            raise KeyError(f"track {name!r} not in panel (have {list(self.tracks)})")
        track = self.tracks[name]
        if isinstance(track, pd.DataFrame):
            col = "close" if "close" in track.columns else track.select_dtypes("number").columns[0]
            ser = track[col]
        else:
            ser = track
        return align_series(self.primary.index, ser, ffill_limit=ffill_limit, name=name)

    def to_frames(self) -> dict[DatasetRef, pd.DataFrame]:
        """Convert to FeatureBuilder ``frames`` dict (Series → single-col DataFrame)."""
        frames: dict[DatasetRef, pd.DataFrame] = {self.primary_ref: self.primary}
        for name, track in self.tracks.items():
            ref = self.track_refs.get(name)
            if ref is None:
                continue
            if isinstance(track, pd.Series):
                col = "close" if is_ohlcv_symbol(ref.symbol) else "value"
                frames[ref] = track.rename(col).to_frame()
            else:
                frames[ref] = track
        return frames

    def with_features(self, features: pd.DataFrame) -> pd.DataFrame:
        """Inner-join feature columns onto primary bars."""
        overlap = set(self.primary.columns) & set(features.columns)
        if overlap:
            features = features.drop(columns=list(overlap))
        return self.primary.join(features, how="inner")
