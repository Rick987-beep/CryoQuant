#!/usr/bin/env python3
"""Generate self-contained CDX.NA.IG narrative study report (HTML)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.study_report_html import write_study_report

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    out = write_study_report()
    log.info("Wrote %s", out)


if __name__ == "__main__":
    main()
