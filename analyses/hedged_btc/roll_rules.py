"""Phase 2c — Calendar + ratchet + IV-gate roll decisions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from ._utils import expiry_dte, nearest_strike, pick_expiry_for_bucket
from .book import BookPosition, BookSpec, RollPolicy
from .pricing import list_expiries, pick_expiry_near_dte, spot_on_date


@dataclass
class RollDecision:
    roll_protection: bool = False
    roll_income: bool = False
    ratchet: bool = False
    iv_blocked: bool = False
    reason: str = ""


def atm_iv_pct(snap: pd.DataFrame, as_of: date, *, target_dte: int = 37) -> float | None:
    """ATM mark_iv (percent) for expiry nearest target_dte."""
    exp = pick_expiry_near_dte(snap, as_of, target_dte, tol=30)
    if exp is None:
        exps = list_expiries(snap, as_of)
        exp = pick_expiry_for_bucket(exps, as_of, "mid")
    if exp is None:
        return None
    spot = spot_on_date(as_of, snap)
    sub = snap[(snap["expiry"] == exp) & (snap["is_call"] == True)]
    if sub.empty:
        return None
    strike = nearest_strike(sub["strike"], spot)
    row = sub.loc[(sub["strike"] - strike).abs().idxmin()]
    iv = float(row["mark_iv"])
    return iv if 0 < iv < 200 else None


def ratchet_triggered(pos: BookPosition, spot: float, policy: RollPolicy) -> bool:
    if policy.ratchet_pct is None or pos.spot_at_open <= 0:
        return False
    return spot >= pos.spot_at_open * (1.0 + policy.ratchet_pct)


def _iv_blocks_roll(dte: int, atm_iv: float | None, policy: RollPolicy) -> bool:
    if not policy.defer_roll_if_iv_high:
        return False
    if policy.iv_ceiling_pct is None or atm_iv is None:
        return False
    if dte <= policy.critical_dte:
        return False
    return atm_iv > policy.iv_ceiling_pct


def evaluate_rolls(
    pos: BookPosition | None,
    as_of: date,
    snap: pd.DataFrame,
    spec: BookSpec,
    spot: float,
) -> RollDecision:
    """Decide whether to roll protection and/or income sleeves."""
    policy = spec.roll_policy or RollPolicy()

    if pos is None:
        return RollDecision(roll_protection=True, roll_income=bool(spec.income_legs), reason="init")

    prot_dte = expiry_dte(pos.protection_expiry, as_of)
    inc_dte = expiry_dte(pos.income_expiry, as_of) if pos.income_expiry else None
    atm_iv = atm_iv_pct(snap, as_of, target_dte=spec.protection_tenor_dte)

    ratchet = ratchet_triggered(pos, spot, policy)
    cal_prot = prot_dte <= spec.roll_min_dte
    cal_inc = (
        bool(spec.income_legs)
        and pos.income_expiry is not None
        and inc_dte is not None
        and inc_dte <= spec.income_roll_min_dte
    )

    iv_blocked = False
    roll_prot = cal_prot or ratchet
    if roll_prot and _iv_blocks_roll(prot_dte, atm_iv, policy):
        iv_blocked = True
        roll_prot = False

    reasons: list[str] = []
    if ratchet:
        reasons.append("ratchet")
    if cal_prot:
        reasons.append(f"prot_dte<={spec.roll_min_dte}")
    if cal_inc:
        reasons.append(f"inc_dte<={spec.income_roll_min_dte}")
    if iv_blocked:
        reasons.append("iv_gate")

    return RollDecision(
        roll_protection=roll_prot,
        roll_income=cal_inc,
        ratchet=ratchet,
        iv_blocked=iv_blocked,
        reason=",".join(reasons) or "hold",
    )


def pick_protection_expiry(snap: pd.DataFrame, as_of: date, spec: BookSpec) -> str | None:
    exp = pick_expiry_near_dte(snap, as_of, spec.protection_tenor_dte, tol=21)
    if exp is None:
        return None
    if expiry_dte(exp, as_of) <= spec.roll_min_dte:
        # Prefer a farther expiry if calendar pick lands inside roll window
        candidates = [
            e for e in list_expiries(snap, as_of)
            if expiry_dte(e, as_of) > spec.roll_min_dte
        ]
        if candidates:
            exp = min(candidates, key=lambda e: abs(expiry_dte(e, as_of) - spec.protection_tenor_dte))
    return exp


def pick_income_expiry(snap: pd.DataFrame, as_of: date, spec: BookSpec) -> str | None:
    tenor = spec.income_tenor_dte or 14
    return pick_expiry_near_dte(snap, as_of, tenor, tol=10)
