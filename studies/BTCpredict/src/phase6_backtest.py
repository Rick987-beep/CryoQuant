"""Phase 6 backtest orchestration."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cryoquant import config as cq_config
from cryoquant.backtest.bundle import RunBundle, write_bundle
from cryoquant.backtest.short_vol import ShortVolConfig, evaluate_short_vol
from cryoquant.data.sources import deribit_options
from cryoquant.signals.base import BoolSignal

from src.backtest_register import load_backtest_register
from cryoquant.backtest.option_lookup import _spot_price_on_date
from src.option_policy import compose_short_vol_signal
from src.phase6_proxy import (
    attach_deflated_sharpe,
    compare_to_naive,
    proxy_to_dict,
    run_naive_vrp_baseline,
    run_vrp_proxy,
)
from src.repro_bundle import build_repro_bundle
from src.signal_compose import build_horizon_signals
from src.trial_log import append_trial, count_trials, trial_log_path

log = logging.getLogger(__name__)


@dataclass
class Phase6Report:
    written_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    session_id: str = ""
    reproducibility: dict[str, Any] = field(default_factory=dict)
    proxy_sweep: list[dict[str, Any]] = field(default_factory=list)
    naive_baselines: list[dict[str, Any]] = field(default_factory=list)
    best_config: dict[str, Any] = field(default_factory=dict)
    chain_smoke: dict[str, Any] = field(default_factory=dict)
    spot_sanity: dict[str, Any] = field(default_factory=dict)
    trial_log_count: int = 0


def _sweep_grid(register: dict[str, Any]) -> list[dict[str, Any]]:
    axes = register.get("sweep", {}).get("axes", {})
    combos: list[dict[str, Any]] = []
    for h in axes.get("horizon_id", ["T+1d", "T+5d"]):
        for vt in axes.get("vrp_threshold", [0.0]):
            for tm in axes.get("tilt_mode", ["symmetric"]):
                for me in axes.get("min_physical_edge", [0.0]):
                    combos.append(
                        {
                            "horizon_id": h,
                            "vrp_threshold": float(vt),
                            "tilt_mode": tm,
                            "min_physical_edge": float(me),
                        }
                    )
    return combos


def _fire_signal_from_policy(policy: pd.DataFrame, symbol: str = "binance.spot:BTCUSDT") -> BoolSignal:
    fire_idx = policy.index[policy["fire"].astype(bool)]

    def _cond(df: pd.DataFrame) -> pd.Series:
        s = pd.Series(False, index=df.index)
        s.loc[s.index.intersection(fire_idx)] = True
        return s

    return BoolSignal("phase6_fire", _cond, symbol_str=symbol)


def run_proxy_sweep(
    cfg: Any,
    register: dict[str, Any],
    *,
    n_trials_base: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    asset = register.get("assets", {}).get("promotion", "BTC")
    spread_bps = float(register.get("dev_proxy", {}).get("spread_bps", 10))

    results: list[dict[str, Any]] = []
    baselines: dict[str, dict[str, Any]] = {}
    n_trials = n_trials_base + len(_sweep_grid(register))

    for combo in _sweep_grid(register):
        h = combo["horizon_id"]
        sig = build_horizon_signals(cfg, register, asset=asset, horizon_id=h)
        if h not in baselines:
            naive = run_naive_vrp_baseline(sig, cfg, asset=asset, horizon_id=h, spread_bps=spread_bps)
            naive = attach_deflated_sharpe(naive, n_trials=n_trials)
            baselines[h] = proxy_to_dict(naive)

        policy = compose_short_vol_signal(
            sig,
            cfg.option_book,
            vrp_threshold=combo["vrp_threshold"],
            min_physical_edge=combo["min_physical_edge"],
            tilt_mode=combo["tilt_mode"],
        )
        run_id = (
            f"proxy_{asset.lower()}_{h.replace('+', '')}_"
            f"vt{combo['vrp_threshold']}_tm{combo['tilt_mode']}_me{combo['min_physical_edge']}"
        )
        res = run_vrp_proxy(
            policy, cfg, asset=asset, horizon_id=h, spread_bps=spread_bps, run_id=run_id
        )
        res = attach_deflated_sharpe(res, n_trials=n_trials)
        naive = run_naive_vrp_baseline(sig, cfg, asset=asset, horizon_id=h, spread_bps=spread_bps)
        naive = attach_deflated_sharpe(naive, n_trials=n_trials)
        res.beats_naive = compare_to_naive(res, naive)
        results.append(proxy_to_dict(res))

    if not results:
        return results, list(baselines.values()), {}

    metric = register.get("sweep", {}).get("selection_metric", "deflated_sharpe")
    best = max(
        results,
        key=lambda r: r.get(metric) if np.isfinite(r.get(metric, float("nan"))) else -1e9,
    )
    best_config = {
        "asset": asset,
        "horizon_id": best["horizon_id"],
        "vrp_threshold": best["vrp_threshold"],
        "tilt_mode": best["tilt_mode"],
        "min_physical_edge": best["min_physical_edge"],
        "selection_metric": metric,
        "deflated_sharpe": best.get("deflated_sharpe"),
        "expectancy": best.get("expectancy"),
        "cvar": best.get("cvar"),
        "beats_naive": best.get("beats_naive"),
    }
    return results, list(baselines.values()), best_config


def run_chain_smoke(cfg: Any, register: dict[str, Any], best: dict[str, Any]) -> dict[str, Any]:
    max_dates = int(register.get("chain", {}).get("smoke_max_dates", 5))
    all_dates = deribit_options.list_dates()
    dates: list = []
    for d in reversed(all_dates):
        try:
            c = deribit_options.load_chain(d)
            if "expiry" in c.columns and len(c) > 1000:
                dates.append(d)
        except Exception:
            continue
        if len(dates) >= max_dates:
            break
    if not dates:
        return {"status": "skipped", "reason": "no_chain_dates", "fires_with_data": 0}

    smoke_dates = dates
    chains_dir = cq_config.CRYOBACKTESTER_DATA_DIR
    asset = best.get("asset", "BTC")
    h = best.get("horizon_id", "T+1d")
    horizon = next(x for x in cfg.horizons if x.id.value == h)
    dte = max(horizon.dte_targets)

    closes: list[float] = []
    index: list[pd.Timestamp] = []
    for d in smoke_dates:
        spot = _spot_price_on_date(chains_dir, d)
        if spot is None:
            try:
                ch = deribit_options.load_chain(d)
                if "underlying_price" in ch.columns:
                    spot = float(ch["underlying_price"].dropna().iloc[0])
            except Exception:
                spot = None
        if spot is not None and spot > 0:
            index.append(pd.Timestamp(d, tz="UTC"))
            closes.append(float(spot))
    if not index:
        return {"status": "skipped", "reason": "no_spot_on_smoke_dates", "fires_with_data": 0}

    bars = pd.DataFrame({"close": closes}, index=pd.DatetimeIndex(index))

    # Infra smoke: fire every bar in window (policy OOS is dev-only; chains are hold-out).
    signal = BoolSignal("phase6_smoke", lambda df: pd.Series(True, index=df.index), symbol_str="binance.spot:BTCUSDT")

    svcfg = ShortVolConfig(
        structure="strangle",
        target_delta=cfg.option_book.target_deltas[1],
        wing_delta_offset=cfg.option_book.wing_delta_offsets[0],
        dte=dte,
        tilt="symmetric",
    )
    result = evaluate_short_vol(signal, bars, cfg=svcfg, chains_dir=chains_dir)
    return {
        "status": "ok",
        "chains_dir": str(chains_dir),
        "smoke_dates": [d.isoformat() for d in smoke_dates],
        "fires_evaluated": result.fires_evaluated,
        "fires_with_data": result.fires_with_data,
        "expectancy": result.expectancy,
        "win_rate": result.win_rate,
        "note": "always-fire infra smoke on hold-out chain window",
    }


def run_spot_sanity(cfg: Any) -> dict[str, Any]:
    return {"status": "informational", "note": "directional null on dev — Goal 1 spot simulate deferred"}


def run_phase6_backtest(cfg: Any, *, smoke: bool = False, data_dir: Path) -> Phase6Report:
    register = load_backtest_register()
    if smoke:
        register = {
            **register,
            "sweep": {
                **register.get("sweep", {}),
                "axes": {
                    "horizon_id": ["T+1d"],
                    "vrp_threshold": [0.0],
                    "tilt_mode": ["symmetric"],
                    "min_physical_edge": [0.0],
                },
            },
        }

    tlog = trial_log_path(data_dir)
    report = Phase6Report(
        session_id=datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        reproducibility=build_repro_bundle(cfg),
        trial_log_count=count_trials(tlog),
    )

    proxy, naive, best = run_proxy_sweep(cfg, register, n_trials_base=report.trial_log_count)
    report.proxy_sweep = proxy
    report.naive_baselines = naive
    report.best_config = best
    report.spot_sanity = run_spot_sanity(cfg)
    report.chain_smoke = run_chain_smoke(cfg, register, best) if best else {
        "status": "skipped",
        "reason": "no_best_config",
        "fires_with_data": 0,
    }

    for row in proxy:
        append_trial(
            tlog,
            {
                "phase": "phase6",
                "run_id": row["run_id"],
                "params": {
                    "horizon_id": row["horizon_id"],
                    "vrp_threshold": row["vrp_threshold"],
                    "tilt_mode": row["tilt_mode"],
                    "min_physical_edge": row["min_physical_edge"],
                },
                "metric": {
                    "sharpe": row.get("sharpe"),
                    "deflated_sharpe": row.get("deflated_sharpe"),
                    "cvar": row.get("cvar"),
                    "expectancy": row.get("expectancy"),
                    "n_trades": row.get("n_trades"),
                },
            },
        )

    return report


def write_phase6_artifacts(report: Phase6Report, data_dir: Path, reports_dir: Path) -> None:
    payload = asdict(report)
    (data_dir / "phase6_backtest_report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    (data_dir / "phase6_best_config.json").write_text(
        json.dumps(report.best_config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if report.proxy_sweep:
        lb = pd.DataFrame(report.proxy_sweep)
        bundle = RunBundle(
            meta={
                "study": "btcpredict_v1",
                "phase": "phase6",
                "n_runs": len(lb),
                "scoring": "deflated_sharpe",
            },
            leaderboard=lb,
        )
        write_bundle(reports_dir / "bundles" / "primary", bundle)

    from src.phase6_report import write_report_text

    write_report_text(payload, reports_dir / "phase6_backtest_report.txt")
