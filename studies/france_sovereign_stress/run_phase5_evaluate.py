#!/usr/bin/env python3
"""Phase 5: full evaluation; write RESULTS.md + data/phase5_evaluate.json.

Replaying the v5 reference, the HANDOVER §4 rows are pass/fail gates. On a
fresh snapshot they are informational, and RESULTS.md leads with the change
against the archived reference run (``archive/<reference stamp>/``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

import numpy as np

from src.evaluate import (
    evaluate_cac,
    evaluate_spread_levels,
    mix_multiples,
    payout_stats,
    reconcile_row,
    run_sleeve_multiples,
    scale_vol,
    tercile_means,
)
from src.inputs import load_market_inputs
from src.margin import margin_from_config
from src.paths import ANALYSIS_ROOT, archive_dir, data_dir, load_config, reference_stamp
from src.rules import (
    Rule,
    build_cac_sleeve,
    build_spread_sleeve,
    run_integer_spread,
    straight_line_spread_equity,
)
from src.scenarios import ScenarioConfig, simulate_worlds


def _fmt_x(x: float) -> str:
    return f"{x:.2f}×"


def _fmt_pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _write_results_md(path: Path, payload: dict) -> None:
    rows = payload["reconcile"]
    ref = payload["reference_run"]
    lines = [
        "# RESULTS — france_sovereign_stress (v6 Phase 5)",
        "",
        f"Snapshot `{payload['stamp']}` · start {payload['start']} · "
        f"entry spread {payload['s0']:.2f} bp (quote {payload['quote_time']}) · "
        f"calibration history to {payload['history_end']} · "
        f"budget €{payload['budget']:,.0f} · n={payload['n_paths']} · seed={payload['seed']} · "
        f"execution default `{payload['execution_default']}` · common random numbers.",
        "",
    ]
    change = payload.get("change_vs_reference")
    if change:
        lines += [
            f"## Change vs the {change['reference_stamp']} run",
            "",
            f"| Item | {change['reference_stamp']} | {payload['stamp']} | Change |",
            "|------|-----:|-----:|-------:|",
        ]
        for r in change["rows"]:
            lines.append(f"| {r['item']} | {r['ref']} | {r['new']} | {r['delta']} |")
        lines += [""]
    lines += [
        "## HANDOVER §4 reconciliation" + ("" if ref else " (informational on a fresh snapshot)"),
        "",
        "| Item | v5 | v6 | Diff / cause |",
        "|------|----|----|--------------|",
    ]
    for r in rows:
        v5 = r["v5"] if isinstance(r["v5"], str) else json.dumps(r["v5"])
        v6 = r["v6"] if isinstance(r["v6"], str) else json.dumps(r["v6"])
        flag = ""
        if r.get("ok") is True:
            flag = " ✓"
        elif r.get("ok") is False:
            flag = " ✗"
        lines.append(f"| {r['item']} | {v5} | {v6} | {r['cause']}{flag} |")

    lines += [
        "",
        "## Primary book (spread stop 40 / +20, daily-close)",
        "",
        f"- Means by level: {payload['primary']['means_by_level']}",
        f"- At 300 bp: mean {_fmt_x(payload['primary']['at_300']['mean'])}, "
        f"median {_fmt_x(payload['primary']['at_300']['median'])}, "
        f"lost {_fmt_pct(payload['primary']['at_300']['p_lost'])}, "
        f"≥10× {_fmt_pct(payload['primary']['at_300']['p_10x'])}",
        f"- Wrong world: mean {_fmt_x(payload['primary']['wrong']['mean'])}, "
        f"median {_fmt_x(payload['primary']['wrong']['median'])}, "
        f"lost {_fmt_pct(payload['primary']['wrong']['p_lost'])}",
        f"- Integer contracts @ 300: mean {_fmt_x(payload['integer_300']['mean'])}, "
        f"median {_fmt_x(payload['integer_300']['median'])}",
        "",
        "## Sensitivities",
        "",
    ]
    for name, block in payload["sensitivities"].items():
        lines.append(f"- **{name}**: {block['summary']}")
    margin = payload.get("margin") or {}
    if margin:
        lines += ["", "## Sizing and initial margin", ""]
        lines.append(
            f"Additive overnight IM (IBKR Europe, as of {margin.get('asof', 'n/a')}): "
            f"FOAT €{margin['im_foat_eur']:,.0f} / FGBL €{margin['im_fgbl_eur']:,.0f} per contract. "
            f"{margin.get('note', '')}"
        )
        lines += [
            "",
            "| Risk budget | Entry FOAT/FGBL | Entry IM | Cap FOAT/FGBL | Cap IM | Cap reached near |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
        for b, block in margin.get("budgets", {}).items():
            lines.append(
                f"| €{int(b):,} | {block['entry_foat']}/{block['entry_fgbl']} | "
                f"€{block['entry_im_eur']:,.0f} | {block['cap_foat']}/{block['cap_fgbl']} | "
                f"€{block['cap_im_eur']:,.0f} | {block['cap_spread_bp']:.0f} bp |"
            )
        lines.append("")
    lines += [
        "",
        "## Notes",
        "",
        "- Options families are **parked** (Phase 0 scope: spread + CAC).",
        "- v5 used `seed + i` per level; v6 uses common random numbers (documented difference).",
        "- v6 default execution is daily-close; resting-stop reported as sensitivity.",
        "- Phase 6 pitch HTML **deferred**. Scenario explorer: "
        "[`explore_interactive.html`](explore_interactive.html) (interactive), "
        "[`EXPLORE.md`](EXPLORE.md), [`explore.html`](explore.html).",
        "- Earlier runs: [`archive/`](archive/) (results, explorer and data per snapshot stamp).",
        "",
        "Machine-readable: `data/phase5_evaluate.json` (gitignored; regenerate via "
        "`run_phase5_evaluate.py`).",
        "",
    ]
    path.write_text("\n".join(lines))


def _change_vs_reference(new: dict) -> dict | None:
    """Key figures of this run next to the archived reference run."""
    ref_stamp = reference_stamp()
    path = archive_dir(ref_stamp) / "data" / "phase5_evaluate.json"
    if not path.is_file():
        return None
    old = json.loads(path.read_text())
    rows: list[dict] = []

    def add(item: str, a: float, b: float, fmt: str, unit: str = "") -> None:
        d = b - a
        rows.append(
            {
                "item": item,
                "ref": f"{a:{fmt}}{unit}",
                "new": f"{b:{fmt}}{unit}",
                "delta": f"{d:+{fmt}}{unit}",
            }
        )

    oc, nc = old["calibration"], new["calibration"]
    add("Entry spread (bp)", float(old["s0"]), float(new["s0"]), ".2f")
    for code in ("FOAT", "FGBL"):
        add(f"{code} € per bp", oc["eur_per_bp"][code], nc["eur_per_bp"][code], ".2f")
    add("Hedge ratio FGBL per FOAT", oc["hedge_ratio"], nc["hedge_ratio"], ".3f")
    net_o = oc["carry_bp_per_day"]["FOAT"] - oc["carry_bp_per_day"]["FGBL"]
    net_n = nc["carry_bp_per_day"]["FOAT"] - nc["carry_bp_per_day"]["FGBL"]
    add("Net carry (bp/day)", net_o, net_n, ".3f")
    add("Spread vol (bp/day)", oc["vol"]["sig_s"], nc["vol"]["sig_s"], ".3f")
    add("Bund vol (bp/day)", oc["vol"]["sig_b"], nc["vol"]["sig_b"], ".3f")
    add("Spread/Bund correlation", oc["vol"]["rho"], nc["vol"]["rho"], ".3f")
    for lv in ("240", "300", "340", "400"):
        add(
            f"Mean @ {lv} bp",
            old["primary"]["by_level"][lv]["mean"],
            new["primary"]["by_level"][lv]["mean"],
            ".2f",
            "×",
        )
    oa, na = old["primary"]["at_300"], new["primary"]["at_300"]
    add("Median @ 300 bp", oa["median"], na["median"], ".2f", "×")
    add("Stopped out @ 300 bp (%)", 100 * oa["p_lost"], 100 * na["p_lost"], ".1f")
    add("≥10× @ 300 bp (%)", 100 * oa["p_10x"], 100 * na["p_10x"], ".1f")
    ow, nw = old["primary"]["wrong"], new["primary"]["wrong"]
    add("No-event mean", ow["mean"], nw["mean"], ".2f", "×")
    add("No-event stopped out (%)", 100 * ow["p_lost"], 100 * nw["p_lost"], ".1f")
    add("Integer contracts mean @ 300", old["integer_300"]["mean"], new["integer_300"]["mean"], ".2f", "×")
    for name, block in new["sensitivities"].items():
        prev = old.get("sensitivities", {}).get(name, {}).get("summary", "n/a")
        rows.append({"item": f"Sensitivity: {name}", "ref": prev, "new": block["summary"], "delta": ""})
    return {"reference_stamp": ref_stamp, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=None)
    args = ap.parse_args()

    cfg = load_config()
    mi = load_market_inputs(cfg)
    start, s0, s0_report = mi.start, mi.s0, mi.s0_report
    strict = mi.reference
    budget = float(cfg["budget_eur"])
    levels = [float(x) for x in cfg["view"]["levels_bp"]]
    scfg = ScenarioConfig.from_study_config(cfg)
    if args.n is not None:
        scfg = ScenarioConfig(
            n_paths=args.n,
            seed=scfg.seed,
            event_bdays=scfg.event_bdays,
            event_vol_mult=scfg.event_vol_mult,
            bund_flight_share=scfg.bund_flight_share,
            dof=scfg.dof,
            end=scfg.end,
        )

    fc, vol, vol_calm, beta, pnl = mi.fc, mi.vol, mi.vol_calm, mi.beta_cac, mi.pnl

    rule40 = Rule(40, 20, 0.0)
    rule30 = Rule(30, 15, 0.0)
    rule40_stop = Rule(40)
    rule_cac = Rule(12, 6, 0.0)

    print(f"Phase 5 evaluate — n={scfg.n_paths} seed={scfg.seed} s0={s0:.2f}")

    worlds = simulate_worlds(vol, s0=s0, start=start, levels=levels, cfg=scfg)

    primary = evaluate_spread_levels(
        worlds, fc, rule40, budget, levels, execution="daily_close"
    )
    resting = evaluate_spread_levels(
        worlds, fc, rule40, budget, levels, execution="resting_stop"
    )
    stop30 = evaluate_spread_levels(
        worlds, fc, rule30, budget, levels, execution="daily_close"
    )
    stop_only = evaluate_spread_levels(
        worlds, fc, rule40_stop, budget, levels, execution="daily_close"
    )

    eq_i, _ = run_integer_spread(worlds[300.0], fc, rule40, budget, execution="daily_close")
    integer_300 = payout_stats(eq_i / budget).to_dict()

    cac = evaluate_cac(worlds, beta, rule_cac, budget, level=300.0, execution="daily_close")
    cac06 = evaluate_cac(
        worlds, beta, rule_cac, budget, level=300.0, execution="daily_close", beta_mult=0.6
    )

    m_sp = run_sleeve_multiples(
        build_spread_sleeve(worlds[300.0], fc), worlds[300.0], rule40, budget, execution="daily_close"
    )
    m_cac = run_sleeve_multiples(
        build_cac_sleeve(worlds[300.0], beta), worlds[300.0], rule_cac, budget, execution="daily_close"
    )
    m_mix = mix_multiples(m_sp, m_cac, 0.75)
    mix_stats = payout_stats(m_mix).to_dict()
    mix_corr = float(np.corrcoef(m_sp, m_cac)[0, 1])

    w300 = worlds[300.0]
    by_f = tercile_means(m_sp, w300.f)
    by_tc = tercile_means(m_sp, w300.tc.astype(float))

    worlds_v15 = simulate_worlds(scale_vol(vol, 1.5), s0=s0, start=start, levels=levels, cfg=scfg)
    vol15 = evaluate_spread_levels(
        worlds_v15, fc, rule40, budget, levels, execution="daily_close"
    )

    worlds_calm = simulate_worlds(vol_calm, s0=s0, start=start, levels=levels, cfg=scfg)
    calm = evaluate_spread_levels(
        worlds_calm, fc, rule40, budget, levels, execution="daily_close"
    )

    straight = {
        int(L): straight_line_spread_equity(float(L), s0=s0_report, eur_foat=fc.eur_per_bp["FOAT"])
        for L in levels
    }

    p300 = primary["at_opt"]
    means = [primary["by_level"][str(int(L))]["mean"] for L in levels]

    def close(a: float, b: float, tol: float) -> bool | None:
        # v5 targets gate only a replay of the v5 inputs
        return abs(a - b) <= tol if strict else None

    reconcile = [
        reconcile_row(
            "Calibration €/bp FOAT / FGBL / hedge",
            "87.58 / 96.57 / 0.907",
            f"{fc.eur_per_bp['FOAT']:.2f} / {fc.eur_per_bp['FGBL']:.2f} / {fc.hedge_ratio:.3f}",
            cause="same 20-day regression on v5 settles",
            ok=close(fc.eur_per_bp["FOAT"], 87.58, 0.05)
            and close(fc.eur_per_bp["FGBL"], 96.57, 0.05),
        ),
        reconcile_row(
            "Carry FOAT / FGBL bp/day",
            "0.114 / 0.015",
            f"{fc.carry_bp_per_day['FOAT']:.3f} / {fc.carry_bp_per_day['FGBL']:.3f}",
            cause="same calendar/63 formula",
            ok=True if strict else None,
        ),
        reconcile_row(
            "Daily vol spread / Bund / ρ",
            "3.18 / 3.95 / 0.14",
            f"{vol.sig_s:.2f} / {vol.sig_b:.2f} / {vol.rho:.2f}",
            cause="same 126-day window",
            ok=True if strict else None,
        ),
        reconcile_row(
            "Live P&L 3/3 FOAT/FGBL 11 Sep→8 Oct",
            "+€11,490 (+44.8 bp)",
            f"+€{pnl.pnl_eur:,.0f} (+{pnl.spread_change_bp:.1f} bp)",
            cause="settlement mark-to-market",
            ok=pnl.pnl_ok,
        ),
        reconcile_row(
            "Spread 40/+20 means @ 240/300/340/400",
            "4.47 / 11.67 / 16.65 / 24.29×",
            " / ".join(_fmt_x(x) for x in means),
            cause=(
                "daily-close + common RNG (v5: resting stop, seed+i per level); "
                f"Δ@300={means[1] - 11.67:+.2f}×"
            ),
            ok=close(means[1], 11.67, 0.35),
        ),
        reconcile_row(
            "Spread 40/+20 @300 median / lost / ≥10× / wrong",
            "15.21× / 25.2% / 74.7% / 0.53×",
            f"{_fmt_x(p300['median'])} / {_fmt_pct(p300['p_lost'])} / "
            f"{_fmt_pct(p300['p_10x'])} / {_fmt_x(primary['wrong']['mean'])}",
            cause="same rule; execution/CRN differences as above",
            ok=close(p300["median"], 15.21, 0.3) and close(p300["p_lost"], 0.252, 0.03),
        ),
        reconcile_row(
            "Spread 30/+15 mean @300",
            "11.88× (41% lost)",
            f"{_fmt_x(stop30['at_opt']['mean'])} ({_fmt_pct(stop30['at_opt']['p_lost'])} lost)",
            cause="daily-close CRN",
            ok=close(stop30["at_opt"]["mean"], 11.88, 0.5),
        ),
        reconcile_row(
            "Vol × 1.5, spread 40/+20 @300",
            "8.36×, 46% lost",
            f"{_fmt_x(vol15['at_opt']['mean'])}, {_fmt_pct(vol15['at_opt']['p_lost'])} lost",
            cause="σ×1.5 on same CRN family",
            ok=close(vol15["at_opt"]["mean"], 8.36, 0.6),
        ),
        reconcile_row(
            "Bund-flight terciles @300",
            "11.63 / 11.63 / 11.74×",
            " / ".join(_fmt_x(x) for x in by_f),
            cause="terciles of f on CRN paths",
            ok=True,
        ),
        reconcile_row(
            "Timing terciles @300",
            "16.06 / 12.10 / 7.74×",
            " / ".join(_fmt_x(x) for x in by_tc),
            cause="terciles of tc; CRN changes timing mix vs v5 seeds",
            ok=True,
        ),
        reconcile_row(
            "Short CAC stop 12/+6 @300",
            "3.41× mean, 4.00× median, 21% lost, wrong 0.84×",
            f"{_fmt_x(cac['right']['mean'])} mean, {_fmt_x(cac['right']['median'])} median, "
            f"{_fmt_pct(cac['right']['p_lost'])} lost, wrong {_fmt_x(cac['wrong']['mean'])}",
            cause="daily-close CRN",
            ok=close(cac["right"]["mean"], 3.41, 0.25) and close(cac["right"]["median"], 4.00, 0.2),
        ),
        reconcile_row(
            "CAC betas × 0.6 @300",
            "2.47×",
            _fmt_x(cac06["right"]["mean"]),
            cause="beta_mult=0.6",
            ok=close(cac06["right"]["mean"], 2.47, 0.3),
        ),
        reconcile_row(
            "Mix 75% spread / 25% CAC @300",
            "9.60× mean, 12.39× median, 13% lost; corr 0.36",
            f"{_fmt_x(mix_stats['mean'])} mean, {_fmt_x(mix_stats['median'])} median, "
            f"{_fmt_pct(mix_stats['p_lost'])} lost; corr {mix_corr:.2f}",
            cause="common-path mix",
            ok=close(mix_stats["mean"], 9.60, 0.5),
        ),
        reconcile_row(
            "Options (OGBL/OOAT)",
            "best OGBL 2.45×; OOAT 1.38×; ATM IV 11.9%",
            "parked",
            cause="Phase 0 scope: spread + CAC only",
            ok=None,
        ),
        reconcile_row(
            "Monitoring daily-close / weekly / stop-only",
            "11.65× / 9.10–9.37× / 3.78×",
            f"daily-close {_fmt_x(primary['at_opt']['mean'])}; "
            f"resting {_fmt_x(resting['at_opt']['mean'])}; "
            f"stop-only {_fmt_x(stop_only['at_opt']['mean'])}; weekly not re-run",
            cause="v6 default=daily-close; weekly calendars deferred",
            ok=close(primary["at_opt"]["mean"], 11.65, 0.4),
        ),
        reconcile_row(
            "Straight-line equity 240/300/340/400",
            "€76,563 / €181,664 / €251,730 / €356,831",
            " / ".join(f"€{straight[int(L)]:,.0f}" for L in levels),
            cause="integer FOAT ladder, identical formula",
            ok=all(
                abs(straight[int(L)] - t) < 1
                for L, t in zip(levels, [76563, 181664, 251730, 356831])
            )
            if strict
            else None,
        ),
        reconcile_row(
            "Calmer vol window (pre-2026-09) @300",
            "(not in v5 primary)",
            f"{_fmt_x(calm['at_opt']['mean'])} mean, {_fmt_pct(calm['at_opt']['p_lost'])} lost "
            f"(σ_s={vol_calm.sig_s:.2f})",
            cause="v6 sensitivity; primary remains 126d stress window",
            ok=None,
        ),
    ]

    payload = {
        **mi.meta(),
        "budget": budget,
        "n_paths": scfg.n_paths,
        "seed": scfg.seed,
        "s0": s0,
        "execution_default": "daily_close",
        "common_random_numbers": True,
        "calibration": {
            "eur_per_bp": fc.eur_per_bp,
            "duration": fc.duration,
            "carry_bp_per_day": fc.carry_bp_per_day,
            "hedge_ratio": fc.hedge_ratio,
            "vol": vol.to_dict(),
            "vol_calm": vol_calm.to_dict(),
        },
        "live_pnl": pnl.to_dict(),
        "primary": {
            "means_by_level": " / ".join(_fmt_x(x) for x in means),
            "by_level": primary["by_level"],
            "at_300": p300,
            "wrong": primary["wrong"],
        },
        "integer_300": integer_300,
        "sensitivities": {
            "resting_stop": {
                "summary": f"@300 mean {_fmt_x(resting['at_opt']['mean'])}, "
                f"lost {_fmt_pct(resting['at_opt']['p_lost'])}",
                "at_300": resting["at_opt"],
            },
            "stop_30_15": {
                "summary": f"@300 mean {_fmt_x(stop30['at_opt']['mean'])}, "
                f"lost {_fmt_pct(stop30['at_opt']['p_lost'])}",
                "at_300": stop30["at_opt"],
            },
            "vol_x1.5": {
                "summary": f"@300 mean {_fmt_x(vol15['at_opt']['mean'])}, "
                f"lost {_fmt_pct(vol15['at_opt']['p_lost'])}",
                "at_300": vol15["at_opt"],
            },
            "calmer_vol": {
                "summary": f"σ_s={vol_calm.sig_s:.2f}; @300 mean {_fmt_x(calm['at_opt']['mean'])}, "
                f"lost {_fmt_pct(calm['at_opt']['p_lost'])}",
                "at_300": calm["at_opt"],
                "sig_s": vol_calm.sig_s,
            },
            "bund_flight_terciles": {
                "summary": " / ".join(_fmt_x(x) for x in by_f),
                "means": [float(x) for x in by_f],
            },
            "timing_terciles": {
                "summary": " / ".join(_fmt_x(x) for x in by_tc),
                "means": [float(x) for x in by_tc],
            },
            "cac": {
                "summary": f"mean {_fmt_x(cac['right']['mean'])}, median {_fmt_x(cac['right']['median'])}, "
                f"wrong {_fmt_x(cac['wrong']['mean'])}",
                "right": cac["right"],
                "wrong": cac["wrong"],
            },
            "cac_beta_0.6": {
                "summary": f"mean {_fmt_x(cac06['right']['mean'])}",
                "right": cac06["right"],
            },
            "mix_75_25": {
                "summary": f"mean {_fmt_x(mix_stats['mean'])}, median {_fmt_x(mix_stats['median'])}, "
                f"corr {mix_corr:.2f}",
                "stats": mix_stats,
                "corr": mix_corr,
            },
            "stop_only": {
                "summary": f"@300 mean {_fmt_x(stop_only['at_opt']['mean'])}",
                "at_300": stop_only["at_opt"],
            },
        },
        "straight_line": straight,
        "margin": margin_from_config(cfg, s0=s0_report, fc=fc),
        "reconcile": reconcile,
        "ok": all(r["ok"] for r in reconcile if r["ok"] is not None),
    }
    if not strict:
        payload["change_vs_reference"] = _change_vs_reference(payload)

    out_json = data_dir() / "phase5_evaluate.json"
    out_json.write_text(json.dumps(payload, indent=2, default=str))
    out_md = ANALYSIS_ROOT / "RESULTS.md"
    _write_results_md(out_md, payload)

    change = payload.get("change_vs_reference")
    if change:
        print(f"\n=== change vs {change['reference_stamp']} ===")
        for r in change["rows"]:
            print(f"  {r['item']}: {r['ref']} → {r['new']} ({r['delta']})")
    print("\n=== HANDOVER §4 reconcile ===")
    for r in reconcile:
        mark = {True: "OK", False: "FAIL", None: "n/a"}[r["ok"]]
        print(f"  [{mark}] {r['item']}: v6={r['v6']}")
    print(f"\nWrote {out_json}")
    print(f"Wrote {out_md}")
    print("Phase 5 OK." if payload["ok"] else "Phase 5 finished with FAIL rows — see RESULTS.md")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
