"""Crunch Fund vintage backtester — 5y lottery mandate on CDX.NA.IG."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .backtest_cds import run_overlay
from .cds_cost_model import CdsEconomicsConfig
from .paths import ANALYSIS_ROOT, data_dir
from .signals_tail import pyramid_tail_insurance, standing_tail_insurance, tail_hold_on_spike

NO_EXIT_BPS = 9_999.0


@lru_cache(maxsize=1)
def load_crunch_config() -> dict:
    path = ANALYSIS_ROOT / "config_crunch_fund.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass(frozen=True)
class CrunchFundSpec:
    """Single crunch-fund configuration."""

    strategy: str              # standing | spike | pyramid
    notional_usd: float
    entry_max_bps: float
    exit_bps: float | None = None     # None = no spread exit (base leg for pyramid)
    addon_entry_bps: float | None = None
    addon_retreat_bps: float | None = None
    addon_hold_days: int | None = None
    collateral_usd: float = 5_000_000

    @property
    def exit_bps_effective(self) -> float:
        return self.exit_bps if self.exit_bps is not None else NO_EXIT_BPS

    @property
    def run_id(self) -> str:
        x = "no_exit" if self.exit_bps is None else f"x{int(self.exit_bps)}"
        n = int(self.notional_usd / 1e6)
        if self.strategy == "pyramid":
            a = int(self.addon_entry_bps or 0)
            r = int(self.addon_retreat_bps or 0)
            h = int(self.addon_hold_days or 0)
            return f"pyramid_e{int(self.entry_max_bps)}_a{a}_r{r}_h{h}_{x}_n{n}m"
        return f"{self.strategy}_e{int(self.entry_max_bps)}_{x}_n{n}m"


@dataclass
class CrunchVintageResult:
    spec: CrunchFundSpec
    vintage_start: pd.Timestamp
    vintage_end: pd.Timestamp
    equity: pd.Series
    positions: pd.Series
    overlay_name: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    episodes: list[dict[str, Any]] = field(default_factory=list)


def fund_vintage_starts(
    index: pd.DatetimeIndex,
    *,
    fund_years: int = 5,
    freq: str = "QS",
) -> list[pd.Timestamp]:
    """Quarterly (or other) fund inception dates with full fund_years of data ahead."""
    if len(index) == 0:
        return []
    starts: list[pd.Timestamp] = []
    origin = index[0]
    candidates = pd.date_range(origin, index[-1], freq=freq, tz=index.tz)
    for t0 in candidates:
        if t0 < origin:
            continue
        t_end = t0 + pd.DateOffset(years=fund_years)
        if t_end > index[-1]:
            break
        starts.append(pd.Timestamp(t0))
    return starts


def build_crunch_position(
    spread_bps: pd.Series,
    spec: CrunchFundSpec,
    *,
    is_roll: pd.Series | None = None,
) -> pd.Series:
    if spec.strategy == "standing":
        return standing_tail_insurance(
            spread_bps,
            entry_max_bps=spec.entry_max_bps,
            exit_bps=spec.exit_bps_effective,
            skip_roll=is_roll,
        )
    if spec.strategy == "spike":
        return tail_hold_on_spike(spread_bps)
    if spec.strategy == "pyramid":
        if spec.addon_entry_bps is None or spec.addon_retreat_bps is None or spec.addon_hold_days is None:
            raise ValueError("pyramid strategy requires addon_entry_bps, addon_retreat_bps, addon_hold_days")
        return pyramid_tail_insurance(
            spread_bps,
            entry_max_bps=spec.entry_max_bps,
            base_exit_bps=spec.exit_bps_effective,
            addon_entry_bps=spec.addon_entry_bps,
            addon_retreat_bps=spec.addon_retreat_bps,
            addon_hold_days=spec.addon_hold_days,
            skip_roll=is_roll,
        )
    raise ValueError(f"unknown strategy: {spec.strategy}")


def analytical_notional_for_10x(
    collateral_usd: float,
    delta_bps: float,
    *,
    duration: float = 5.0,
    target_multiple: float = 10.0,
) -> float:
    """Notional required for target peak NAV on a pure MTM delta (ignores carry)."""
    target_pnl = (target_multiple - 1.0) * collateral_usd
    if delta_bps <= 0:
        return float("inf")
    return target_pnl * 10_000 / (duration * delta_bps)


def analytical_tier_c_peak_nav(
    notional_usd: float,
    collateral_usd: float,
    delta_bps: float,
    *,
    duration: float = 5.0,
) -> float:
    pnl = notional_usd * duration * delta_bps / 10_000
    return 1.0 + pnl / collateral_usd


def _years_to_depletion(equity: pd.Series, floor_nav: float) -> float | None:
    below = equity <= floor_nav
    if not below.any():
        return None
    first = below[below].index[0]
    days = (first - equity.index[0]).days
    return days / 365.25


def _calm_burn(attribution: pd.DataFrame, spread: pd.Series, threshold: float = 80.0) -> float:
    calm = spread < threshold
    return float(attribution.loc[calm, "total"].sum())


def evaluate_episode(
    equity: pd.Series,
    positions: pd.Series,
    attribution: pd.DataFrame,
    episode: dict[str, Any],
    *,
    collateral_usd: float,
    target_multiple: float = 10.0,
    nav_floor: float = 0.05,
) -> dict[str, Any]:
    """Compute crisis metrics for one episode window."""
    ep_id = episode["id"]
    tier = episode.get("tier", "A")

    if episode.get("synthetic"):
        delta = float(episode.get("delta_bps", 200))
        notional = float(
            attribution.attrs.get("effective_notional_usd", attribution.attrs.get("notional_usd", 0))
        )
        peak_mult = analytical_tier_c_peak_nav(notional, collateral_usd, delta)
        crisis_pnl = (peak_mult - 1.0) * collateral_usd
        return {
            "episode_id": ep_id,
            "tier": tier,
            "label": episode.get("label", ep_id),
            "synthetic": True,
            "in_market_at_onset": True,
            "crisis_nav_peak_multiple": peak_mult,
            "crisis_pnl_usd": crisis_pnl,
            "crisis_return_on_capital": peak_mult - 1.0,
            "distance_to_10x": max(target_multiple - peak_mult, 0.0),
            "hit_10x": peak_mult >= target_multiple,
            "capture_ratio": 1.0,
        }

    start, end = episode["start"], episode["end"]
    slc_eq = equity.loc[start:end]
    if slc_eq.empty:
        return {
            "episode_id": ep_id,
            "tier": tier,
            "label": episode.get("label", ep_id),
            "in_market_at_onset": False,
            "crisis_nav_peak_multiple": float("nan"),
            "crisis_pnl_usd": float("nan"),
            "distance_to_10x": float("nan"),
            "hit_10x": False,
        }

    onset = slc_eq.index[0]
    pre = equity.loc[:onset]
    raw_start = float(pre.iloc[-1]) if len(pre) else float(equity.iloc[0])
    nav_start = max(raw_start, nav_floor)
    nav_peak = float(slc_eq.max())
    peak_mult = nav_peak / nav_start if nav_start > 0 else float("nan")
    crisis_pnl = float(attribution.loc[start:end, "total"].sum())
    in_market = float(positions.loc[onset]) > 0 if onset in positions.index else False

    # PnL-based multiple (robust when NAV is depleted): episode dollar PnL on initial collateral
    pnl_multiple = 1.0 + crisis_pnl / collateral_usd

    # Theoretical peak if held full episode without exit (position=1 throughout)
    notional = float(attribution.attrs.get("notional_usd", 0))
    spread_slc = attribution.attrs.get("spread_slice")
    theoretical_peak = peak_mult
    capture_ratio = 1.0
    if spread_slc is not None and notional > 0:
        sp = spread_slc.loc[start:end]
        if len(sp) > 1:
            delta = float(sp.max() - sp.iloc[0])
            theo_pnl = notional * 5.0 * delta / 10_000
            theo_mult = nav_start + theo_pnl / collateral_usd
            if theo_mult > 0:
                capture_ratio = min(peak_mult / theo_mult, 1.0) if theo_mult > nav_start else 1.0
                theoretical_peak = theo_mult / nav_start

    return {
        "episode_id": ep_id,
        "tier": tier,
        "label": episode.get("label", ep_id),
        "synthetic": False,
        "in_market_at_onset": in_market,
        "crisis_nav_start": raw_start,
        "crisis_nav_peak_multiple": peak_mult,
        "crisis_pnl_multiple": pnl_multiple,
        "crisis_pnl_usd": crisis_pnl,
        "crisis_return_on_capital": crisis_pnl / collateral_usd,
        "distance_to_10x": max(target_multiple - peak_mult, 0.0),
        "distance_to_10x_pnl": max(target_multiple - pnl_multiple, 0.0),
        "hit_10x": peak_mult >= target_multiple,
        "hit_10x_pnl": pnl_multiple >= target_multiple,
        "capture_ratio": capture_ratio,
        "theoretical_peak_multiple": theoretical_peak,
    }


def run_fund_vintage(
    spread_bps: pd.Series,
    features: pd.DataFrame,
    spec: CrunchFundSpec,
    vintage_start: pd.Timestamp,
    vintage_end: pd.Timestamp,
    *,
    config: CdsEconomicsConfig | None = None,
    episodes: list[dict] | None = None,
    nav_floor_pct: float = 0.05,
    target_multiple: float = 10.0,
) -> CrunchVintageResult:
    """Run one 5-year fund vintage."""
    config = config or CdsEconomicsConfig.from_yaml()
    collateral = spec.collateral_usd
    mask = (spread_bps.index >= vintage_start) & (spread_bps.index <= vintage_end)
    spread = spread_bps.loc[mask]
    feat = features.loc[mask]
    roll = feat["is_roll_window"] if "is_roll_window" in feat.columns else None

    pos = build_crunch_position(spread, spec, is_roll=roll)
    result = run_overlay(
        spread, pos, name=spec.run_id, notional_usd=spec.notional_usd,
        config=config, is_roll_day=roll, collateral_usd=collateral,
    )

    floor_nav = 1.0 * nav_floor_pct
    years_dep = _years_to_depletion(result.equity, floor_nav)
    calm_burn = _calm_burn(result.daily_attribution, spread)

    max_pos = float(pos.max()) if len(pos) else 1.0
    result.daily_attribution.attrs["notional_usd"] = spec.notional_usd
    result.daily_attribution.attrs["effective_notional_usd"] = spec.notional_usd * max(max_pos, 1.0)
    result.daily_attribution.attrs["spread_slice"] = spread

    ep_cfg = episodes or load_crunch_config().get("episodes", [])
    ep_rows = [
        evaluate_episode(
            result.equity, result.positions, result.daily_attribution, ep,
            collateral_usd=collateral, target_multiple=target_multiple,
            nav_floor=nav_floor_pct,
        )
        for ep in ep_cfg
    ]

    tier_bc = [
        e for e in ep_rows
        if e.get("tier") in ("B", "C") and e.get("in_market_at_onset", False) and not e.get("synthetic")
    ]
    tier_bc_synth = [e for e in ep_rows if e.get("tier") == "C" and e.get("synthetic")]
    best_bc = max(tier_bc, key=lambda e: e.get("crisis_pnl_multiple", 0) or 0) if tier_bc else {}
    best_synth = tier_bc_synth[0] if tier_bc_synth else {}
    tier_a = [e for e in ep_rows if e.get("tier") == "A"]

    delta_c = float(load_crunch_config()["crunch_fund"].get("tier_c_delta_bps", 200))
    notional_10x = analytical_notional_for_10x(collateral, delta_c, duration=config.duration, target_multiple=target_multiple)

    metrics = {
        **result.metrics,
        "vintage_start": str(vintage_start.date()),
        "vintage_end": str(vintage_end.date()),
        "terminal_nav": float(result.equity.iloc[-1]),
        "calm_burn_usd": calm_burn,
        "years_to_depletion": years_dep,
        "pct_in_market": result.metrics.get("pct_in_market", 0),
        "notional_for_10x": notional_10x,
        "crisis_nav_peak_tier_bc": best_bc.get("crisis_pnl_multiple", best_bc.get("crisis_nav_peak_multiple", float("nan"))),
        "distance_to_10x_tier_bc": best_bc.get("distance_to_10x_pnl", best_bc.get("distance_to_10x", float("nan"))),
        "hit_10x_tier_bc": bool(best_bc.get("hit_10x_pnl", best_bc.get("hit_10x", False))),
        "tier_c_analytical_multiple": best_synth.get("crisis_nav_peak_multiple", float("nan")),
        "covid_peak_multiple": tier_a[0].get("crisis_pnl_multiple", tier_a[0].get("crisis_nav_peak_multiple")) if tier_a else float("nan"),
        "distance_to_10x_covid": tier_a[0].get("distance_to_10x") if tier_a else float("nan"),
    }

    return CrunchVintageResult(
        spec=spec,
        vintage_start=vintage_start,
        vintage_end=vintage_end,
        equity=result.equity,
        positions=result.positions,
        overlay_name=result.name,
        metrics=metrics,
        episodes=ep_rows,
    )


def _parse_exit_bps(exit_bps: Any) -> float | None:
    return None if exit_bps in (None, "null") else float(exit_bps)


def _standing_spike_specs(sweeps: dict, collateral: float) -> list[CrunchFundSpec]:
    specs: list[CrunchFundSpec] = []
    for strategy in sweeps["strategies"]:
        if strategy == "pyramid":
            continue
        for notional in sweeps["notional_usd"]:
            for entry in sweeps["entry_max_bps"]:
                for exit_bps in sweeps["exit_bps"]:
                    specs.append(CrunchFundSpec(
                        strategy=strategy,
                        notional_usd=float(notional),
                        entry_max_bps=float(entry),
                        exit_bps=_parse_exit_bps(exit_bps),
                        collateral_usd=collateral,
                    ))
    return specs


def _pyramid_specs(pyramid_sweeps: dict, collateral: float) -> list[CrunchFundSpec]:
    specs: list[CrunchFundSpec] = []
    for notional in pyramid_sweeps["notional_usd"]:
        for entry in pyramid_sweeps["entry_max_bps"]:
            for exit_bps in pyramid_sweeps["exit_bps"]:
                for addon_entry in pyramid_sweeps["addon_entry_bps"]:
                    for retreat in pyramid_sweeps["addon_retreat_bps"]:
                        for hold in pyramid_sweeps["addon_hold_days"]:
                            specs.append(CrunchFundSpec(
                                strategy="pyramid",
                                notional_usd=float(notional),
                                entry_max_bps=float(entry),
                                exit_bps=_parse_exit_bps(exit_bps),
                                addon_entry_bps=float(addon_entry),
                                addon_retreat_bps=float(retreat),
                                addon_hold_days=int(hold),
                                collateral_usd=collateral,
                            ))
    return specs


def iter_specs(cfg: dict | None = None) -> list[CrunchFundSpec]:
    """Expand sweep grid into CrunchFundSpec list."""
    cfg = cfg or load_crunch_config()
    cf = cfg["crunch_fund"]
    collateral = float(cf["collateral_usd"])
    sweeps = cfg["sweeps"]
    specs = _standing_spike_specs(sweeps, collateral)
    if "pyramid" in sweeps.get("strategies", []) and "pyramid_sweeps" in cfg:
        specs.extend(_pyramid_specs(cfg["pyramid_sweeps"], collateral))
    return specs


def aggregate_config_results(vintage_rows: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-vintage rows to one leaderboard row per config."""
    if vintage_rows.empty:
        return vintage_rows

    agg = vintage_rows.groupby("run_id", as_index=False).agg(
        strategy=("strategy", "first"),
        notional_usd=("notional_usd", "first"),
        entry_max_bps=("entry_max_bps", "first"),
        exit_bps=("exit_bps", "first"),
        n_vintages=("vintage_start", "count"),
        median_terminal_nav=("terminal_nav", "median"),
        min_terminal_nav=("terminal_nav", "min"),
        max_crisis_peak_tier_bc=("crisis_nav_peak_tier_bc", "max"),
        min_distance_10x_tier_bc=("distance_to_10x_tier_bc", "min"),
        hit_10x_rate_tier_bc=("hit_10x_tier_bc", "mean"),
        median_covid_peak=("covid_peak_multiple", "median"),
        median_calm_burn=("calm_burn_usd", "median"),
        notional_for_10x=("notional_for_10x", "first"),
        median_years_to_depletion=("years_to_depletion", "median"),
    )
    agg["distance_to_10x_tier_bc"] = agg["min_distance_10x_tier_bc"]
    agg["crisis_nav_peak_tier_bc"] = agg["max_crisis_peak_tier_bc"]
    return agg.sort_values("distance_to_10x_tier_bc", ascending=True).reset_index(drop=True)
