"""Paths and runtime configuration for CryoQuant.

Override in `config_local.py` (gitignored) if your layout differs.
"""

from __future__ import annotations

import os
from pathlib import Path

# Workspace root (this file's grandparent).
ROOT: Path = Path(__file__).resolve().parents[1]

# Where raw market data parquets are stored (partitioned by source/venue_ticker/tf/year=YYYY/).
STORE_ROOT: Path = Path(os.environ.get("CRYOQUANT_STORE_ROOT", str(ROOT / "data")))

# Where Tier-2 feature parquets are cached.
FEATURE_STORE_DIR: Path = ROOT / "cryoquant" / "features" / "store"

# Where model artifacts (joblib) are persisted.
MODEL_ARTIFACTS_DIR: Path = ROOT / "cryoquant" / "models" / "artifacts"

# DuckDB file backing the data catalog and model registry.
CATALOG_DB: Path = Path(os.environ.get("CRYOQUANT_CATALOG_DB", str(STORE_ROOT / "catalog.duckdb")))

# External data sources --------------------------------------------------------

# CryoBacktester's option + spot parquets. Read-only.
CRYOBACKTESTER_DATA_DIR: Path = Path(
    os.environ.get(
        "CRYOBACKTESTER_DATA_DIR",
        "/Users/ulrikdeichsel/CryoBacktester/backtester/data",
    )
)

# Binance public REST base.
BINANCE_REST_BASE: str = "https://api.binance.com"

# FRED API key (optional — falls back to public CSV endpoint if absent).
FRED_API_KEY: str | None = os.environ.get("FRED_API_KEY")


# Optional local overrides (gitignored)
try:
    from cryoquant.config_local import *  # type: ignore  # noqa: F401, F403
except ImportError:
    pass
