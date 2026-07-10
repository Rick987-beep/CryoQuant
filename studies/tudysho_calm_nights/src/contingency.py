"""Hypothesis tests: Spearman, contingency lift, false calm, bootstrap CI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from cryoquant import config as cq_config
from cryoquant.backtest.option_lookup import _best_leg, _load_chain_df, _spot_price_on_date

from extrusion import path_extrusion, slice_bars
from sessions import hold_night_bounds_utc


@dataclass(frozen=True)
class LiftResult:
    hold_col: str
    n_total: int
    n_morning_quiet: int
    n_morning_active: int
    p_quiet_given_morning_quiet: float
    p_quiet_given_morning_active: float
    lift: float
    fisher_p: float
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "hold_col": self.hold_col,
            "n_total": self.n_total,
            "n_morning_quiet": self.n_morning_quiet,
            "n_morning_active": self.n_morning_active,
            "p_quiet_given_morning_quiet": self.p_quiet_given_morning_quiet,
            "p_quiet_given_morning_active": self.p_quiet_given_morning_active,
            "lift": self.lift,
            "fisher_p": self.fisher_p,
            "passed": self.passed,
        }


def spearman_matrix(daily: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Spearman rho between predictor / session / hold range extrusions."""
    pairs = [
        ("predictor_range", "us_afternoon_range"),
        ("predictor_range", "hold_night_range"),
        ("us_afternoon_range", "hold_night_range"),
        ("predictor_range", "hold_from_1200_range"),
        ("predictor_range", "hold_from_1400_range"),
    ]
    out: dict[str, dict[str, float]] = {}
    for a, b in pairs:
        if a not in daily.columns or b not in daily.columns:
            continue
        sub = daily[[a, b]].dropna()
        if len(sub) < 10:
            rho, p = float("nan"), float("nan")
        else:
            rho, p = stats.spearmanr(sub[a], sub[b])
        key = f"{a}__{b}"
        out[key] = {"rho": float(rho), "p_value": float(p), "n": len(sub)}
    return out


def contingency_lift(
    daily: pd.DataFrame,
    hold_quiet_col: str,
    *,
    min_lift: float = 1.5,
    max_p_value: float = 0.05,
    min_sample_days: int = 100,
) -> LiftResult:
    """Lift of P(hold quiet | predictor quiet) vs P(hold quiet | predictor active)."""
    quiet_col = "predictor_quiet"
    sub = daily.dropna(subset=[quiet_col, hold_quiet_col])
    n_total = len(sub)

    mq = sub[quiet_col].astype(bool)
    hq = sub[hold_quiet_col].astype(bool)

    quiet_quiet = int((mq & hq).sum())
    quiet_active = int((~mq & hq).sum())
    n_mq = int(mq.sum())
    n_ma = int((~mq).sum())

    p_qq = quiet_quiet / n_mq if n_mq else float("nan")
    p_aq = quiet_active / n_ma if n_ma else float("nan")
    lift = p_qq / p_aq if p_aq and p_aq > 0 else (float("inf") if p_qq > 0 else float("nan"))

    # 2x2: rows morning quiet/active, cols hold quiet/active
    a = quiet_quiet
    b = n_mq - quiet_quiet
    c = quiet_active
    d = n_ma - quiet_active
    _, fisher_p = stats.fisher_exact([[a, b], [c, d]])

    passed = (
        n_total >= min_sample_days
        and lift >= min_lift
        and fisher_p < max_p_value
        and not np.isnan(lift)
    )

    return LiftResult(
        hold_col=hold_quiet_col.replace("_quiet", ""),
        n_total=n_total,
        n_morning_quiet=n_mq,
        n_morning_active=n_ma,
        p_quiet_given_morning_quiet=float(p_qq),
        p_quiet_given_morning_active=float(p_aq),
        lift=float(lift),
        fisher_p=float(fisher_p),
        passed=bool(passed),
    )


def bootstrap_lift_ci(
    daily: pd.DataFrame,
    hold_quiet_col: str,
    *,
    n_bootstrap: int = 2000,
    seed: int = 42,
) -> dict[str, float]:
    """Block-bootstrap 95% CI on lift (blocks = calendar weeks)."""
    sub = daily.dropna(subset=["predictor_quiet", hold_quiet_col]).copy()
    if sub.empty:
        return {"lift_lower": float("nan"), "lift_upper": float("nan"), "lift_median": float("nan")}

    sub["entry_date"] = pd.to_datetime(sub["entry_date"])
    sub["week"] = sub["entry_date"].dt.isocalendar().week.astype(int)
    weeks = sub["week"].unique()
    rng = np.random.default_rng(seed)
    lifts: list[float] = []

    for _ in range(n_bootstrap):
        sampled_weeks = rng.choice(weeks, size=len(weeks), replace=True)
        parts = [sub[sub["week"] == w] for w in sampled_weeks]
        boot = pd.concat(parts, ignore_index=True)
        r = contingency_lift(boot, hold_quiet_col)
        if not np.isnan(r.lift):
            lifts.append(r.lift)

    if not lifts:
        return {"lift_lower": float("nan"), "lift_upper": float("nan"), "lift_median": float("nan")}

    arr = np.array(lifts)
    return {
        "lift_lower": float(np.percentile(arr, 2.5)),
        "lift_upper": float(np.percentile(arr, 97.5)),
        "lift_median": float(np.median(arr)),
    }


def weekday_stratified_lift(
    daily: pd.DataFrame, hold_quiet_col: str
) -> dict[str, dict[str, float]]:
    """Per-weekday lift for robustness reporting."""
    out: dict[str, dict[str, float]] = {}
    sub = daily.copy()
    sub["entry_date"] = pd.to_datetime(sub["entry_date"])
    sub["weekday"] = sub["entry_date"].dt.day_name()
    for wd, grp in sub.groupby("weekday"):
        if len(grp) < 15:
            continue
        r = contingency_lift(grp, hold_quiet_col, min_sample_days=0)
        out[wd] = {"lift": r.lift, "n": r.n_total}
    return out


def _apply_min_otm(
    leg: pd.Series,
    spot: float,
    min_otm_pct: float,
    is_call: bool,
    chain: pd.DataFrame,
    expiry_label: str,
) -> pd.Series:
    """Push strike further OTM if below min_otm_pct."""
    strike = float(leg["strike"])
    if is_call:
        otm_pct = (strike - spot) / spot * 100.0
        if otm_pct >= min_otm_pct:
            return leg
        target_strike = spot * (1.0 + min_otm_pct / 100.0)
        candidates = chain[
            (chain["expiry"] == expiry_label)
            & (chain["is_call"] == True)  # noqa: E712
            & (chain["strike"] >= target_strike)
            & (chain["bid_price"] > 0)
        ].sort_values("strike")
    else:
        otm_pct = (spot - strike) / spot * 100.0
        if otm_pct >= min_otm_pct:
            return leg
        target_strike = spot * (1.0 - min_otm_pct / 100.0)
        candidates = chain[
            (chain["expiry"] == expiry_label)
            & (chain["is_call"] == False)  # noqa: E712
            & (chain["strike"] <= target_strike)
            & (chain["bid_price"] > 0)
        ].sort_values("strike", ascending=False)

    if candidates.empty:
        return leg
    return candidates.iloc[0]


def _min_otm_distance_pct(call_leg: pd.Series, put_leg: pd.Series, spot: float) -> float:
    call_dist = (float(call_leg["strike"]) - spot) / spot
    put_dist = (spot - float(put_leg["strike"])) / spot
    return float(min(call_dist, put_dist))


def false_calm_events(
    daily: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    delta: float = 0.20,
    min_otm_pct: float = 1.0,
    proximity_buffer_usd: float = 1000.0,
    chains_dir: Any | None = None,
) -> pd.DataFrame:
    """Morning-quiet days where hold window breaches δ strangle strike buffer."""
    chains_dir = chains_dir or cq_config.CRYOBACKTESTER_DATA_DIR
    quiet_days = daily[daily["predictor_quiet"].fillna(False)].copy()
    events: list[dict] = []

    for _, row in quiet_days.iterrows():
        entry_day = date.fromisoformat(row["entry_date"])
        chain = _load_chain_df(chains_dir, entry_day)
        if chain is None:
            continue
        spot = _spot_price_on_date(chains_dir, entry_day)
        if spot is None:
            continue

        expiry_day = entry_day + timedelta(days=1)
        call_leg = _best_leg(chain, expiry_day, delta, is_call=True)
        put_leg = _best_leg(chain, expiry_day, delta, is_call=False)
        if call_leg is None or put_leg is None:
            continue

        from cryoquant.backtest.option_lookup import _to_deribit_expiry

        expiry_label = _to_deribit_expiry(expiry_day)
        call_leg = _apply_min_otm(call_leg, spot, min_otm_pct, True, chain, expiry_label)
        put_leg = _apply_min_otm(put_leg, spot, min_otm_pct, False, chain, expiry_label)

        call_strike = float(call_leg["strike"])
        put_strike = float(put_leg["strike"])
        min_dist = _min_otm_distance_pct(call_leg, put_leg, spot)

        h0, h1 = hold_night_bounds_utc(entry_day)
        hold_bars = slice_bars(bars, pd.Timestamp(h0), pd.Timestamp(h1))
        if hold_bars.empty:
            continue

        hold_low = float(hold_bars["low"].min())
        hold_high = float(hold_bars["high"].max())
        breached = (
            hold_high >= call_strike - proximity_buffer_usd
            or hold_low <= put_strike + proximity_buffer_usd
        )
        hold_path = path_extrusion(hold_bars)
        ratio = hold_path / min_dist if min_dist > 0 else float("inf")

        events.append(
            {
                "entry_date": row["entry_date"],
                "hold_path": hold_path,
                "min_otm_distance_pct": min_dist,
                "extrusion_ratio": ratio,
                "strike_breach": breached,
                "false_calm": breached,
                "delta": delta,
            }
        )

    return pd.DataFrame(events)


def run_contingency_tests(
    daily: pd.DataFrame,
    bars: pd.DataFrame,
    cfg: dict,
) -> dict[str, Any]:
    """Run full Phase 0 hypothesis test battery."""
    hyp = cfg["hypothesis"]
    min_lift = hyp["min_lift"]
    max_p = hyp["max_p_value"]
    min_n = hyp["min_sample_days"]

    hold_cols = [
        "hold_night_quiet",
        "hold_from_1200_quiet",
        "hold_from_1400_quiet",
    ]

    lifts: dict[str, Any] = {}
    for col in hold_cols:
        if col not in daily.columns:
            continue
        r = contingency_lift(
            daily, col, min_lift=min_lift, max_p_value=max_p, min_sample_days=min_n
        )
        lifts[col] = r.to_dict()
        lifts[col]["bootstrap_ci"] = bootstrap_lift_ci(daily, col)
        lifts[col]["weekday_lift"] = weekday_stratified_lift(daily, col)

    primary = lifts.get("hold_night_quiet", {})
    fc_cfg = cfg.get("false_calm", {})
    fc_events = false_calm_events(
        daily,
        bars,
        delta=fc_cfg.get("delta", 0.10),
        min_otm_pct=fc_cfg.get("min_otm_pct", 2.6),
        proximity_buffer_usd=fc_cfg.get("proximity_buffer_usd", 1000.0),
    )
    n_quiet = int(daily["predictor_quiet"].fillna(False).sum())
    n_false = int(fc_events["false_calm"].sum()) if not fc_events.empty else 0
    false_calm_rate = (n_false / n_quiet * 100.0) if n_quiet else float("nan")
    ref_tail = cfg["objective"]["reference_tail_rate_pct"]

    return {
        "n_days": len(daily),
        "n_morning_quiet": n_quiet,
        "spearman": spearman_matrix(daily),
        "lifts": lifts,
        "primary_gate": {
            "hold_col": "hold_night",
            "passed": primary.get("passed", False),
            "lift": primary.get("lift"),
            "fisher_p": primary.get("fisher_p"),
        },
        "false_calm": {
            "n_events": len(fc_events),
            "n_false_calm": n_false,
            "rate_pct": false_calm_rate,
            "threshold_pct": ref_tail,
            "passed": false_calm_rate < ref_tail if not np.isnan(false_calm_rate) else False,
            "events": fc_events.to_dict(orient="records") if not fc_events.empty else [],
        },
    }
