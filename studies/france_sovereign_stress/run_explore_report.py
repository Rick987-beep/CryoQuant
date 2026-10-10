#!/usr/bin/env python3
"""Build EXPLORE.md + reports/explore.html from the fine exit-level grid.

Regenerates ``data/exit_level_grid.json`` when missing (base fee × half-tick
only for speed; full fee grid optional via ``--full-costs``).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

import matplotlib.pyplot as plt
import numpy as np

from cryoquant.reporting.html_brand import escape_html, fig_to_b64, html_document, style_axes
from src.calibrate import calibrate_futures, calibrate_vol
from src.data.reference import load_eurex_settles, load_yields_daily
from src.evaluate import run_sleeve_multiples
from src.paths import data_dir, load_config, reports_dir
from src.rules import FUT_FEE, HALF_TICK, Rule, build_spread_sleeve
from src.scenarios import ScenarioConfig, simulate_worlds


def _ensure_grid(*, n: int, full_costs: bool) -> dict:
    out = data_dir() / "exit_level_grid.json"
    if out.exists() and not full_costs:
        return json.loads(out.read_text())

    cfg = load_config()
    stamp = cfg["reference"]["stamp"]
    budget = float(cfg["budget_eur"])
    levels = list(range(200, 401, 10))
    fees = [1.50, 2.35, 4.00] if full_costs else [2.35]
    half_ticks = [2.5, 5.0, 10.0] if full_costs else [5.0]
    scfg = ScenarioConfig.from_study_config(cfg)
    scfg = ScenarioConfig(
        n_paths=n,
        seed=scfg.seed,
        event_bdays=scfg.event_bdays,
        event_vol_mult=scfg.event_vol_mult,
        bund_flight_share=scfg.bund_flight_share,
        dof=scfg.dof,
        end=scfg.end,
    )
    start = date.fromisoformat(stamp.split("T", 1)[0])
    s0 = 138.0
    yields = load_yields_daily()
    settles = load_eurex_settles()
    fc = calibrate_futures(settles, yields)
    vol = calibrate_vol(yields, window=int(cfg["simulation"]["vol_window_bdays"]))
    rule = Rule(40, 20, 0.0)

    print(f"explore grid n={n} levels={len(levels)} fees={fees} half_ticks={half_ticks}")
    worlds = simulate_worlds(
        vol, s0=s0, start=start, levels=[float(L) for L in levels], cfg=scfg
    )
    grids: dict[str, dict] = {}
    for fee in fees:
        for ht in half_ticks:
            key = f"{fee:g}|{ht:g}"
            rows = []
            for L in levels:
                sleeve = build_spread_sleeve(
                    worlds[float(L)], fc, fee_per_side=fee, half_tick_eur=ht
                )
                m = run_sleeve_multiples(
                    sleeve, worlds[float(L)], rule, budget, execution="daily_close"
                )
                rows.append(
                    {
                        "level_bp": L,
                        "mean": round(float(m.mean()), 3),
                        "p10": round(float(np.percentile(m, 10)), 3),
                        "p25": round(float(np.percentile(m, 25)), 3),
                        "p50": round(float(np.percentile(m, 50)), 3),
                        "p75": round(float(np.percentile(m, 75)), 3),
                        "p90": round(float(np.percentile(m, 90)), 3),
                        "p_lost": round(float((m <= 0.1).mean()), 4),
                    }
                )
            grids[key] = {"fee_per_side": fee, "half_tick_eur": ht, "curve": rows}
            print(f"  {key} @300 mean={next(r['mean'] for r in rows if r['level_bp']==300)}")

    payload = {
        "meta": {
            "stamp": stamp,
            "s0": s0,
            "budget": budget,
            "n_paths": n,
            "seed": scfg.seed,
            "rule": rule.text,
            "execution": "daily_close",
            "grid": "200:400:10",
            "default_fee": FUT_FEE,
            "default_half_tick": HALF_TICK,
            "quantiles": [10, 25, 50, 75, 90],
        },
        "fee_options": [
            {"value": "1.5", "label": "€1.50 / side (cheap)"},
            {"value": "2.35", "label": "€2.35 / side (base · IBKR/Lynx proxy)"},
            {"value": "4", "label": "€4.00 / side (expensive)"},
        ],
        "half_tick_options": [
            {"value": "2.5", "label": "Quarter tick €2.50 / side"},
            {"value": "5", "label": "Half tick €5.00 / side (base)"},
            {"value": "10", "label": "Full tick €10.00 / side"},
        ],
        "grids": grids,
    }
    data_dir().mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    return payload


def _base_curve(payload: dict) -> list[dict]:
    meta = payload["meta"]
    key = f"{meta['default_fee']:g}|{meta['default_half_tick']:g}"
    if key not in payload["grids"]:
        key = next(iter(payload["grids"]))
    return payload["grids"][key]["curve"]


def _chart_png(curve: list[dict]) -> str:
    levels = [r["level_bp"] for r in curve]
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    ax.fill_between(
        levels,
        [r["p10"] for r in curve],
        [r["p90"] for r in curve],
        alpha=0.18,
        label="p10–p90",
    )
    ax.fill_between(
        levels,
        [r["p25"] for r in curve],
        [r["p75"] for r in curve],
        alpha=0.28,
        label="p25–p75",
    )
    ax.plot(levels, [r["mean"] for r in curve], lw=2.2, label="mean")
    ax.plot(levels, [r["p50"] for r in curve], lw=1.4, ls="--", label="median (p50)")
    style_axes(
        ax,
        title="Payout multiple vs right-world exit level (FOAT/FGBL, stop 40 / +20)",
        xlabel="Exit level (bp)",
        ylabel="Terminal equity (× budget)",
    )
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    ax.axvline(300, color="#8fa3bc", ls=":", lw=1)
    return fig_to_b64(fig)


def write_md(payload: dict, curve: list[dict], path: Path) -> None:
    meta = payload["meta"]
    r300 = next(r for r in curve if r["level_bp"] == 300)
    lines = [
        "# EXPLORE — france_sovereign_stress",
        "",
        f"Snapshot `{meta['stamp']}` · budget €{meta['budget']:,.0f} · "
        f"n={meta['n_paths']} · seed={meta['seed']} · "
        f"rule `{meta['rule']}` · execution `{meta['execution']}`.",
        "",
        "Static counterpart to the Cursor canvas explorer. Phase 6 pitch HTML is deferred.",
        "",
        "## Fine exit grid",
        "",
        f"Right-world exits **{meta['grid']}** bp. Default costs: "
        f"**€{meta['default_fee']}/side** fee + **€{meta['default_half_tick']}** half-tick "
        "(Lynx/IBKR-style proxy; Eurex exchange ~€0.27/contract on top in live trading).",
        "",
        f"At **300 bp**: mean **{r300['mean']:.2f}×**, median **{r300['p50']:.2f}×**, "
        f"p10 **{r300['p10']:.2f}×**, p90 **{r300['p90']:.2f}×**, "
        f"lost **{100 * r300['p_lost']:.1f}%**.",
        "",
        "| Exit bp | Mean | p10 | p25 | p50 | p75 | p90 | Lost |",
        "|--------:|-----:|----:|----:|----:|----:|----:|-----:|",
    ]
    for r in curve:
        if r["level_bp"] % 20 != 0:
            continue
        lines.append(
            f"| {r['level_bp']} | {r['mean']:.2f}× | {r['p10']:.2f}× | {r['p25']:.2f}× | "
            f"{r['p50']:.2f}× | {r['p75']:.2f}× | {r['p90']:.2f}× | {100 * r['p_lost']:.1f}% |"
        )
    lines += [
        "",
        "## Execution and costs (checked)",
        "",
        "- **Instruments:** short FOAT / long FGBL (DV01-neutral); optional short CAC.",
        "- **Fees:** €2.35/contract/side in sim ≈ Lynx €2.00 + Eurex A-account ~€0.27.",
        "- **Bid–ask:** half-tick (€5) per leg — matches a 1-tick book with aggressive fills "
        "in European hours. Markets closed weekends (Mon–Fri only).",
        "- **Execution:** `daily_close` baseline; 1 bp stop slip; quarterly rolls charged.",
        "",
        "## Artifacts",
        "",
        "- [`explore.html`](explore.html) — branded chart + table",
        "- `data/exit_level_grid.json` — machine-readable curves (gitignored)",
        "- [`RESULTS.md`](RESULTS.md) — Phase 5 v5 reconciliation",
        "",
        "Rebuild: `python studies/france_sovereign_stress/run_explore_report.py`",
        "",
    ]
    path.write_text("\n".join(lines))


def write_html(payload: dict, curve: list[dict], path: Path) -> None:
    meta = payload["meta"]
    r300 = next(r for r in curve if r["level_bp"] == 300)
    chart = _chart_png(curve)
    rows = "".join(
        f"<tr><td>{r['level_bp']}</td><td>{r['mean']:.2f}×</td><td>{r['p10']:.2f}×</td>"
        f"<td>{r['p25']:.2f}×</td><td>{r['p50']:.2f}×</td><td>{r['p75']:.2f}×</td>"
        f"<td>{r['p90']:.2f}×</td><td>{100 * r['p_lost']:.1f}%</td></tr>"
        for r in curve
        if r["level_bp"] % 20 == 0
    )
    body = f"""
<main class="doc">
  <header>
    <p class="eyebrow">CryoQuant · france_sovereign_stress</p>
    <h1>Scenario explorer</h1>
    <p class="lede">
      FOAT/FGBL spread sleeve · stop 40 / add +20 · daily-close ·
      fine right-world exit grid {escape_html(meta['grid'])} bp ·
      n={meta['n_paths']} · seed={meta['seed']} · snapshot {escape_html(meta['stamp'])}.
    </p>
  </header>

  <section>
    <h2>Headline @ 300 bp</h2>
    <div class="stats">
      <div><strong>{r300['mean']:.2f}×</strong><span>Mean</span></div>
      <div><strong>{r300['p50']:.2f}×</strong><span>Median</span></div>
      <div><strong>{r300['p90']:.2f}×</strong><span>p90</span></div>
      <div><strong>{100 * r300['p_lost']:.1f}%</strong><span>Lost (≤0.1×)</span></div>
    </div>
    <p class="muted">
      Costs: €{meta['default_fee']}/side fee + €{meta['default_half_tick']} half-tick bid–ask
      (both legs). p10 stays near the stop because ~25% of right-world paths are stopped out
      before the event completes.
    </p>
  </section>

  <section>
    <h2>Payout vs exit level</h2>
    <figure>
      <img src="data:image/png;base64,{chart}" alt="Mean and quantile payout vs exit level"/>
      <figcaption>
        Mean and cross-sectional quantiles of terminal equity / budget.
        Vertical guide at the 300 bp optimise level.
      </figcaption>
    </figure>
  </section>

  <section>
    <h2>Table (every 20 bp)</h2>
    <table>
      <thead>
        <tr><th>Exit bp</th><th>Mean</th><th>p10</th><th>p25</th><th>p50</th>
        <th>p75</th><th>p90</th><th>Lost</th></tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </section>

  <section>
    <h2>Notes</h2>
    <ul>
      <li>Research only — no orders.</li>
      <li>Eurex FOAT/FGBL trade Mon–Fri; no weekend book.</li>
      <li>Phase 5 full reconciliation: <code>RESULTS.md</code>.</li>
      <li>Rebuild: <code>python studies/france_sovereign_stress/run_explore_report.py</code>.</li>
    </ul>
  </section>
</main>
<style>
  .doc {{ max-width: 960px; margin: 0 auto; padding: 2rem 1.25rem 3rem; }}
  .eyebrow {{ letter-spacing: 0.08em; text-transform: uppercase; font-size: 0.75rem; opacity: 0.7; }}
  .lede {{ max-width: 42rem; opacity: 0.9; }}
  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin: 1rem 0; }}
  .stats div {{ padding: 0.85rem 1rem; border: 1px solid rgba(143,163,188,0.25); }}
  .stats strong {{ display: block; font-size: 1.4rem; }}
  .stats span {{ font-size: 0.8rem; opacity: 0.7; }}
  .muted {{ opacity: 0.75; font-size: 0.9rem; }}
  figure img {{ width: 100%; height: auto; }}
  figcaption {{ font-size: 0.85rem; opacity: 0.7; margin-top: 0.5rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
  th, td {{ text-align: right; padding: 0.4rem 0.55rem; border-bottom: 1px solid rgba(143,163,188,0.2); }}
  th:first-child, td:first-child {{ text-align: left; }}
  @media (max-width: 700px) {{ .stats {{ grid-template-columns: repeat(2, 1fr); }} }}
</style>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_document(title="France sovereign stress — explorer", body=body))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--full-costs", action="store_true", help="Rebuild 3×3 fee×half-tick grids")
    ap.add_argument("--force", action="store_true", help="Regenerate grid even if JSON exists")
    args = ap.parse_args()

    grid_path = data_dir() / "exit_level_grid.json"
    if args.force and grid_path.exists():
        grid_path.unlink()

    payload = _ensure_grid(n=args.n, full_costs=args.full_costs or args.force)
    curve = _base_curve(payload)

    md_path = STUDY_DIR / "EXPLORE.md"
    # Tracked at study root — root .gitignore blocks studies/*/reports/
    html_path = STUDY_DIR / "explore.html"
    reports_dir().mkdir(parents=True, exist_ok=True)
    html_reports = reports_dir() / "explore.html"

    write_md(payload, curve, md_path)
    write_html(payload, curve, html_path)
    write_html(payload, curve, html_reports)
    print("wrote", md_path)
    print("wrote", html_path)
    print("wrote", html_reports, "(local reports/)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
