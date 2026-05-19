"""Feature store: @cached decorator for Tier-2 FeatureBuilders.

Cache layout::

    FEATURE_STORE_DIR/<builder_id>/v=<version>/<venue>_<ticker>_<tf>__<start>__<end>.parquet

Cache key includes (builder.id, version, symbol str, tf, start, end) so a
version bump invalidates automatically.
"""
from __future__ import annotations

import functools
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from cryoquant import config

log = logging.getLogger(__name__)


def _cache_key(*parts: Any) -> str:
    blob = json.dumps([str(p) for p in parts], sort_keys=True).encode()
    return hashlib.sha1(blob).hexdigest()[:16]


def _cache_path(builder_id: str, version: str, key: str) -> Path:
    return (
        config.FEATURE_STORE_DIR
        / builder_id
        / f"v={version}"
        / f"{key}.parquet"
    )


def cached(build_fn: Callable | None = None, *, builder_id: str = "", version: str = ""):
    """Decorator: cache the output of a FeatureBuilder.build() method.

    Usage (applied to a build method on a FeatureBuilder class)::

        class MyBuilder:
            id = "my_builder"
            version = "1"

            @cached
            def build(self, frames):
                ...

    Or as a standalone decorator with explicit id/version::

        @cached(builder_id="my_fn", version="1")
        def build(frames):
            ...
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(self_or_frames, frames=None, **kw):
            # Support both method (self, frames) and standalone function (frames)
            if frames is None:
                # standalone function call: self_or_frames IS frames
                _frames = self_or_frames
                _id = builder_id
                _ver = version
                _self = None
            else:
                _frames = frames
                _self = self_or_frames
                _id = getattr(_self, "id", builder_id) or builder_id
                _ver = getattr(_self, "version", version) or version

            # Build a deterministic cache key from all frame shapes/ranges
            key_parts = [_id, _ver]
            for k, df in sorted(_frames.items(), key=lambda x: str(x[0])):
                key_parts += [str(k), str(len(df)),
                               str(df.index.min()), str(df.index.max())]
            key = _cache_key(*key_parts)

            path = _cache_path(_id, _ver, key)

            if path.exists():
                log.debug("Cache hit: %s", path)
                return pd.read_parquet(path)

            log.debug("Cache miss: building %s v%s", _id, _ver)
            if _self is not None:
                result = fn(_self, _frames, **kw)
            else:
                result = fn(_frames, **kw)

            path.parent.mkdir(parents=True, exist_ok=True)
            result.to_parquet(path)
            log.debug("Cached to %s", path)
            return result

        return wrapper

    if build_fn is not None:
        # Used as @cached without arguments
        return decorator(build_fn)
    return decorator
