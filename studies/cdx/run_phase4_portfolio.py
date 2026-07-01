#!/usr/bin/env python3
"""Phase 4 — portfolio backtest: tail + yield with mutex and walk-forward OOS."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scoring_config import CDX_PORTFOLIO_SCORING
from src.bundle_export import collection_from_records, export_sweep_bundle, portfolio_record
from src.cds_cost_model import CdsEconomicsConfig
from src.paths import bundles_dir, data_dir, load_config, reports_dir
from src.portfolio_backtest import PortfolioSpec, run_portfolio, run_walk_forward_oos

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _spec_from_variant(v: dict, cfg: dict) -> PortfolioSpec:
    tail = cfg.get("portfolio", {}).get("tail", cfg.get("yield_strategies", {}).get("tail_reference", {}))
    return PortfolioSpec(
        name=v["name"],
        tail_entry_max_bps=float(v.get("tail_entry_max_bps", tail.get("entry_max_bps", 60))),
        tail_exit_bps=float(v.get("tail_exit_bps", tail.get("exit_bps", 100))),
        yield_strategy=v["yield_strategy"],
        apply_mutex=bool(v.get("apply_mutex", True)),
        yield_scale=float(v.get("yield_scale", 1.0)),
    )


def main() -> None:
    log.info("Phase 4 — portfolio backtest")
    cfg = load_config()
    econ = CdsEconomicsConfig.from_yaml()
    pcfg = cfg.get("portfolio", {})

    features = pd.read_parquet(data_dir() / "features_daily.parquet")
    panel_path = data_dir() / "panel_daily.parquet"
    panel = pd.read_parquet(panel_path) if panel_path.exists() else None
    spread = features["spread_bps"]

    variants = pcfg.get("variants", [])
    if not variants:
        variants = [{
            "name": "tail_y8_mutex",
            "yield_strategy": "Y8_velocity_filter",
            "apply_mutex": True,
        }]

    full_sample = []
    records = []
    for v in variants:
        spec = _spec_from_variant(v, cfg)
        log.info("Running %s (yield=%s, mutex=%s)", spec.name, spec.yield_strategy, spec.apply_mutex)
        result = run_portfolio(spread, features, spec=spec, panel=panel, config=econ)
        params = {
            "name": spec.name,
            "yield_strategy": spec.yield_strategy,
            "apply_mutex": spec.apply_mutex,
            "tail_entry_max_bps": spec.tail_entry_max_bps,
            "tail_exit_bps": spec.tail_exit_bps,
            "yield_scale": spec.yield_scale,
        }
        records.append(portfolio_record(spec.name, params, result, spread))
        row = {
            "name": result.name,
            "nav_end": result.metrics["nav_end"],
            "cagr": result.metrics.get("cagr"),
            "max_drawdown": result.metrics["max_drawdown"],
            "carry_funding_ratio": result.metrics["carry_funding_ratio"],
            "calm_pnl_usd": result.metrics["calm_pnl_usd"],
            "stress_pnl_usd": result.metrics["stress_pnl_usd"],
            "pnl_covid": result.metrics.get("pnl_covid"),
            "mutex_overlap_days": result.metrics["mutex_overlap_days"],
            "pct_tail_in_market": result.metrics["pct_tail_in_market"],
            "pct_yield_in_market": result.metrics["pct_yield_in_market"],
            "tail_yield_corr_stress": result.metrics["tail_yield_corr_stress"],
            "apply_mutex": spec.apply_mutex,
            "yield_strategy": spec.yield_strategy,
        }
        full_sample.append(row)
        log.info(
            "  NAV end=%.3f funding=%.2f COVID=$%.0f overlap=%d",
            row["nav_end"],
            row["carry_funding_ratio"],
            row["pnl_covid"] or 0,
            row["mutex_overlap_days"],
        )

    df = pd.DataFrame(full_sample).sort_values("nav_end", ascending=False)
    out_csv = data_dir() / "phase4_portfolio_results.csv"
    df.to_csv(out_csv, index=False)

    # Walk-forward OOS on primary variant
    wf_cfg = pcfg.get("walk_forward", cfg.get("backtest", {}).get("walk_forward", {}))
    primary_name = wf_cfg.get("primary", variants[0]["name"])
    primary_v = next(v for v in variants if v["name"] == primary_name)
    spec = _spec_from_variant(primary_v, cfg)
    wf = run_walk_forward_oos(
        spread, features, spec=spec, panel=panel, config=econ,
        train_years=int(wf_cfg.get("train_years", 8)),
        test_years=int(wf_cfg.get("test_years", 3)),
    )
    log.info("Walk-forward OOS (%s): %d blocks, NAV end=%.3f",
             spec.name, wf["metrics"]["n_blocks"], wf["metrics"]["nav_end"])

    report = {
        "data_end": str(spread.index.max().date()),
        "full_sample": df.to_dict(orient="records"),
        "walk_forward": {
            "spec": spec.name,
            "metrics": wf["metrics"],
            "blocks": wf["blocks"],
        },
    }
    out_json = reports_dir() / "phase4_portfolio.json"
    out_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    collection = collection_from_records(records)
    bundle_path = export_sweep_bundle(
        bundles_dir() / "phase4_portfolio",
        collection,
        meta={
            "study": "cdx_phase4_portfolio",
            "data_end": str(spread.index.max().date()),
            "walk_forward": report["walk_forward"],
        },
        scoring=CDX_PORTFOLIO_SCORING,
        breakdown_cols=("yield_strategy", "apply_mutex"),
    )
    log.info("Wrote %s, %s, bundle %s", out_csv, out_json, bundle_path / "report.html")
    log.info("\n%s", df.to_string(index=False))


if __name__ == "__main__":
    main()
