#!/usr/bin/env python3
"""Phase 5 — manifest, index HTML, and primary portfolio bundle."""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.cds_cost_model import CdsEconomicsConfig
from src.paths import bundles_dir, data_dir, load_config, reports_dir
from src.portfolio_backtest import PortfolioSpec, run_portfolio, run_walk_forward_oos
from src.primary_bundle import export_primary_bundle
from src.report_manifest import build_manifest, render_index_html, write_manifest
from src.study_report_html import write_study_report

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


def _run_script(name: str) -> None:
    script = ROOT / name
    log.info("Running %s …", name)
    subprocess.run([sys.executable, str(script)], check=True, cwd=str(ROOT))


def _load_walk_forward(cfg: dict) -> dict | None:
    path = reports_dir() / "phase4_portfolio.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("walk_forward")
    return None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="CDX Phase 5 report orchestrator")
    parser.add_argument(
        "--refresh-bundles",
        action="store_true",
        help="Re-run phase 3 and 4 before building manifest (slow)",
    )
    args = parser.parse_args(argv)

    log.info("Phase 5 — report manifest + primary bundle")
    cfg = load_config()
    econ = CdsEconomicsConfig.from_yaml()
    pcfg = cfg.get("portfolio", {})
    wf_cfg = pcfg.get("walk_forward", cfg.get("backtest", {}).get("walk_forward", {}))
    primary_name = wf_cfg.get("primary", "tail_y8_mutex")

    phase3_dir = bundles_dir() / "phase3_overlay_sweep"
    phase4_dir = bundles_dir() / "phase4_portfolio"
    primary_dir = bundles_dir() / "primary"

    if args.refresh_bundles:
        _run_script("run_phase3_overlay_sweeps.py")
        _run_script("run_phase4_portfolio.py")
    elif not (phase3_dir / "meta.json").exists() or not (phase4_dir / "meta.json").exists():
        log.warning(
            "Phase 3/4 bundles missing — index will link only what exists. "
            "Run with --refresh-bundles or execute phase 3/4 scripts first."
        )

    features = pd.read_parquet(data_dir() / "features_daily.parquet")
    panel_path = data_dir() / "panel_daily.parquet"
    panel = pd.read_parquet(panel_path) if panel_path.exists() else None
    spread = features["spread_bps"]
    data_start = str(spread.index.min().date())
    data_end = str(spread.index.max().date())
    n_bars = len(spread)

    variants = pcfg.get("variants", [])
    primary_v = next((v for v in variants if v["name"] == primary_name), None)
    if primary_v is None:
        primary_v = {"name": primary_name, "yield_strategy": "Y8_velocity_filter", "apply_mutex": True}
    spec = _spec_from_variant(primary_v, cfg)

    log.info("Exporting primary portfolio: %s", spec.name)
    result = run_portfolio(spread, features, spec=spec, panel=panel, config=econ)
    wf = run_walk_forward_oos(
        spread, features, spec=spec, panel=panel, config=econ,
        train_years=int(wf_cfg.get("train_years", 8)),
        test_years=int(wf_cfg.get("test_years", 3)),
    )
    walk_forward = {
        "spec": spec.name,
        "metrics": wf["metrics"],
        "blocks": wf["blocks"],
    }

    export_primary_bundle(
        result,
        spread,
        primary_dir,
        meta_extra={
            "data_start": data_start,
            "data_end": data_end,
            "n_bars": n_bars,
            "walk_forward": walk_forward,
        },
    )
    log.info("Primary bundle: %s", primary_dir / "report.html")

    manifest = build_manifest(
        data_start=data_start,
        data_end=data_end,
        n_bars=n_bars,
        primary_name=spec.name,
        phase3_dir=phase3_dir,
        phase4_dir=phase4_dir,
        primary_dir=primary_dir,
        walk_forward=walk_forward or _load_walk_forward(cfg),
    )
    manifest_path = write_manifest(reports_dir() / "manifest.json", manifest)
    index_path = render_index_html(reports_dir() / "report.html", manifest)
    study_path = write_study_report()

    log.info("Manifest: %s", manifest_path)
    log.info("Index:    %s", index_path)
    log.info("Study:    %s", study_path)
    log.info(
        "Primary NAV end=%.3f funding=%.2f COVID=$%.0f",
        result.metrics["nav_end"],
        result.metrics["carry_funding_ratio"],
        result.metrics.get("pnl_covid") or 0,
    )


if __name__ == "__main__":
    main()
