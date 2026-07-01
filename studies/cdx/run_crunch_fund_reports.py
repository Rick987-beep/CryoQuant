#!/usr/bin/env python3
"""Generate Crunch Fund HTML reports (research + investor pitch)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.crunch_fund_pitch_html import write_crunch_fund_pitch
from src.crunch_fund_report_html import write_crunch_fund_report

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    study = write_crunch_fund_report()
    pitch = write_crunch_fund_pitch()
    log.info("Research report: %s", study)
    log.info("Investor pitch:   %s", pitch)


if __name__ == "__main__":
    main()
