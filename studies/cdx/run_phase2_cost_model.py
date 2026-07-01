#!/usr/bin/env python3
"""Phase 2 — validate CDS cost model and COVID.NA.IG replay."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.cds_cost_model import CdsEconomicsConfig, replay_constant_position
from src.ingest import cdx_to_macro_series, load_cdx_clean_csv
from src.paths import reports_dir

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def carry_table(cfg: CdsEconomicsConfig, notional: float = 100_000_000) -> pd.DataFrame:
    rows = []
    for bps in [50, 60, 70, 80]:
        annual = notional * (bps / 10_000)
        rows.append({
            "spread_bps": bps,
            "annual_carry_usd": annual,
            "pct_of_collateral": annual / cfg.collateral_usd * 100,
        })
    return pd.DataFrame(rows)


def main() -> None:
    log.info("Phase 2 — CDS cost model validation")
    cfg = CdsEconomicsConfig.from_yaml()
    df = load_cdx_clean_csv()
    spread = cdx_to_macro_series(df)

    covid = replay_constant_position(
        spread,
        entry_date="2020-02-24",
        exit_date="2020-03-23",
        notional_usd=100_000_000,
        config=cfg,
    )

    carry = carry_table(cfg)
    log.info("COVID replay nav_multiple=%.2f total_pnl=$%.1fM",
             covid["nav_multiple"], covid["total_pnl_usd"] / 1e6)
    log.info("\n%s", carry.to_string(index=False))

    report = {
        "covid_replay": {k: v for k, v in covid.items() if k not in ("pnl_daily", "nav")},
        "carry_table": carry.to_dict(orient="records"),
        "config": {
            "duration": cfg.duration,
            "collateral_usd": cfg.collateral_usd,
            "bid_ask_bps": cfg.bid_ask_bps,
            "financing_rate": cfg.financing_rate,
        },
    }
    out = reports_dir() / "phase2_cost_model.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("Wrote %s", out)


if __name__ == "__main__":
    main()
