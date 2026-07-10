"""Continuous entry schedule from morning calm index + walk-forward verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LinearRegression


@dataclass(frozen=True)
class EntryWindow:
    earliest: time  # 12:00 NYC
    latest: time    # 16:00 NYC
    step_minutes: int = 15

    @property
    def earliest_minutes(self) -> int:
        return self.earliest.hour * 60 + self.earliest.minute

    @property
    def latest_minutes(self) -> int:
        return self.latest.hour * 60 + self.latest.minute

    @property
    def span_minutes(self) -> int:
        return self.latest_minutes - self.earliest_minutes


def parse_hhmm(s: str) -> time:
    parts = s.strip().split(":")
    return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


def mci_to_entry_minutes(mci: float, window: EntryWindow) -> int:
    """Map morning calm index → NYC entry minutes since midnight.

    MCI=1 (calm) → earliest entry; MCI=0 (active) → latest entry.
    """
    mci = float(np.clip(mci, 0.0, 1.0))
    raw = window.latest_minutes - mci * window.span_minutes
    if window.step_minutes > 0:
        raw = round(raw / window.step_minutes) * window.step_minutes
    return int(np.clip(raw, window.earliest_minutes, window.latest_minutes))


def minutes_to_hhmm(minutes: int) -> str:
    minutes = int(minutes)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def add_entry_schedule(
    daily: pd.DataFrame,
    *,
    mci_col: str = "morning_calm_index",
    window: EntryWindow,
) -> pd.DataFrame:
    df = daily.copy()
    mins = df[mci_col].apply(lambda x: mci_to_entry_minutes(x, window) if pd.notna(x) else np.nan)
    df["entry_minutes_nyc"] = mins
    df["entry_time_nyc"] = df["entry_minutes_nyc"].apply(
        lambda m: minutes_to_hhmm(int(m)) if pd.notna(m) else None
    )
    df["minutes_earlier_than_base"] = window.latest_minutes - df["entry_minutes_nyc"]
    return df


def _valid_pairs(df: pd.DataFrame, x_col: str, y_col: str) -> pd.DataFrame:
    return df[[x_col, y_col, "entry_date"]].dropna()


def fit_predictor(
    train: pd.DataFrame,
    *,
    x_col: str = "morning_calm_index",
    y_col: str = "hold_night_calm_index",
) -> dict[str, Any]:
    """Fit linear + isotonic predictors of hold calm from morning calm."""
    sub = _valid_pairs(train, x_col, y_col)
    if len(sub) < 30:
        return {"status": "insufficient_train", "n": len(sub)}

    x = sub[x_col].to_numpy().reshape(-1, 1)
    y = sub[y_col].to_numpy()

    lin = LinearRegression()
    lin.fit(x, y)
    y_hat_lin = lin.predict(x)

    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(sub[x_col].to_numpy(), y)

    rho, rho_p = stats.spearmanr(sub[x_col], sub[y_col])
    pearson_r, pearson_p = stats.pearsonr(sub[x_col], sub[y_col])

    return {
        "status": "ok",
        "n_train": len(sub),
        "spearman_rho": float(rho),
        "spearman_p": float(rho_p),
        "pearson_r": float(pearson_r),
        "pearson_p": float(pearson_p),
        "linear": {
            "intercept": float(lin.intercept_),
            "slope": float(lin.coef_[0]),
            "r2_in_sample": float(lin.score(x, y)),
        },
        "isotonic": {"fitted": True},
        "_lin_model": lin,
        "_iso_model": iso,
        "in_sample_mae": float(np.mean(np.abs(y - y_hat_lin))),
    }


def predict_hold_calm(
    df: pd.DataFrame,
    model: dict[str, Any],
    *,
    x_col: str = "morning_calm_index",
) -> pd.Series:
    if model.get("status") != "ok":
        return pd.Series(np.nan, index=df.index)
    lin: LinearRegression = model["_lin_model"]
    return pd.Series(lin.predict(df[[x_col]].to_numpy()), index=df.index).clip(0, 1)


def evaluate_oos(
    df: pd.DataFrame,
    *,
    min_train: int = 80,
    test_size: int = 40,
    x_col: str = "morning_calm_index",
    y_col: str = "hold_night_calm_index",
) -> dict[str, Any]:
    """Expanding-window walk-forward: train on past, predict next *test_size* days."""
    sub = df.sort_values("entry_date").reset_index(drop=True)
    sub = sub.dropna(subset=[x_col, y_col])
    n = len(sub)
    if n < min_train + test_size:
        return {"status": "insufficient_data", "n": n}

    folds: list[dict] = []
    start_test = min_train
    while start_test + test_size <= n:
        train = sub.iloc[:start_test]
        test = sub.iloc[start_test : start_test + test_size]
        model = fit_predictor(train, x_col=x_col, y_col=y_col)
        if model.get("status") != "ok":
            start_test += test_size
            continue

        pred = predict_hold_calm(test, model, x_col=x_col)
        y_true = test[y_col]
        mae = float(np.mean(np.abs(y_true - pred)))
        rho, _ = stats.spearmanr(test[x_col], y_true)
        pred_rho, _ = stats.spearmanr(pred, y_true)

        folds.append(
            {
                "train_end": test["entry_date"].iloc[0],
                "test_start": test["entry_date"].iloc[0],
                "test_end": test["entry_date"].iloc[-1],
                "n_train": len(train),
                "n_test": len(test),
                "mae": mae,
                "spearman_mci_hci": float(rho),
                "spearman_pred_hci": float(pred_rho) if not np.isnan(pred_rho) else None,
            }
        )
        start_test += test_size

    if not folds:
        return {"status": "no_folds", "n": n}

    maes = [f["mae"] for f in folds]
    pred_rhos = [f["spearman_pred_hci"] for f in folds if f["spearman_pred_hci"] is not None]

    return {
        "status": "ok",
        "n_folds": len(folds),
        "folds": folds,
        "mean_oos_mae": float(np.mean(maes)),
        "mean_oos_spearman_pred": float(np.mean(pred_rhos)) if pred_rhos else None,
        "min_train": min_train,
        "test_size": test_size,
    }


def calibration_bins(
    df: pd.DataFrame,
    *,
    x_col: str = "morning_calm_index",
    y_col: str = "hold_night_calm_index",
    n_bins: int = 10,
) -> list[dict[str, Any]]:
    """Bin MCI deciles → mean HCI (calibration curve)."""
    sub = _valid_pairs(df, x_col, y_col)
    if sub.empty:
        return []
    sub = sub.copy()
    sub["bin"] = pd.qcut(sub[x_col], q=n_bins, duplicates="drop")
    rows = []
    for label, grp in sub.groupby("bin", observed=True):
        rows.append(
            {
                "mci_mean": float(grp[x_col].mean()),
                "mci_min": float(grp[x_col].min()),
                "mci_max": float(grp[x_col].max()),
                "hci_mean": float(grp[y_col].mean()),
                "hci_std": float(grp[y_col].std()),
                "n": len(grp),
            }
        )
    return sorted(rows, key=lambda r: r["mci_mean"])


def permutation_test_correlation(
    df: pd.DataFrame,
    *,
    x_col: str = "morning_calm_index",
    y_col: str = "hold_night_calm_index",
    n_perm: int = 2000,
    seed: int = 42,
) -> dict[str, float]:
    sub = _valid_pairs(df, x_col, y_col)
    if len(sub) < 20:
        return {"observed_rho": float("nan"), "p_value": float("nan")}
    observed, _ = stats.spearmanr(sub[x_col], sub[y_col])
    rng = np.random.default_rng(seed)
    y = sub[y_col].to_numpy()
    count = 0
    for _ in range(n_perm):
        perm_y = rng.permutation(y)
        rho, _ = stats.spearmanr(sub[x_col], perm_y)
        if abs(rho) >= abs(observed):
            count += 1
    return {
        "observed_rho": float(observed),
        "p_value": float((count + 1) / (n_perm + 1)),
        "n_perm": n_perm,
    }


def verify_entry_monotonicity(
    daily: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    mci_col: str = "morning_calm_index",
    window: EntryWindow,
) -> dict[str, Any]:
    """Verify: higher MCI → earlier entry → lower realized hold extrusion (Spearman)."""
    from extrusion import drop_weekend_bars, range_extrusion, slice_bars
    from sessions import hold_from_entry_bounds_utc

    rows = []
    for _, row in daily.dropna(subset=[mci_col, "entry_time_nyc"]).iterrows():
        from datetime import date

        entry_day = date.fromisoformat(row["entry_date"])
        h0, h1 = hold_from_entry_bounds_utc(entry_day, row["entry_time_nyc"])
        hb = slice_bars(bars, pd.Timestamp(h0), pd.Timestamp(h1))
        hb = drop_weekend_bars(hb)
        hold_range = range_extrusion(hb)
        if np.isnan(hold_range):
            continue
        rows.append(
            {
                "mci": row[mci_col],
                "entry_minutes": row["entry_minutes_nyc"],
                "hold_range": hold_range,
            }
        )

    if len(rows) < 30:
        return {"status": "insufficient", "n": len(rows)}

    ev = pd.DataFrame(rows)
    rho_entry, _ = stats.spearmanr(ev["mci"], ev["entry_minutes"])
    rho_hold, _ = stats.spearmanr(ev["mci"], ev["hold_range"])
    # higher MCI → earlier entry (lower minutes) → negative rho for entry
    # higher MCI → lower hold range → negative rho for hold
    return {
        "status": "ok",
        "n": len(ev),
        "spearman_mci_vs_entry_minutes": float(rho_entry),
        "spearman_mci_vs_hold_range": float(rho_hold),
        "entry_monotone_decreasing": rho_entry < 0,
        "hold_monotone_decreasing": rho_hold < 0,
        "mean_hold_range_calm_half": float(
            ev.loc[ev["mci"] >= ev["mci"].median(), "hold_range"].mean()
        ),
        "mean_hold_range_active_half": float(
            ev.loc[ev["mci"] < ev["mci"].median(), "hold_range"].mean()
        ),
    }


def run_phase3_verification(
    daily: pd.DataFrame,
    bars: pd.DataFrame,
    cfg: dict,
) -> dict[str, Any]:
    """Full Phase 3 continuous calm + entry verification battery."""
    ce = cfg.get("continuous_entry", {})
    window = EntryWindow(
        earliest=parse_hhmm(ce.get("earliest_nyc", "12:00")),
        latest=parse_hhmm(ce.get("latest_nyc", "16:00")),
        step_minutes=int(ce.get("step_minutes", 15)),
    )
    vcfg = cfg.get("phase3_verification", {})

    daily = add_entry_schedule(daily, window=window)
    full_model = fit_predictor(daily)
    oos = evaluate_oos(
        daily,
        min_train=int(vcfg.get("min_train_days", 80)),
        test_size=int(vcfg.get("test_fold_days", 40)),
    )
    cal = calibration_bins(daily, n_bins=int(vcfg.get("calibration_bins", 10)))
    perm = permutation_test_correlation(daily, n_perm=int(vcfg.get("permutation_n", 2000)))
    mono = verify_entry_monotonicity(daily, bars, window=window)

    gates = cfg.get("phase3_gates", {})
    passed = (
        full_model.get("spearman_rho", 0) >= gates.get("min_spearman", 0.25)
        and perm.get("p_value", 1) < gates.get("max_perm_p", 0.05)
        and (oos.get("mean_oos_spearman_pred") or 0) >= gates.get("min_oos_spearman", 0.15)
        and mono.get("entry_monotone_decreasing", False)
    )

    return {
        "predictor": {k: v for k, v in full_model.items() if not k.startswith("_")},
        "walk_forward_oos": oos,
        "calibration": cal,
        "permutation_test": perm,
        "entry_monotonicity": mono,
        "entry_window": {
            "earliest": ce.get("earliest_nyc", "12:00"),
            "latest": ce.get("latest_nyc", "16:00"),
            "step_minutes": window.step_minutes,
        },
        "gates_passed": passed,
        "n_days": len(daily.dropna(subset=["morning_calm_index", "hold_night_calm_index"])),
    }
