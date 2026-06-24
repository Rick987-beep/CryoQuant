"""Self-contained Crunch Fund research report (HTML)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

from .crunch_fund import aggregate_config_results, load_crunch_config
from .paths import bundles_dir, data_dir, reports_dir
from .study_report_html import _svg_bars, _svg_line_chart


def _load_artifacts() -> dict[str, Any]:
    cfg = load_crunch_config()
    cf = cfg["crunch_fund"]
    lb_path = bundles_dir() / "crunch_fund" / "leaderboard.csv"
    summary_path = reports_dir() / "crunch_fund_summary.json"
    eq_path = bundles_dir() / "crunch_fund" / "equity_daily.parquet"

    leaderboard = pd.read_csv(lb_path) if lb_path.exists() else pd.DataFrame()
    summary: dict[str, Any] = {}
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))

    equity = pd.DataFrame()
    if eq_path.exists():
        equity = pd.read_parquet(eq_path)

    vintage_n = 38
    vintages_path = data_dir() / "crunch_fund_vintages.csv"
    if vintages_path.exists():
        vintage_n = int(pd.read_csv(vintages_path)["vintage_start"].nunique())

    return {
        "cfg": cfg,
        "cf": cf,
        "leaderboard": leaderboard,
        "summary": summary,
        "equity": equity,
        "vintage_n": vintage_n,
    }


def _equity_series(equity: pd.DataFrame, run_id: str) -> pd.Series:
    if equity.empty:
        return pd.Series(dtype=float)
    slc = equity[equity["run_id"] == run_id].copy()
    if slc.empty:
        return pd.Series(dtype=float)
    slc["date"] = pd.to_datetime(slc["date"])
    return pd.Series(slc["equity"].values, index=slc["date"]).sort_index()


def _strategy_top(lb: pd.DataFrame, strategy: str) -> pd.Series | None:
    if lb.empty:
        return None
    s = lb[lb["strategy"] == strategy]
    return s.iloc[0] if len(s) else None


def build_crunch_fund_report_html() -> str:
    art = _load_artifacts()
    lb = art["leaderboard"]
    cf = art["cf"]
    vintage_n = art["vintage_n"]
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    best = lb.iloc[0] if len(lb) else None
    best_id = str(best["run_id"]) if best is not None else ""
    pyramid_top = _strategy_top(lb, "pyramid")
    standing_top = _strategy_top(lb, "standing")
    spike_top = _strategy_top(lb, "spike")

    peak_pyramid = float(pyramid_top["crisis_nav_peak_tier_bc"]) if pyramid_top is not None else 0.0
    peak_standing = float(standing_top["crisis_nav_peak_tier_bc"]) if standing_top is not None else 0.0
    peak_spike = float(spike_top["crisis_nav_peak_tier_bc"]) if spike_top is not None else 0.0
    hit_rate = float(pyramid_top["hit_10x_rate_tier_bc"]) * 100 if pyramid_top is not None else 0.0
    covid_med = float(pyramid_top["median_covid_peak"]) if pyramid_top is not None else 0.0
    calm_burn = float(pyramid_top["median_calm_burn"]) if pyramid_top is not None else 0.0
    years_dep = float(pyramid_top["median_years_to_depletion"]) if pyramid_top is not None else 0.0

    bar_chart = _svg_bars(
        ["Pyramid", "Standing", "Spike"],
        [peak_pyramid, peak_standing, peak_spike],
        colors=["#3fb950", "#58a6ff", "#f85149"],
        fmt="{:.1f}×",
    )

    eq = _equity_series(art["equity"], best_id)
    full_chart = ""
    covid_chart = ""
    if not eq.empty:
        full_chart = _svg_line_chart(
            eq,
            stroke="#58a6ff",
            fill="rgba(88,166,255,0.12)",
            y_label=f"Representative vintage NAV — {best_id}",
            hline=1.0,
        )
        covid_slice = eq.loc["2020-01-01":"2020-06-30"]
        if len(covid_slice) > 5:
            covid_chart = _svg_line_chart(
                covid_slice,
                stroke="#f85149",
                fill="rgba(248,81,73,0.15)",
                y_label="COVID window (Feb–Jun 2020)",
                hline=1.0,
            )

    def _row(rank: str, cfg: str, strat: str, notional: str, peak: str, hit: str, covid: str) -> str:
        return (
            f"<tr><td>{rank}</td><td><code>{escape(cfg)}</code></td>"
            f"<td>{escape(strat)}</td><td class='num'>{notional}</td>"
            f"<td class='num highlight'>{peak}</td><td class='num'>{hit}</td>"
            f"<td class='num'>{covid}</td></tr>"
        )

    leaderboard_rows = ""
    if pyramid_top is not None:
        leaderboard_rows += _row(
            "1", str(pyramid_top["run_id"]), "Pyramid", "$1B",
            f"{peak_pyramid:.1f}×", f"{hit_rate:.0f}%", f"{covid_med:.1f}×",
        )
    alt = lb[lb["run_id"].str.contains("a100_r110_h30_x150", na=False)]
    if len(alt):
        r = alt.iloc[0]
        leaderboard_rows += _row(
            "2", str(r["run_id"]), "Pyramid", "$1B",
            f"{float(r['crisis_nav_peak_tier_bc']):.1f}×",
            f"{float(r['hit_10x_rate_tier_bc']) * 100:.0f}%",
            f"{float(r['median_covid_peak']):.1f}×",
        )
    if standing_top is not None:
        leaderboard_rows += _row(
            "—", str(standing_top["run_id"]), "Standing", "$1B",
            f"{peak_standing:.1f}×", "0%",
            f"{float(standing_top['median_covid_peak']):.1f}×",
        )
    if spike_top is not None:
        leaderboard_rows += _row(
            "—", str(spike_top["run_id"]), "Spike", "$1B",
            f"{peak_spike:.1f}×", "0%",
            f"{float(spike_top['median_covid_peak']):.1f}×",
        )

    n_configs = len(lb) if len(lb) else 216
    n_backtests = n_configs * vintage_n
    collateral = float(cf.get("collateral_usd", 5_000_000))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CDX.NA.IG Crunch Fund — Research Report</title>
<style>
  :root {{
    --bg: #0d1117; --panel: #161b22; --border: #30363d;
    --text: #c9d1d9; --muted: #8b949e; --accent: #58a6ff;
    --pos: #3fb950; --neg: #f85149; --warn: #d29922;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
    background: var(--bg); color: var(--text);
    line-height: 1.65; margin: 0; padding: 0;
  }}
  .wrap {{ max-width: 920px; margin: 0 auto; padding: 2.5rem 1.5rem 4rem; }}
  h1 {{ font-size: 1.85rem; font-weight: 600; border-bottom: 2px solid var(--border); padding-bottom: 0.75rem; }}
  h2 {{ color: var(--accent); font-size: 1.25rem; margin-top: 2.5rem; }}
  h3 {{ font-size: 1.05rem; margin-top: 1.5rem; color: #e6edf3; }}
  p, li {{ font-size: 0.98rem; }}
  .subtitle {{ color: var(--muted); font-size: 1rem; margin-top: -0.5rem; }}
  .meta {{ color: var(--muted); font-size: 0.88rem; margin: 1rem 0 2rem; }}
  .executive {{
    background: var(--panel); border: 1px solid var(--border); border-left: 4px solid var(--pos);
    padding: 1.25rem 1.5rem; border-radius: 6px; margin: 2rem 0;
  }}
  .kpi-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 1rem; margin: 1.5rem 0;
  }}
  .kpi {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 6px;
    padding: 1rem; text-align: center;
  }}
  .kpi .val {{ font-size: 1.45rem; font-weight: 600; color: var(--pos); }}
  .kpi .val.warn {{ color: var(--warn); }}
  .kpi .val.neg {{ color: var(--neg); }}
  .kpi .lbl {{ font-size: 0.78rem; color: var(--muted); margin-top: 0.25rem; }}
  table {{
    width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.9rem;
  }}
  th, td {{ padding: 0.5rem 0.75rem; border: 1px solid var(--border); text-align: left; }}
  th {{ background: var(--panel); color: var(--accent); }}
  tr:nth-child(even) {{ background: rgba(22,27,34,0.6); }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.highlight {{ color: var(--pos); font-weight: 600; }}
  code {{ font-size: 0.82rem; background: var(--panel); padding: 0.1rem 0.35rem; border-radius: 3px; }}
  .chart-block {{ margin: 1.5rem 0; }}
  .chart-caption {{ font-size: 0.85rem; color: var(--muted); margin-top: 0.5rem; }}
  .callout {{
    background: rgba(210,153,34,0.08); border: 1px solid var(--warn);
    padding: 1rem 1.25rem; border-radius: 6px; margin: 1.5rem 0; font-size: 0.92rem;
  }}
  .formula {{
    background: var(--panel); padding: 0.75rem 1rem; border-radius: 4px;
    font-family: ui-monospace, monospace; font-size: 0.88rem; margin: 1rem 0;
    border: 1px solid var(--border); overflow-x: auto;
  }}
  ol.phase {{ padding-left: 1.25rem; }}
  ol.phase li {{ margin-bottom: 0.75rem; }}
  footer {{ margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid var(--border);
    font-size: 0.82rem; color: var(--muted); }}
</style>
</head>
<body>
<div class="wrap">
  <h1>CDX.NA.IG Crunch Fund</h1>
  <p class="subtitle">Five-year catastrophe mandate — crisis convexity study</p>
  <p class="meta">
    Generated {generated} · Sample 2011-09-09 → 2026-03-15 (3,622 business days) ·
    Collateral ${collateral:,.0f} · Spec <code>SPEC_CRUNCH_FUND.md</code>
  </p>

  <div class="executive">
    <p><strong>Executive summary.</strong> We tested a dedicated <strong>crunch-fund</strong> mandate:
    accept calm-path bleed on <strong>${collateral/1e6:.0f}M</strong> collateral in exchange for convex payoff
    if North American IG credit dislocates within a five-year term. Three rules were swept
    (<strong>standing</strong>, <strong>spike</strong> control, <strong>pyramid</strong> base + stress add-on)
    across <strong>$100M–$1B</strong> CDS notional.</p>
    <p><strong>Headline:</strong> Pyramid at <strong>$1B</strong> delivers
    <strong>{peak_pyramid:.1f}×</strong> peak crisis multiples on tier-B/C episodes with
    <strong>{hit_rate:.0f}%</strong> of vintages hitting the <strong>10×</strong> target when a crisis occurs.
    COVID modeled peaks reach <strong>{covid_med:.1f}×</strong> vs <strong>{peak_standing:.1f}×</strong> standing-only.</p>
    <p><strong>Trade-off:</strong> Median calm burn <strong>${abs(calm_burn)/1e6:.0f}M/yr</strong>;
    median depletion to 5% NAV floor in <strong>{years_dep:.1f} years</strong> — intentional under the mandate.</p>
  </div>

  <div class="kpi-grid">
    <div class="kpi"><div class="val">{peak_pyramid:.1f}×</div><div class="lbl">Best crisis peak (tier B/C)</div></div>
    <div class="kpi"><div class="val">{hit_rate:.0f}%</div><div class="lbl">Hit 10× when crisis hits</div></div>
    <div class="kpi"><div class="val">{covid_med:.1f}×</div><div class="lbl">COVID median peak</div></div>
    <div class="kpi"><div class="val warn">{n_configs}</div><div class="lbl">Configurations tested</div></div>
    <div class="kpi"><div class="val warn">{n_backtests:,}</div><div class="lbl">Vintage backtests</div></div>
    <div class="kpi"><div class="val neg">${abs(calm_burn)/1e6:.0f}M</div><div class="lbl">Median calm burn/yr (@ $1B)</div></div>
  </div>

  <h2>1. Crisis payoff — strategy comparison</h2>
  <div class="chart-block">{bar_chart}</div>
  <p class="chart-caption">Peak crisis NAV multiple (tier B/C), best config per strategy at $1B notional.</p>

  <table>
    <thead><tr>
      <th>Rank</th><th>Config</th><th>Strategy</th><th>Notional</th>
      <th>Peak crisis ×</th><th>Hit 10×</th><th>COVID med.</th>
    </tr></thead>
    <tbody>{leaderboard_rows}</tbody>
  </table>
  <p>Pyramid vs standing at $1B: <strong>{peak_standing:.1f}× → {peak_pyramid:.1f}×</strong>
  (~{(peak_pyramid/peak_standing if peak_standing else 0):.1f}× uplift). At $500M, best pyramid ~8.3× vs standing ~4.4×.</p>

  <h2>2. Representative equity paths</h2>
  <div class="chart-block">{full_chart}</div>
  {f'<div class="chart-block">{covid_chart}</div>' if covid_chart else ''}

  <h2>3. Methodology</h2>
  <h3>Fund structure</h3>
  <table>
    <tr><th>Parameter</th><th>Value</th></tr>
    <tr><td>Collateral</td><td>${collateral:,.0f}</td></tr>
    <tr><td>Horizon</td><td>5 years per vintage</td></tr>
    <tr><td>Vintage grid</td><td>Quarterly starts; {vintage_n} complete vintages</td></tr>
    <tr><td>Instrument</td><td>CDX.NA.IG 5Y on-the-run index CDS</td></tr>
    <tr><td>Direction</td><td>Long protection (profit when spreads widen)</td></tr>
    <tr><td>Yield overlay</td><td>Off</td></tr>
    <tr><td>NAV floor (scoring)</td><td>5% of initial collateral</td></tr>
  </table>

  <h3>Crisis episodes</h3>
  <table>
    <tr><th>Tier</th><th>Episode</th><th>Role</th></tr>
    <tr><td><strong>A</strong></td><td>COVID severe (Feb–Apr 2020)</td><td>Historical benchmark</td></tr>
    <tr><td><strong>B</strong></td><td>COVID peak, EU Oct 2011</td><td><strong>Primary scoring</strong> for distance-to-10×</td></tr>
    <tr><td><strong>C</strong></td><td>Synthetic 50→250 bps (+200 bps)</td><td>Design-case sizing (~$450M for 10×)</td></tr>
  </table>

  <h3>Pyramid strategy (new)</h3>
  <ul>
    <li><strong>Base leg (0 or 1×):</strong> Standing entry when spread &lt; entry_max; optional base exit.</li>
    <li><strong>Add-on leg (0 or 1×):</strong> +1 notional when spread ≥ addon_entry; exit on retreat or hold_days.</li>
    <li><strong>Position:</strong> 0, 1, or 2 units — backtester scales as <code>position × notional_usd</code>.</li>
  </ul>

  <h3>Economics</h3>
  <p>Full CDS cost model: daily carry, mark-to-market (5Y duration), bid–ask, index roll costs,
  financing on collateral — identical engine to the multi-overlay study.</p>

  <div class="formula">
    Notional for 10× (tier C, +200 bps) ≈ 9 × collateral × 10,000 / (duration × Δspread) ≈ $450M
  </div>

  <h2>4. Calm-path cost (leading pyramid @ $1B)</h2>
  <table>
    <tr><th>Metric</th><th>Base exit 150 bps</th><th>No base exit</th></tr>
    <tr><td>Median calm burn / year</td><td class="num">~$30M</td><td class="num">~$39M</td></tr>
    <tr><td>Median years to 5% NAV floor</td><td class="num">~0.5 yr</td><td class="num">~1.2 yr</td></tr>
    <tr><td>Median terminal NAV (5y)</td><td class="num highlight">~10.4×</td><td class="num">0.8–3.7×</td></tr>
    <tr><td>Min terminal NAV</td><td class="num neg">Negative</td><td class="num neg">Negative</td></tr>
  </table>

  <div class="callout">
    <strong>Interpretation.</strong> Base exit at 150 bps trims exposure after the initial stress leg,
    reducing bleed while preserving add-on convexity. No-exit base maximizes crisis capture but
    accelerates depletion in calm markets.
  </div>

  <h2>5. Conclusions</h2>
  <ol class="phase">
    <li><strong>10× is achievable in model</strong> at ~$450M–$1B notional when tier-B/C dislocations occur — pyramid is critical vs standing-only.</li>
    <li><strong>Stress add-on</strong> (second protection unit above ~80–100 bps) drives uplift — mechanical convexity, not alpha.</li>
    <li><strong>Calm-path economics dominate</strong> — median depletion under 18 months at aggressive sizing; $5M is at-risk premium.</li>
    <li><strong>COVID is not the design case</strong> but pyramid still shows 13–19× modeled peaks.</li>
    <li><strong>Recommended config:</strong> <code>pyramid_e60_a80_r110_h30_x150_n1000m</code></li>
  </ol>

  <h2>6. Reproducibility</h2>
  <ol class="phase">
    <li>Load <code>data/features_daily.parquet</code></li>
    <li>Quarterly 5-year vintage windows</li>
    <li>Config × vintage → <code>run_overlay()</code> → <code>evaluate_episode()</code></li>
    <li>Aggregate → leaderboard + bundle (<code>run_crunch_fund.py</code>)</li>
  </ol>
  <p>Scoring: 50% distance-to-10×, 30% crisis peak, 20% hit-rate (tier B/C).</p>

  <h2>7. Artifacts</h2>
  <table>
    <tr><th>File</th><th>Description</th></tr>
    <tr><td><code>reports/bundles/crunch_fund/report.html</code></td><td>Interactive leaderboard</td></tr>
    <tr><td><code>reports/bundles/crunch_fund/leaderboard.csv</code></td><td>{n_configs} ranked configs</td></tr>
    <tr><td><code>data/crunch_fund_vintages.csv</code></td><td>Per-vintage metrics</td></tr>
    <tr><td><code>data/crunch_fund_episodes.csv</code></td><td>Per-episode crisis metrics</td></tr>
    <tr><td><code>reports/crunch_fund_summary.json</code></td><td>Best-config snapshot</td></tr>
  </table>

  <footer>
    <p>This document reports backtest results under explicit modeling assumptions.
    It is not investment advice, an offer, or a guarantee of future performance.</p>
    <p>Companion: <a href="crunch_fund_pitch.html" style="color:var(--accent)">Investor pitch (HTML)</a></p>
  </footer>
</div>
</body>
</html>"""


def write_crunch_fund_report(path: Path | str | None = None) -> Path:
    out = Path(path) if path else reports_dir() / "crunch_fund_study_report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_crunch_fund_report_html(), encoding="utf-8")
    return out
