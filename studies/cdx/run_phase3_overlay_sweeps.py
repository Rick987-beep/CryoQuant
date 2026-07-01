#!/usr/bin/env python3
"""Phase 3 — per-overlay backtests with CDS cost model (tail + yield v2)."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scoring_config import CDX_OVERLAY_SCORING
from src.backtest_cds import run_overlay
from src.bundle_export import collection_from_records, export_sweep_bundle, overlay_record
from src.cds_cost_model import CdsEconomicsConfig
from src.paths import bundles_dir, data_dir, load_config, reports_dir
from src.signals_tail import standing_tail_insurance, tail_hold_on_spike
from src.signals_yield import YIELD_STRATEGY_REGISTRY, run_yield_strategy

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _calm_mask(spread: pd.Series, threshold: float = 80.0) -> pd.Series:
    return spread < threshold


def _episode_pnl(result, start: str, end: str) -> float:
    slc = result.daily_attribution["total"].loc[start:end]
    return float(slc.sum()) if len(slc) else 0.0


def _extra_metrics(
    result,
    spread: pd.Series,
    *,
    calm_threshold: float,
    tail_calm_carry_usd: float,
    y1_nav_end: float | None = None,
) -> dict:
    calm = _calm_mask(spread, calm_threshold)
    calm_pnl = float(result.daily_attribution.loc[calm, "total"].sum())
    funding = calm_pnl / abs(tail_calm_carry_usd) if tail_calm_carry_usd != 0 else float("nan")
    metrics = {
        "calm_pnl_usd": calm_pnl,
        "carry_funding_ratio": funding,
        "covid_pnl_usd": _episode_pnl(result, "2020-02-01", "2020-04-30"),
    }
    if y1_nav_end is not None:
        metrics["vs_y1_nav"] = result.metrics["nav_end"] / y1_nav_end
    return metrics


def _result_row(
    overlay: str,
    name: str,
    result,
    spread: pd.Series,
    *,
    calm_threshold: float,
    tail_calm_carry_usd: float,
    y1_nav_end: float | None = None,
) -> dict:
    extra = _extra_metrics(
        result, spread,
        calm_threshold=calm_threshold,
        tail_calm_carry_usd=tail_calm_carry_usd,
        y1_nav_end=y1_nav_end,
    )
    row = {
        "overlay": overlay,
        "name": name,
        "nav_end": result.metrics["nav_end"],
        "cagr": result.metrics["cagr"],
        "max_drawdown": result.metrics["max_drawdown"],
        "n_trades": result.metrics["n_trades"],
        "carry_usd": result.metrics["carry_usd"],
        "pct_in_market": result.metrics["pct_in_market"],
        **extra,
    }
    return row


def main() -> None:
    log.info("Phase 3 — overlay sweeps (CDX.NA.IG through 2026-03-15)")
    cfg = load_config()
    econ = CdsEconomicsConfig.from_yaml()
    ycfg = cfg.get("yield_strategies", {})
    calm_threshold = float(ycfg.get("stress_bps", 80))

    features = pd.read_parquet(data_dir() / "features_daily.parquet")
    panel_path = data_dir() / "panel_daily.parquet"
    panel = pd.read_parquet(panel_path) if panel_path.exists() else None
    spread = features["spread_bps"]
    roll = features["is_roll_window"]

    tail_notional = float(cfg["overlays"]["tail"]["notional_usd"])
    yield_notional = float(cfg["overlays"]["yield"]["notional_usd"])
    tail_collateral = econ.collateral_usd * float(cfg["overlays"]["tail"]["collateral_slice_pct"])
    yield_collateral = econ.collateral_usd * float(cfg["overlays"]["yield"]["collateral_slice_pct"])

    tail_ref = ycfg.get("tail_reference", {})
    tail_pos = standing_tail_insurance(
        spread,
        entry_max_bps=float(tail_ref.get("entry_max_bps", 60)),
        exit_bps=float(tail_ref.get("exit_bps", 100)),
        skip_roll=roll,
    )
    tail_ref_result = run_overlay(
        spread, tail_pos, name="tail_ref_carry", notional_usd=tail_notional,
        config=econ, is_roll_day=roll, collateral_usd=tail_collateral,
    )
    calm = _calm_mask(spread, calm_threshold)
    tail_calm_carry = float(tail_ref_result.daily_attribution.loc[calm, "carry"].sum())

    results: list[dict] = []
    records = []

    # --- Overlay 1: standing tail grid ---
    for entry_max in [60, 65, 70]:
        for exit_bps in [100, 120]:
            name = f"tail_stand_e{entry_max}_x{exit_bps}"
            pos = standing_tail_insurance(
                spread, entry_max_bps=entry_max, exit_bps=exit_bps, skip_roll=roll,
            )
            r = run_overlay(
                spread, pos, name=name, notional_usd=tail_notional,
                config=econ, is_roll_day=roll, collateral_usd=tail_collateral,
            )
            extra = _extra_metrics(
                r, spread, calm_threshold=calm_threshold, tail_calm_carry_usd=tail_calm_carry,
            )
            params = {"overlay": "tail", "name": name, "entry_max_bps": entry_max, "exit_bps": exit_bps}
            records.append(overlay_record(name, params, r, spread, extra_metrics=extra))
            results.append(_result_row(
                "tail", name, r, spread,
                calm_threshold=calm_threshold, tail_calm_carry_usd=tail_calm_carry,
            ))

    pos_hold = tail_hold_on_spike(spread)
    r_hold = run_overlay(
        spread, pos_hold, name="tail_hold_spike", notional_usd=tail_notional,
        config=econ, is_roll_day=roll, collateral_usd=tail_collateral,
    )
    extra_hold = _extra_metrics(
        r_hold, spread, calm_threshold=calm_threshold, tail_calm_carry_usd=tail_calm_carry,
    )
    records.append(overlay_record(
        "tail_hold_spike",
        {"overlay": "tail", "name": "tail_hold_spike"},
        r_hold, spread, extra_metrics=extra_hold,
    ))
    results.append(_result_row(
        "tail", "tail_hold_spike", r_hold, spread,
        calm_threshold=calm_threshold, tail_calm_carry_usd=tail_calm_carry,
    ))

    # --- Overlay 2: yield v2 (all registered strategies) ---
    y1_name = ycfg.get("benchmark", "Y1_calm_underwriter")
    y1_pos = run_yield_strategy(
        y1_name, spread, features=features, panel=panel,
    )
    y1_result = run_overlay(
        spread, y1_pos, name=y1_name, notional_usd=yield_notional,
        config=econ, is_roll_day=roll, collateral_usd=yield_collateral,
    )
    y1_nav = y1_result.metrics["nav_end"]
    log.info("Y1 benchmark NAV end: %.3f", y1_nav)

    for name in sorted(YIELD_STRATEGY_REGISTRY.keys()):
        tail_for_strategy = tail_pos if name == "Y14_handoff" else None
        pos = run_yield_strategy(
            name, spread, features=features, panel=panel, tail_position=tail_for_strategy,
        )
        r = run_overlay(
            spread, pos, name=name, notional_usd=yield_notional,
            config=econ, is_roll_day=roll, collateral_usd=yield_collateral,
        )
        extra = _extra_metrics(
            r, spread,
            calm_threshold=calm_threshold,
            tail_calm_carry_usd=tail_calm_carry,
            y1_nav_end=y1_nav,
        )
        params = {"overlay": "yield", "name": name, "yield_strategy": name}
        records.append(overlay_record(name, params, r, spread, extra_metrics=extra))
        results.append(_result_row(
            "yield", name, r, spread,
            calm_threshold=calm_threshold,
            tail_calm_carry_usd=tail_calm_carry,
            y1_nav_end=y1_nav,
        ))

    df = pd.DataFrame(results)
    yield_df = df[df["overlay"] == "yield"].sort_values("nav_end", ascending=False)
    tail_df = df[df["overlay"] == "tail"].sort_values("nav_end", ascending=False)
    df = pd.concat([tail_df, yield_df], ignore_index=True)

    out_csv = data_dir() / "phase3_overlay_results.csv"
    df.to_csv(out_csv, index=False)
    log.info("\n--- Yield leaderboard ---\n%s", yield_df.to_string(index=False))

    report = {
        "data_end": str(spread.index.max().date()),
        "data_note": "Manual CDX.NA.IG CSV; no live feed",
        "y1_benchmark_nav_end": y1_nav,
        "tail_calm_carry_usd": tail_calm_carry,
        "leaderboard": df.to_dict(orient="records"),
        "yield_leaderboard": yield_df.to_dict(orient="records"),
    }
    out_json = reports_dir() / "phase3_overlay_sweeps.json"
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    collection = collection_from_records(records)
    bundle_path = export_sweep_bundle(
        bundles_dir() / "phase3_overlay_sweep",
        collection,
        meta={
            "study": "cdx_phase3_overlay_sweep",
            "data_end": str(spread.index.max().date()),
            "y1_benchmark_nav_end": y1_nav,
        },
        scoring=CDX_OVERLAY_SCORING,
        breakdown_cols=("overlay",),
    )
    log.info("Wrote %s, %s, bundle %s", out_csv, out_json, bundle_path / "report.html")


if __name__ == "__main__":
    main()
