"""Paths and runtime configuration for CryoQuant.

Override in `config.local.py` (gitignored) if your layout differs.
"""

from __future__ import annotations

from pathlib import Path

# Workspace root (this file's grandparent).
ROOT: Path = Path(__file__).resolve().parents[1]

# Where Tier-2 feature parquets are cached.
FEATURE_STORE_DIR: Path = ROOT / "cryoquant" / "features" / "store"

# Where model artifacts (joblib) are persisted.
MODEL_ARTIFACTS_DIR: Path = ROOT / "cryoquant" / "models" / "artifacts"

# DuckDB file backing the data catalog and model registry.
CATALOG_DB: Path = ROOT / "cryoquant" / "data" / "catalog.duckdb"

# External data sources --------------------------------------------------------

# CryoBacktester's option + spot parquets. Read-only.
CRYOBACKTESTER_DATA_DIR: Path = Path(
    "/Users/ulrikdeichsel/CryoBacktester/backtester/data"
)

# Local Binance spot klines (we may also fetch fresh into here).
BINANCE_SPOT_DIR: Path = ROOT / "cryoquant" / "data" / "binance_spot"


# Optional local overrides
try:
    from cryoquant.config_local import *  # type: ignore  # noqa: F401, F403
except ImportError:
    pass
