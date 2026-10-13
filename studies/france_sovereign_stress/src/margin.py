"""Initial-margin schedule for the FOAT/FGBL integer ladder.

Uses per-contract overnight initial margin from the broker/exchange (IBKR Europe
risk-based / Eurex Prisma). Figures are an *additive ceiling*: short FOAT and
long FGBL in the same account may get a small portfolio credit, so live margin
can be a little lower. There is no listed OAT–Bund inter-product spread on Eurex,
so the book is two legs, not a calendar.

Risk budget (€ at risk to the stop) and initial margin (cash locked by the
clearing house) are different quantities. Margin scales with contracts; the
stop scales with euros per basis point until the contract cap binds.
"""

from __future__ import annotations

from typing import Any

from src.calibrate import FutCalib
from src.rules import straight_line_spread_ladder


def entry_contracts(budget: float, fc: FutCalib, *, stop_bp: float = 40.0) -> tuple[int, int]:
    """Whole FOAT / FGBL at entry: equity ÷ stop, rounded per leg."""
    u = float(budget) / stop_bp
    foat = max(1, int(round(u / fc.eur_per_bp["FOAT"])))
    fgbl = max(1, int(round(u / fc.eur_per_bp["FGBL"])))
    return foat, fgbl


def margin_im(foat_n: int, fgbl_n: int, *, im_foat: float, im_fgbl: float) -> float:
    """Additive initial margin (€) for a short-FOAT / long-FGBL book."""
    return foat_n * im_foat + fgbl_n * im_fgbl


def ladder_with_margin(
    *,
    s0: float,
    fc: FutCalib,
    budget: float,
    im_foat: float,
    im_fgbl: float,
    stop_bp: float = 40.0,
    add_every_bp: float = 20.0,
    foat_cap: int = 20,
    fgbl_cap: int = 18,
    levels: list[float] | None = None,
) -> dict[str, Any]:
    """Straight-line integer ladder plus additive IM at each step."""
    levels = levels or [240.0, 300.0, 340.0, 400.0]
    entry_f, entry_g = entry_contracts(budget, fc, stop_bp=stop_bp)
    raw = straight_line_spread_ladder(
        s0=s0,
        eur_foat=fc.eur_per_bp["FOAT"],
        eur_fgbl=fc.eur_per_bp["FGBL"],
        levels=levels,
        budget=budget,
        stop_bp=stop_bp,
        add_every_bp=add_every_bp,
        foat_cap=foat_cap,
        fgbl_cap=fgbl_cap,
        entry_foat=entry_f,
        entry_fgbl=entry_g,
    )
    rows = []
    for r in raw["rows"]:
        im = margin_im(r["foat"], r["fgbl"], im_foat=im_foat, im_fgbl=im_fgbl)
        ebp = r["foat"] * fc.eur_per_bp["FOAT"]
        rows.append(
            {
                **r,
                "equity": round(float(r["equity"]), 1),
                "spread_bp": round(float(r["spread_bp"]), 1),
                "delta_bp": round(float(r["delta_bp"]), 1),
                "im_eur": round(im, 0),
                "eur_per_bp": round(ebp, 1),
            }
        )
    cap = next((r for r in rows if r["foat"] >= foat_cap), rows[-1])
    return {
        "budget": budget,
        "entry_foat": entry_f,
        "entry_fgbl": entry_g,
        "entry_im_eur": rows[0]["im_eur"],
        "cap_im_eur": cap["im_eur"],
        "cap_spread_bp": cap["spread_bp"],
        "cap_foat": foat_cap,
        "cap_fgbl": fgbl_cap,
        "im_foat_eur": im_foat,
        "im_fgbl_eur": im_fgbl,
        "rows": rows,
        "finals": {str(k): round(v, 1) for k, v in raw["finals"].items()},
    }


def margin_report(
    *,
    s0: float,
    fc: FutCalib,
    budgets: list[float],
    im_foat: float,
    im_fgbl: float,
    asof: str,
    source: str,
    stop_bp: float = 40.0,
    foat_cap: int = 20,
    fgbl_cap: int = 18,
) -> dict[str, Any]:
    """Margin schedules for one or more risk budgets (e.g. 10k / 15k / 20k)."""
    by_budget = {
        str(int(b)): ladder_with_margin(
            s0=s0,
            fc=fc,
            budget=float(b),
            im_foat=im_foat,
            im_fgbl=im_fgbl,
            stop_bp=stop_bp,
            foat_cap=foat_cap,
            fgbl_cap=fgbl_cap,
        )
        for b in budgets
    }
    return {
        "asof": asof,
        "source": source,
        "method": "additive_ceiling",
        "note": (
            "Overnight initial margin per contract from IBKR Europe (Eurex Prisma). "
            "Additive short FOAT + long FGBL; live portfolio credit may reduce the total slightly. "
            "Not a calendar spread: Eurex has no listed OAT–Bund IPS, so the legs are separate orders."
        ),
        "im_foat_eur": im_foat,
        "im_fgbl_eur": im_fgbl,
        "stop_bp": stop_bp,
        "foat_cap": foat_cap,
        "fgbl_cap": fgbl_cap,
        "budgets": by_budget,
    }


def margin_from_config(cfg: dict, *, s0: float, fc: FutCalib) -> dict[str, Any]:
    m = cfg.get("margin") or {}
    im = m.get("initial_eur") or {}
    budgets = m.get("budget_scenarios_eur") or [cfg["budget_eur"]]
    rules = cfg.get("rules") or {}
    return margin_report(
        s0=s0,
        fc=fc,
        budgets=[float(b) for b in budgets],
        im_foat=float(im.get("FOAT", 3247)),
        im_fgbl=float(im.get("FGBL", 2363)),
        asof=str(m.get("asof", "")),
        source=str(m.get("source", "IBKR Europe overnight initial")),
        stop_bp=float((rules.get("recommended") or {}).get("stop_bp", 40)),
        foat_cap=int(rules.get("spread_cap_foat", 20)),
        fgbl_cap=int(m.get("fgbl_cap", 18)),
    )
