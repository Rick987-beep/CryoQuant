"""Phase 1 — feature ranking on tail days vs turbulence, IV, calendar."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from cryoquant import config as cq_config
from cryoquant.backtest.option_lookup import _load_chain_df, _spot_price_on_date

from sessions import nyc_dt, to_utc

PACKAGE_INDICATORS = Path(__file__).resolve().parents[1] / "package" / "indicators"


def _load_turbulence_module():
    path = PACKAGE_INDICATORS / "turbulence_reference.py"
    spec = importlib.util.spec_from_file_location("turbulence_reference", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


# Known tail references from handover
TAIL_DATES = {
    "2025-10-15",  # Oct-2025 expiry loss benchmark (approximate)
}


def turbulence_at_nyc_time(
    turb_df: pd.DataFrame,
    entry_day: date,
    entry_time: str,
) -> dict[str, float]:
    """T−1h UTC bucket lookup at NYC wall-clock entry (CryoTrader convention)."""
    from sessions import parse_entry_time_nyc

    t = parse_entry_time_nyc(entry_time)
    entry_utc = to_utc(nyc_dt(entry_day, t))
    bucket = entry_utc.replace(minute=0, second=0, microsecond=0) - pd.Timedelta(hours=1)
    if bucket not in turb_df.index:
        # nearest prior hour
        prior = turb_df.index[turb_df.index <= bucket]
        if len(prior) == 0:
            return {}
        bucket = prior[-1]
    row = turb_df.loc[bucket]
    return {
        "composite": float(row.get("composite", np.nan)),
        "vol_score": float(row.get("vol_score", np.nan)),
        "decay_score": float(row.get("decay_score", np.nan)),
    }


def atm_iv_percentile(chain: pd.DataFrame, spot: float) -> float:
    """ATM mark_iv from chain (nearest strike)."""
    if chain.empty or "mark_iv" not in chain.columns:
        return float("nan")
    chain = chain.copy()
    chain["strike_dist"] = (chain["strike"] - spot).abs()
    atm = chain.nsmallest(5, "strike_dist")
    if atm.empty:
        return float("nan")
    return float(atm["mark_iv"].median())


def enrich_daily_features(
    daily: pd.DataFrame,
    bars_15m: pd.DataFrame,
) -> pd.DataFrame:
    """Add turbulence, IV, and calendar flags per slot-A day."""
    turb_mod = _load_turbulence_module()
    turb_df = turb_mod.turbulence(bars_15m)

    chains_dir = cq_config.CRYOBACKTESTER_DATA_DIR
    rows = []
    for _, row in daily.iterrows():
        entry_day = date.fromisoformat(row["entry_date"])
        rec = dict(row)

        for label, et in [("12", "12:00"), ("16", "16:00")]:
            tvals = turbulence_at_nyc_time(turb_df, entry_day, et)
            for k, v in tvals.items():
                rec[f"turbulence_{k}_{label}"] = v

        chain = _load_chain_df(chains_dir, entry_day)
        spot = _spot_price_on_date(chains_dir, entry_day)
        if chain is not None and spot is not None:
            rec["atm_iv"] = atm_iv_percentile(chain, spot)
        else:
            rec["atm_iv"] = float("nan")

        rec["is_tail_reference"] = row["entry_date"] in TAIL_DATES
        rows.append(rec)

    return pd.DataFrame(rows)


def _tail_labels(enriched: pd.DataFrame, contingency: dict | None) -> pd.Series:
    """Binary tail label: reference dates + false-calm events from Phase 0."""
    labels = enriched["entry_date"].isin(TAIL_DATES)
    if contingency:
        for ev in contingency.get("false_calm", {}).get("events", []):
            if ev.get("false_calm"):
                labels = labels | (enriched["entry_date"] == ev["entry_date"])
    return labels.astype(bool)


def _auc_binary(feature: pd.Series, target: pd.Series) -> float:
    sub = pd.DataFrame({"f": feature, "t": target}).dropna()
    if sub["t"].nunique() < 2 or len(sub) < 10:
        return float("nan")
    ranks = stats.rankdata(sub["f"])
    n1 = sub["t"].sum()
    n0 = len(sub) - n1
    if n0 == 0 or n1 == 0:
        return float("nan")
    sum_ranks_pos = ranks[sub["t"].values].sum()
    u = sum_ranks_pos - n1 * (n1 + 1) / 2
    return float(u / (n0 * n1))


def rank_features(
    enriched: pd.DataFrame,
    contingency: dict | None = None,
) -> dict[str, Any]:
    """Univariate AUC/lift per feature on tail vs non-tail days."""
    target = _tail_labels(enriched, contingency)
    feature_cols = [
        "us_morning_range_norm",
        "turbulence_composite_12",
        "turbulence_composite_16",
        "turbulence_decay_score_12",
        "turbulence_vol_score_12",
        "atm_iv",
    ]
    rankings: list[dict] = []
    for col in feature_cols:
        if col not in enriched.columns:
            continue
        auc = _auc_binary(enriched[col], target)
        rankings.append({"feature": col, "auc": auc})

    rankings.sort(key=lambda x: abs(x["auc"] - 0.5) if not np.isnan(x["auc"]) else -1, reverse=True)

    # Incremental: morning extrusion vs turbulence at 12:00
    morning_auc = next((r["auc"] for r in rankings if r["feature"] == "us_morning_range_norm"), float("nan"))
    turb_auc = next((r["auc"] for r in rankings if r["feature"] == "turbulence_composite_12"), float("nan"))

    return {
        "n_days": len(enriched),
        "n_tail_days": int(target.sum()),
        "feature_rankings": rankings,
        "incremental_value": {
            "morning_extrusion_auc": morning_auc,
            "turbulence_12_auc": turb_auc,
            "morning_beats_turbulence": (
                abs(morning_auc - 0.5) > abs(turb_auc - 0.5)
                if not (np.isnan(morning_auc) or np.isnan(turb_auc))
                else None
            ),
        },
        "recommendation": (
            "Proceed with overnight_calm_score combining morning extrusion + decay_score"
            if abs(morning_auc - 0.5) >= abs(turb_auc - 0.5)
            else "Turbulence may dominate; weight decay_score + morning extrusion carefully"
        ),
    }
