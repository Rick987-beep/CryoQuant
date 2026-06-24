#!/usr/bin/env python3
"""Crunch Fund — 5y vintage sweeps toward 10× crisis payoff."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scoring_config import CRUNCH_FUND_SCORING
from src.backtest_cds import run_overlay
from src.bundle_export import (
    collection_from_records,
    export_leaderboard_bundle,
    overlay_record,
)
from src.cds_cost_model import CdsEconomicsConfig
from src.crunch_fund import (
    aggregate_config_results,
    build_crunch_position,
    fund_vintage_starts,
    iter_specs,
    load_crunch_config,
    run_fund_vintage,
)
from src.paths import bundles_dir, data_dir, reports_dir

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _econ_from_crunch(cf: dict) -> CdsEconomicsConfig:
    base = CdsEconomicsConfig.from_yaml()
    return CdsEconomicsConfig(
        duration=base.duration,
        day_count=base.day_count,
        bid_ask_bps=base.bid_ask_bps,
        roll_cost_bps=base.roll_cost_bps,
        financing_rate=base.financing_rate,
        collateral_usd=float(cf["collateral_usd"]),
    )


def main() -> None:
    log.info("Crunch Fund — vintage sweep (10× crisis target)")
    cfg = load_crunch_config()
    cf = cfg["crunch_fund"]
    econ = _econ_from_crunch(cf)

    features = pd.read_parquet(data_dir() / "features_daily.parquet")
    spread = features["spread_bps"]
    episodes = cfg.get("episodes", [])

    starts = fund_vintage_starts(
        spread.index,
        fund_years=int(cf["fund_years"]),
        freq=str(cf.get("vintage_freq", "QS")),
    )
    specs = iter_specs(cfg)
    log.info("%d vintages × %d configs = %d backtests", len(starts), len(specs), len(starts) * len(specs))

    vintage_rows: list[dict] = []
    episode_rows: list[dict] = []
    rep_overlay: dict[str, tuple] = {}

    for vi, t0 in enumerate(starts):
        t1 = t0 + pd.DateOffset(years=int(cf["fund_years"]))
        if vi % 8 == 0:
            log.info("Vintage %d/%d: %s", vi + 1, len(starts), t0.date())

        for spec in specs:
            result = run_fund_vintage(
                spread, features, spec, t0, t1,
                config=econ,
                episodes=episodes,
                nav_floor_pct=float(cf["nav_floor_pct"]),
                target_multiple=float(cf["target_nav_multiple"]),
            )
            vintage_rows.append({
                "run_id": spec.run_id,
                "strategy": spec.strategy,
                "notional_usd": spec.notional_usd,
                "entry_max_bps": spec.entry_max_bps,
                "exit_bps": spec.exit_bps,
                "addon_entry_bps": spec.addon_entry_bps,
                "addon_retreat_bps": spec.addon_retreat_bps,
                "addon_hold_days": spec.addon_hold_days,
                **result.metrics,
            })
            for ep in result.episodes:
                episode_rows.append({"run_id": spec.run_id, "vintage_start": result.metrics["vintage_start"], **ep})

            if spec.run_id not in rep_overlay and t0 <= pd.Timestamp("2019-07-01", tz="UTC"):
                slc = (spread.index >= t0) & (spread.index <= t1)
                sp, feat_slc = spread.loc[slc], features.loc[slc]
                roll = feat_slc["is_roll_window"] if "is_roll_window" in feat_slc.columns else None
                pos = build_crunch_position(sp, spec, is_roll=roll)
                cds = run_overlay(
                    sp, pos, name=spec.run_id, notional_usd=spec.notional_usd,
                    config=econ, is_roll_day=roll, collateral_usd=spec.collateral_usd,
                )
                rep_overlay[spec.run_id] = (spec, sp, cds)

    vintage_df = pd.DataFrame(vintage_rows)
    episode_df = pd.DataFrame(episode_rows)
    leaderboard = aggregate_config_results(vintage_df)

    vintage_df.to_csv(data_dir() / "crunch_fund_vintages.csv", index=False)
    episode_df.to_csv(data_dir() / "crunch_fund_episodes.csv", index=False)

    records = []
    for _, row in leaderboard.iterrows():
        run_id = row["run_id"]
        if run_id not in rep_overlay:
            continue
        spec, sp, cds = rep_overlay[run_id]
        records.append(overlay_record(
            run_id,
            {
                "strategy": spec.strategy,
                "notional_usd": spec.notional_usd,
                "entry_max_bps": spec.entry_max_bps,
                "exit_bps": spec.exit_bps,
                "addon_entry_bps": spec.addon_entry_bps,
                "addon_retreat_bps": spec.addon_retreat_bps,
                "addon_hold_days": spec.addon_hold_days,
            },
            cds, sp,
            extra_metrics={k: row[k] for k in row.index if k != "run_id"},
        ))

    collection = collection_from_records(records)
    bundle_path = export_leaderboard_bundle(
        bundles_dir() / "crunch_fund",
        leaderboard,
        collection,
        meta={
            "study": "cdx_crunch_fund",
            "mandate": "10x crisis peak NAV",
            "decisions_v1": {
                "nav_floor_pct": cf["nav_floor_pct"],
                "ten_x": "peak NAV in episode",
                "tier_c": "synthetic 200bp",
                "yield_overlay": False,
            },
            "n_vintages": len(starts),
            "n_configs": len(specs),
        },
        scoring=CRUNCH_FUND_SCORING,
        breakdown_cols=("strategy",),
    )

    best = leaderboard.iloc[0]
    summary = {
        "best_config": best.to_dict(),
        "any_hit_10x_historical": bool(episode_df.get("hit_10x", pd.Series(dtype=bool)).any()),
        "best_distance_to_10x_tier_bc": float(best["distance_to_10x_tier_bc"]),
        "best_crisis_peak_tier_bc": float(best["crisis_nav_peak_tier_bc"]),
    }
    summary_path = reports_dir() / "crunch_fund_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    log.info("Bundle: %s", bundle_path / "report.html")
    log.info("\n%s", leaderboard.head(8).to_string(index=False))


if __name__ == "__main__":
    main()
