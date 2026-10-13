"""Pytest path setup for studies/france_sovereign_stress."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os

# Tests assert on the frozen v5 inputs; a live snapshot in config.yaml must not leak in.
os.environ["FSS_SNAPSHOT"] = "reference"
