"""Phase 7B — hold-out chain backtest (report-all) and calibration."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from cryoquant import config as cq_config
from cryoquant.backtest.robustness import deflated_sharpe
from cryoquant.backtest.short_vol import ShortVolConfig, ShortVolResult, evaluate_short_vol
from cryoquant.backtest.short_vol_metrics import (
    calibration_gap,
    cvar_loss,
    otm_rate_vs_delta,
    trade_sharpe,
)
from cryoquant.data.sources import deribit_options
from cryoquant.models.validation import calibration_summary
from cryoquant.signals.base import BoolSignal

from src.backtest_register import load_backtest_register
from src.config_models import StudyConfig
from src.holdout_register import load_holdout_register
from src.option_policy import compose_short_vol_signal
from src.phase5_calibration import exceedance_calibration_overlay
from src.signal_compose import build_horizon_signals_holdout
from src.trial_log import count_trials, trial_log_path

log = logging.getLogger(__name__)


@dataclass
class Phase7Report:
    written_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    session_id: str = ""
    frozen_signal: dict[str, Any] = field(default_factory=dict)
    inference_summary: dict[str, Any] = field(default_factory=dict)
    calibration_slice: dict[str, Any] = field(default_factory=dict)
    chain_window: dict[str, Any] = field(default_factory=dict)
    preregistered_primary: dict[str, Any] = field(default_factory=dict)
    model_gated: dict[str, Any] = field(default_factory=dict)
    naive_seller: dict[str, Any] = field(default_factory=dict)
    naive_vrp_gate: dict[str, Any] = field(default_factory=dict)
    report_all_grid: list[dict[str, Any]] = field(default_factory=list)
    physical_vs_delta: dict[str, Any] = field(default_factory=dict)
    gates: dict[str, Any] = field(default_factory=dict)
    trial_log_count: int = 0


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _effective_start(register: dict[str, Any], cfg: StudyConfig) -> pd.Timestamp:
    chain_start = register.get("chain_eval", {}).get("effective_start", "2025-04-11")
    holdout = pd.Timestamp(cfg.splits.holdout_start, tz="UTC")
    eff = pd.Timestamp(_parse_date(chain_start), tz="UTC")
    return max(holdout, eff)


def _valid_chain_dates(effective_start: date) -> list[date]:
    out: list[date] = []
    for d in deribit_options.list_dates():
        if d < effective_start:
            continue
        try:
            c = deribit_options.load_chain(d)
            if {"expiry", "is_call", "bid_price", "ask_price"}.issubset(c.columns) and len(c) > 500:
                out.append(d)
        except Exception:
            continue
    return sorted(out)


def build_chain_bars(dates: list[date], chains_dir: Path) -> pd.DataFrame:
    from cryoquant.backtest.option_lookup import _spot_price_on_date

    index: list[pd.Timestamp] = []
    closes: list[float] = []
    for d in dates:
        spot = _spot_price_on_date(chains_dir, d)
        if spot is None:
            try:
                ch = deribit_options.load_chain(d)
                if "underlying_price" in ch.columns:
                    up = ch["underlying_price"].dropna()
                    if len(up):
                        spot = float(up.iloc[0])
            except Exception:
                spot = None
        if spot is not None and spot > 0:
            index.append(pd.Timestamp(d, tz="UTC"))
            closes.append(float(spot))
    return pd.DataFrame({"close": closes}, index=pd.DatetimeIndex(index))


def _bool_signal_from_mask(name: str, mask: pd.Series, bars: pd.DataFrame) -> BoolSignal:
    fire_idx = mask[mask.astype(bool)].index

    def _cond(df: pd.DataFrame) -> pd.Series:
        s = pd.Series(False, index=df.index)
        s.loc[s.index.intersection(fire_idx)] = True
        return s

    return BoolSignal(name, _cond, symbol_str="binance.spot:BTCUSDT")


def _always_fire_signal(name: str) -> BoolSignal:
    return BoolSignal(name, lambda df: pd.Series(True, index=df.index), symbol_str="binance.spot:BTCUSDT")


def _short_vol_config(
    *,
    target_delta: float,
    dte: int,
    structure: Literal["strangle", "credit_spread"],
    tilt: str = "symmetric",
    wing_offset: float = 0.05,
) -> ShortVolConfig:
    return ShortVolConfig(
        structure=structure,
        target_delta=target_delta,
        wing_delta_offset=wing_offset,
        dte=dte,
        tilt=tilt,  # type: ignore[arg-type]
    )


def _metrics_from_result(
    result: ShortVolResult,
    *,
    label: str,
    params: dict[str, Any],
    target_delta: float,
    n_trials: int,
) -> dict[str, Any]:
    pnl = np.asarray(result.pnl_pct, dtype=float)
    n = int(np.sum(np.isfinite(pnl)))
    sharpe = trade_sharpe(pnl.tolist())
    skew = float(pd.Series(pnl).skew()) if n > 2 else 0.0
    kurt = float(pd.Series(pnl).kurtosis()) if n > 3 else 3.0
    dsr = deflated_sharpe(sharpe, n_trials=max(1, n_trials), n_obs=max(2, n), skew=skew, kurt=kurt)
    implied_otm = 1.0 - target_delta
    otm = otm_rate_vs_delta(
        np.asarray(result.realized_otm, dtype=float),
        np.full(len(result.realized_otm), implied_otm),
    )
    gap = calibration_gap(otm.get("realized_otm_rate", float("nan")), target_delta)
    return {
        "label": label,
        **params,
        "fires_evaluated": result.fires_evaluated,
        "fires_with_data": result.fires_with_data,
        "n_trades": n,
        "expectancy": result.expectancy,
        "win_rate": result.win_rate,
        "sharpe": sharpe,
        "deflated_sharpe": dsr,
        "cvar": cvar_loss(pnl.tolist()),
        "target_delta": target_delta,
        "realized_otm_rate": otm.get("realized_otm_rate"),
        "predicted_otm_rate": otm.get("predicted_otm_rate"),
        "calibration_gap": gap,
        "otm_n": otm.get("n", 0),
    }


def _sweep_grid(register: dict[str, Any]) -> list[dict[str, Any]]:
    axes = register.get("sweep", {}).get("axes", {})
    combos: list[dict[str, Any]] = []
    for delta in axes.get("target_delta", [0.15]):
        for dte in axes.get("dte", [7]):
            for structure in axes.get("structure", ["strangle"]):
                for exit_rule in axes.get("exit_rule", ["hold_to_expiry"]):
                    combos.append(
                        {
                            "target_delta": float(delta),
                            "dte": int(dte),
                            "structure": structure,
                            "exit_rule": exit_rule,
                        }
                    )
    return combos


def _run_calibration_slice(
    cfg: StudyConfig,
    holdout_preds: pd.DataFrame,
    register: dict[str, Any],
    *,
    effective_start: pd.Timestamp,
) -> dict[str, Any]:
    holdout = pd.Timestamp(cfg.splits.holdout_start, tz="UTC")
    slice_preds = holdout_preds[
        (holdout_preds["timestamp"] >= holdout) & (holdout_preds["timestamp"] < effective_start)
    ]
    val_reg = {
        "exceedance_calibration": {
            "assets": ["BTC"],
            "deltas": [0.15],
            "sides": ["call", "put"],
        }
    }
    overlays = exceedance_calibration_overlay(
        cfg,
        slice_preds,
        val_reg,
        dev_only_labels=False,
        close_through_holdout=False,
    )
    btc_h1 = [o for o in overlays if o.get("asset") == "BTC" and o.get("horizon_id") == "T+1d"]
    ece_vals = [o.get("ece") for o in btc_h1 if o.get("ece") is not None]
    return {
        "slice_start": holdout.isoformat(),
        "slice_end": effective_start.isoformat(),
        "prediction_rows": len(slice_preds),
        "exceedance_overlays": overlays,
        "btc_h1_ece_min": float(min(ece_vals)) if ece_vals else float("nan"),
    }


def _evaluate_gates(report: Phase7Report, cfg: StudyConfig, register: dict[str, Any]) -> dict[str, Any]:
    max_cvar = -float(cfg.risk.max_cvar_loss_pct)
    primary = report.model_gated or report.preregistered_primary
    g2_gap = primary.get("calibration_gap")
    g2_ece = report.calibration_slice.get("btc_h1_ece_min")
    g2_chain_n = primary.get("n_trades", 0) or 0
    g2_pass = (
        (g2_chain_n > 0 and g2_gap is not None and np.isfinite(g2_gap) and float(g2_gap) > 0)
        or (g2_ece is not None and np.isfinite(g2_ece) and float(g2_ece) < 0.05)
    )
    g1_pass = bool(
        primary.get("deflated_sharpe") is not None
        and report.naive_seller.get("deflated_sharpe") is not None
        and np.isfinite(primary["deflated_sharpe"])
        and np.isfinite(report.naive_seller["deflated_sharpe"])
        and float(primary["deflated_sharpe"]) > float(report.naive_seller["deflated_sharpe"])
    )
    cvar = primary.get("cvar")
    g3_pass = bool(cvar is not None and np.isfinite(cvar) and float(cvar) >= max_cvar)
    exp = primary.get("expectancy")
    g4_pass = bool(exp is not None and np.isfinite(exp) and float(exp) > 0)
    return {
        "G2_primary": {
            "pass": g2_pass,
            "calibration_gap": g2_gap,
            "ece_min": g2_ece,
            "passed_via": "chain_gap" if (g2_chain_n > 0 and g2_gap is not None and float(g2_gap) > 0) else (
                "calibration_slice_ece" if g2_pass else "none"
            ),
            "chain_trades": g2_chain_n,
        },
        "G1_secondary": {"pass": g1_pass, "model_dsr": primary.get("deflated_sharpe"), "naive_dsr": report.naive_seller.get("deflated_sharpe")},
        "G3_secondary": {"pass": g3_pass, "cvar": cvar, "cap": max_cvar},
        "G4_secondary": {"pass": g4_pass, "expectancy": exp},
        "primary_gate_pass": g2_pass,
        "study_valid_null": not g2_pass and not g1_pass,
    }


def run_phase7_holdout(
    cfg: StudyConfig,
    *,
    data_dir: Path,
    frozen_signal: dict[str, Any],
    inference_meta: list[dict[str, Any]],
    holdout_preds: pd.DataFrame,
) -> Phase7Report:
    backtest_reg = load_backtest_register()
    register = load_holdout_register()
    chains_dir = cq_config.CRYOBACKTESTER_DATA_DIR
    n_trials = count_trials(trial_log_path(data_dir))

    eff_ts = _effective_start(register, cfg)
    eff_date = eff_ts.date()
    chain_dates = _valid_chain_dates(eff_date)
    bars = build_chain_bars(chain_dates, chains_dir)

    asset = frozen_signal.get("asset", register.get("chain_eval", {}).get("asset", "BTC"))
    horizon_id = frozen_signal.get("horizon_id", "T+1d")
    target_delta = float(
        register.get("sweep", {}).get("preregistered_primary", {}).get("target_delta", 0.15)
    )

    signals = build_horizon_signals_holdout(
        cfg,
        backtest_reg,
        asset=asset,
        horizon_id=horizon_id,
        target_delta=target_delta,
        slice_start=eff_ts,
    )
    policy = compose_short_vol_signal(
        signals,
        cfg.option_book,
        vrp_threshold=float(frozen_signal.get("vrp_threshold", 0.0)),
        min_physical_edge=float(frozen_signal.get("min_physical_edge", 0.0)),
        tilt_mode=frozen_signal.get("tilt_mode", "symmetric"),
    )

    chain_signals = signals.reindex(bars.index).dropna(subset=["dvol", "pred_fwd_rv"], how="any")
    chain_policy = policy.reindex(bars.index)
    chain_bars = bars.loc[chain_signals.index.intersection(bars.index)]

    model_sig = _bool_signal_from_mask("model_gated", chain_policy["fire"].fillna(False), chain_bars)
    naive_sig = _always_fire_signal("naive_seller")
    vrp_mask = chain_signals["iv_minus_rv"].fillna(-1.0) > 0
    vrp_sig = _bool_signal_from_mask("naive_vrp", vrp_mask, chain_bars)

    primary = register.get("sweep", {}).get("preregistered_primary", {})
    p_delta = float(primary.get("target_delta", 0.15))
    p_dte = int(primary.get("dte", 7))
    p_struct = primary.get("structure", "strangle")
    wing = cfg.option_book.wing_delta_offsets[0]

    report = Phase7Report(
        session_id=datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        frozen_signal=frozen_signal,
        inference_summary={
            "runs": len(inference_meta),
            "ok_runs": sum(1 for m in inference_meta if m.get("status") == "ok"),
            "prediction_rows": len(holdout_preds),
        },
        calibration_slice=_run_calibration_slice(cfg, holdout_preds, register, effective_start=eff_ts),
        chain_window={
            "effective_start": eff_ts.isoformat(),
            "chain_dates_available": len(chain_dates),
            "bars_with_spot": len(chain_bars),
            "first_date": chain_dates[0].isoformat() if chain_dates else None,
            "last_date": chain_dates[-1].isoformat() if chain_dates else None,
        },
        trial_log_count=n_trials,
    )

    svcfg = _short_vol_config(target_delta=p_delta, dte=p_dte, structure=p_struct, wing_offset=wing)
    model_res = evaluate_short_vol(model_sig, chain_bars, cfg=svcfg, chains_dir=chains_dir)
    naive_res = evaluate_short_vol(naive_sig, chain_bars, cfg=svcfg, chains_dir=chains_dir)
    vrp_res = evaluate_short_vol(vrp_sig, chain_bars, cfg=svcfg, chains_dir=chains_dir)

    report.preregistered_primary = _metrics_from_result(
        model_res,
        label="preregistered_primary",
        params={"target_delta": p_delta, "dte": p_dte, "structure": p_struct},
        target_delta=p_delta,
        n_trials=n_trials,
    )
    report.model_gated = {**report.preregistered_primary, "label": "model_gated"}
    report.naive_seller = _metrics_from_result(
        naive_res,
        label="naive_seller",
        params={"target_delta": p_delta, "dte": p_dte, "structure": p_struct},
        target_delta=p_delta,
        n_trials=n_trials,
    )
    report.naive_vrp_gate = _metrics_from_result(
        vrp_res,
        label="naive_vrp_gate",
        params={"target_delta": p_delta, "dte": p_dte, "structure": p_struct},
        target_delta=p_delta,
        n_trials=n_trials,
    )

    grid_rows: list[dict[str, Any]] = []
    for combo in _sweep_grid(register):
        svc = _short_vol_config(
            target_delta=combo["target_delta"],
            dte=combo["dte"],
            structure=combo["structure"],
            wing_offset=wing,
        )
        res = evaluate_short_vol(model_sig, chain_bars, cfg=svc, chains_dir=chains_dir)
        row = _metrics_from_result(
            res,
            label="report_all",
            params=combo,
            target_delta=combo["target_delta"],
            n_trials=n_trials,
        )
        row["run_id"] = (
            f"ho_{combo['structure']}_d{int(combo['target_delta']*100):02d}_"
            f"dte{combo['dte']}"
        )
        grid_rows.append(row)
    report.report_all_grid = grid_rows

    # Physical P(OTM) vs market delta on model fires with trades
    if model_res.fires_with_data > 0:
        pred_otm = 1.0 - p_delta + np.nanmean(chain_policy.loc[chain_policy["fire"], "exceedance_edge"].astype(float))
        otm_stats = otm_rate_vs_delta(
            np.asarray(model_res.realized_otm, dtype=float),
            np.full(len(model_res.realized_otm), 1.0 - p_delta),
        )
        report.physical_vs_delta = {
            "target_delta": p_delta,
            "implied_otm": 1.0 - p_delta,
            "mean_exceedance_edge_on_fires": float(
                chain_policy.loc[chain_policy["fire"], "exceedance_edge"].astype(float).mean()
            ),
            "physical_p_otm_proxy": pred_otm,
            **otm_stats,
            "gap_vs_market_delta": calibration_gap(
                otm_stats.get("realized_otm_rate", float("nan")), p_delta
            ),
        }
    else:
        report.physical_vs_delta = {"n": 0, "note": "no resolved model trades"}

    report.gates = _evaluate_gates(report, cfg, register)

    n_vol_fires = int((chain_signals["vol_edge"] > float(frozen_signal.get("vrp_threshold", 0))).sum())
    n_model_fires = int(chain_policy["fire"].fillna(False).sum()) if len(chain_policy) else 0
    report.chain_window["signal_diagnostics"] = {
        "bars_with_signals": len(chain_signals),
        "vol_edge_positive": n_vol_fires,
        "model_fires": n_model_fires,
        "mean_exceedance_edge": float(chain_signals["exceedance_edge"].mean()) if len(chain_signals) else float("nan"),
        "exceedance_gate_blocks": n_vol_fires > 0 and n_model_fires == 0,
        "frozen_min_physical_edge": float(frozen_signal.get("min_physical_edge", 0.0)),
    }
    return report


def write_phase7_artifacts(report: Phase7Report, data_dir: Path, reports_dir: Path) -> None:
    payload = asdict(report)
    (data_dir / "phase7_holdout_report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    from cryoquant.backtest.bundle import RunBundle, write_bundle

    if report.report_all_grid:
        lb = pd.DataFrame(report.report_all_grid)
        bundle = RunBundle(
            meta={
                "study": "btcpredict_v1",
                "phase": "phase7",
                "mode": "report_all",
                "n_runs": len(lb),
                "scoring": "distribution_only",
            },
            leaderboard=lb,
        )
        write_bundle(reports_dir / "bundles" / "holdout", bundle)
