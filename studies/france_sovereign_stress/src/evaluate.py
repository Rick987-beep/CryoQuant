"""Phase 5 evaluation helpers: payout stats, mixes, sensitivities, reconcile rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.calibrate import FutCalib, StockBeta, VolCalib
from src.rules import Rule, Sleeve, build_cac_sleeve, build_spread_sleeve, run_continuous
from src.scenarios import World


@dataclass(frozen=True)
class PayoutStats:
    mean: float
    median: float
    p_lost: float
    p_5x: float
    p_10x: float
    p95: float

    def to_dict(self) -> dict[str, float]:
        return {
            "mean": self.mean,
            "median": self.median,
            "p_lost": self.p_lost,
            "p_5x": self.p_5x,
            "p_10x": self.p_10x,
            "p95": self.p95,
        }


def payout_stats(multiples: np.ndarray) -> PayoutStats:
    m = np.asarray(multiples, dtype=float)
    return PayoutStats(
        mean=float(m.mean()),
        median=float(np.median(m)),
        p_lost=float((m <= 0.1).mean()),
        p_5x=float((m >= 5.0).mean()),
        p_10x=float((m >= 10.0).mean()),
        p95=float(np.percentile(m, 95)),
    )


def run_sleeve_multiples(
    sleeve: Sleeve,
    world: World,
    rule: Rule,
    budget: float,
    *,
    execution: str = "daily_close",
) -> np.ndarray:
    eq, _ = run_continuous(sleeve, world, rule, budget, execution=execution)  # type: ignore[arg-type]
    return eq / budget


def evaluate_spread_levels(
    worlds: dict[float | None, World],
    fc: FutCalib,
    rule: Rule,
    budget: float,
    levels: list[float],
    *,
    execution: str = "daily_close",
) -> dict[str, Any]:
    by_level: dict[str, dict[str, float]] = {}
    for lv in levels:
        sleeve = build_spread_sleeve(worlds[lv], fc)
        st = payout_stats(run_sleeve_multiples(sleeve, worlds[lv], rule, budget, execution=execution))
        by_level[str(int(lv))] = st.to_dict()
    wrong = payout_stats(
        run_sleeve_multiples(
            build_spread_sleeve(worlds[None], fc), worlds[None], rule, budget, execution=execution
        )
    )
    opt = levels[1] if len(levels) > 1 else levels[0]
    # prefer 300 if present
    if 300.0 in levels:
        opt = 300.0
    return {
        "rule": rule.text,
        "execution": execution,
        "by_level": by_level,
        "wrong": wrong.to_dict(),
        "at_opt": by_level[str(int(opt))],
        "opt_level": opt,
    }


def evaluate_cac(
    worlds: dict[float | None, World],
    beta: StockBeta,
    rule: Rule,
    budget: float,
    *,
    level: float = 300.0,
    execution: str = "daily_close",
    carry_pa: float = 0.01,
    beta_mult: float = 1.0,
) -> dict[str, Any]:
    b = StockBeta(
        beta_s=beta.beta_s * beta_mult,
        beta_b=beta.beta_b * beta_mult,
        idio=beta.idio,
        r2=beta.r2,
    )
    right = build_cac_sleeve(worlds[level], b, carry_pa=carry_pa)
    wrong_s = build_cac_sleeve(worlds[None], b, carry_pa=carry_pa)
    sr = payout_stats(run_sleeve_multiples(right, worlds[level], rule, budget, execution=execution))
    sw = payout_stats(run_sleeve_multiples(wrong_s, worlds[None], rule, budget, execution=execution))
    return {
        "rule": rule.text,
        "execution": execution,
        "beta_mult": beta_mult,
        "right": sr.to_dict(),
        "wrong": sw.to_dict(),
    }


def mix_multiples(a: np.ndarray, b: np.ndarray, weight_a: float) -> np.ndarray:
    return weight_a * a + (1.0 - weight_a) * b


def tercile_means(multiples: np.ndarray, key: np.ndarray) -> list[float]:
    """Mean multiple in low / mid / high terciles of ``key``."""
    q1, q2 = np.quantile(key, [1 / 3, 2 / 3])
    bands = [
        multiples[key <= q1],
        multiples[(key > q1) & (key <= q2)],
        multiples[key > q2],
    ]
    return [float(b.mean()) if len(b) else float("nan") for b in bands]


def calmer_vol(yields: pd.DataFrame, *, end_before: str = "2026-09-01", window: int = 126) -> VolCalib:
    """Trailing vol ending before the Sept–Oct 2026 stress window."""
    from src.calibrate import calibrate_vol

    y = yields.copy()
    y.index = pd.DatetimeIndex(y.index).tz_localize(None).normalize()
    cut = pd.Timestamp(end_before)
    y = y.loc[y.index < cut]
    return calibrate_vol(y, window=window)


def scale_vol(vol: VolCalib, mult: float) -> VolCalib:
    return VolCalib(
        sig_s=vol.sig_s * mult,
        sig_b=vol.sig_b * mult,
        rho=vol.rho,
        window=vol.window,
        n_obs=vol.n_obs,
    )


def reconcile_row(
    item: str,
    v5: Any,
    v6: Any,
    *,
    cause: str,
    ok: bool | None = None,
) -> dict[str, Any]:
    return {"item": item, "v5": v5, "v6": v6, "cause": cause, "ok": ok}
