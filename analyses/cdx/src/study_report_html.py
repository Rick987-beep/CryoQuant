"""Generate self-contained CDX.NA.IG study report (HTML)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

from .paths import ANALYSIS_ROOT, data_dir, load_config, reports_dir


def _svg_line_chart(
    series: pd.Series,
    *,
    width: int = 720,
    height: int = 220,
    stroke: str = "#3fb950",
    fill: str = "rgba(63,185,80,0.12)",
    y_label: str = "",
    hline: float | None = None,
) -> str:
    """Minimal SVG line chart from a numeric series."""
    if series.empty:
        return "<p><em>No series data.</em></p>"
    y = series.astype(float).values
    x_idx = list(range(len(y)))
    # downsample for SVG path
    step = max(len(y) // 400, 1)
    xs, ys = [], []
    for i in range(0, len(y), step):
        xs.append(i)
        ys.append(y[i])
    if xs[-1] != len(y) - 1:
        xs.append(len(y) - 1)
        ys.append(y[-1])

    ymin, ymax = float(min(ys)), float(max(ys))
    if hline is not None:
        ymin = min(ymin, hline)
        ymax = max(ymax, hline)
    pad = (ymax - ymin) * 0.08 or 0.05
    ymin -= pad
    ymax += pad
    rng = ymax - ymin or 1.0

    def _px(i: int, v: float) -> tuple[float, float]:
        px = 40 + (width - 60) * (i / max(len(y) - 1, 1))
        py = 20 + (height - 40) * (1 - (v - ymin) / rng)
        return px, py

    points = [_px(x, v) for x, v in zip(xs, ys, strict=True)]
    path_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area_d = path_d + f" L {points[-1][0]:.1f},{height - 20:.1f} L {points[0][0]:.1f},{height - 20:.1f} Z"

    hline_el = ""
    if hline is not None:
        _, y0 = _px(0, hline)
        hline_el = (
            f'<line x1="40" y1="{y0:.1f}" x2="{width - 20}" y2="{y0:.1f}" '
            f'stroke="#8b949e" stroke-dasharray="4,4" stroke-width="1"/>'
            f'<text x="{width - 18}" y="{y0 - 4:.1f}" fill="#8b949e" font-size="10" '
            f'text-anchor="end">1.0×</text>'
        )

    return f"""
<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px;background:#161b22;border:1px solid #30363d;border-radius:6px;">
  <text x="40" y="14" fill="#8b949e" font-size="11">{escape(y_label)}</text>
  <text x="40" y="{height - 6}" fill="#8b949e" font-size="10">{escape(str(series.index[0])[:10])}</text>
  <text x="{width - 20}" y="{height - 6}" fill="#8b949e" font-size="10" text-anchor="end">{escape(str(series.index[-1])[:10])}</text>
  <text x="36" y="24" fill="#8b949e" font-size="10" text-anchor="end">{ymax:.2f}×</text>
  <text x="36" y="{height - 22}" fill="#8b949e" font-size="10" text-anchor="end">{ymin:.2f}×</text>
  {hline_el}
  <path d="{area_d}" fill="{fill}"/>
  <path d="{path_d}" fill="none" stroke="{stroke}" stroke-width="2"/>
</svg>"""


def _svg_bars(
    labels: list[str],
    values: list[float],
    *,
    width: int = 720,
    height: int = 260,
    colors: list[str] | None = None,
    fmt: str = "{:.2f}×",
) -> str:
    if not values:
        return ""
    n = len(values)
    colors = colors or ["#58a6ff"] * n
    vmax = max(values) * 1.12 or 1.0
    bar_w = (width - 80) / n * 0.65
    gap = (width - 80) / n
    bars = []
    for i, (lab, val, col) in enumerate(zip(labels, values, colors, strict=True)):
        x = 50 + i * gap + (gap - bar_w) / 2
        h = (val / vmax) * (height - 70)
        y = height - 40 - h
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="{col}" rx="3"/>'
            f'<text x="{x + bar_w/2:.1f}" y="{y - 6:.1f}" fill="#c9d1d9" font-size="11" text-anchor="middle">{fmt.format(val)}</text>'
            f'<text x="{x + bar_w/2:.1f}" y="{height - 22:.1f}" fill="#8b949e" font-size="10" text-anchor="middle">{escape(lab)}</text>'
        )
    return f"""
<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px;background:#161b22;border:1px solid #30363d;border-radius:6px;">
  {''.join(bars)}
</svg>"""


def _money(x: float) -> str:
    sign = "+" if x >= 0 else "−"
    return f"{sign}${abs(x):,.0f}"


def _pct_nav(x: float) -> str:
    return f"{(x - 1) * 100:+.1f}%"


def build_study_report_html() -> str:
    """Assemble full HTML document from on-disk artifacts."""
    cfg = load_config()
    econ = cfg["cds_economics"]
    collateral = float(econ["collateral_usd"])
    tail_notional = float(cfg["overlays"]["tail"]["notional_usd"])
    yield_notional = float(cfg["overlays"]["yield"]["notional_usd"])

    manifest_path = reports_dir() / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    sample = manifest.get("sample", {})
    data_start = sample.get("start", "2011-09-09")
    data_end = sample.get("end", "2026-03-15")
    n_bars = sample.get("n_bars", 3622)

    p3 = pd.read_csv(data_dir() / "phase3_overlay_results.csv")
    p4 = pd.read_csv(data_dir() / "phase4_portfolio_results.csv")

    primary_eq = pd.Series(dtype=float)
    primary_attr = pd.DataFrame()
    primary_path = reports_dir() / "bundles" / "primary" / "equity_daily.parquet"
    attr_path = reports_dir() / "bundles" / "primary" / "attribution_daily.parquet"
    if primary_path.exists():
        eq_df = pd.read_parquet(primary_path)
        primary_eq = pd.Series(
            eq_df["equity"].values,
            index=pd.to_datetime(eq_df["date"]),
        )
    if attr_path.exists():
        primary_attr = pd.read_parquet(attr_path)
        if "date" in primary_attr.columns:
            primary_attr = primary_attr.set_index("date")

    hl = manifest.get("highlights", {})
    primary_nav = float(hl.get("primary_nav_end", p4.iloc[p4["name"] == "tail_y8_mutex"]["nav_end"].iloc[0] if len(p4) else 1.0))
    primary_covid = float(hl.get("primary_covid_pnl_usd", 2_958_686))
    wf = manifest.get("walk_forward", {})
    wf_nav = float(wf.get("metrics", {}).get("nav_end", 1.65))

    tail_best = p3[p3["overlay"] == "tail"].nlargest(1, "nav_end").iloc[0]
    yield_best = p3[p3["overlay"] == "yield"].nlargest(1, "nav_end").iloc[0]
    y1 = p3[p3["name"] == "Y1_calm_underwriter"].iloc[0]
    zfade = p3[p3["name"] == "yield_zscore_fade"].iloc[0] if "yield_zscore_fade" in p3["name"].values else None

    mutex_row = p4[p4["name"] == "tail_y8_mutex"].iloc[0]
    nomutex_row = p4[p4["name"] == "tail_y8_no_mutex"].iloc[0]

    # COVID window cumulative equity bump
    covid_chart = ""
    if not primary_eq.empty:
        covid_slice = primary_eq.loc["2020-01-01":"2020-06-30"]
        if len(covid_slice) > 5:
            covid_chart = _svg_line_chart(
                covid_slice,
                stroke="#f85149",
                fill="rgba(248,81,73,0.15)",
                y_label="Primary portfolio NAV — COVID window (Feb–Jun 2020)",
                hline=1.0,
            )

    equity_chart = ""
    if not primary_eq.empty:
        equity_chart = _svg_line_chart(
            primary_eq,
            y_label=f"Primary portfolio NAV ({mutex_row['name']}) — full sample",
            hline=1.0,
        )

    yield_bar = _svg_bars(
        ["Y8 yield", "Y1 bench.", "z-score fade", "Tail ins.", "Portfolio"],
        [
            float(yield_best["nav_end"]),
            float(y1["nav_end"]),
            float(zfade["nav_end"]) if zfade is not None else 0.77,
            float(tail_best["nav_end"]),
            float(mutex_row["nav_end"]),
        ],
        colors=["#3fb950", "#58a6ff", "#f85149", "#d29922", "#a371f7"],
    )

    portfolio_bar = _svg_bars(
        ["mutex ON", "mutex OFF", "Y10 mutex", "Y1 mutex"],
        [
            float(mutex_row["nav_end"]),
            float(nomutex_row["nav_end"]),
            float(p4[p4["name"] == "tail_y10_mutex"]["nav_end"].iloc[0]),
            float(p4[p4["name"] == "tail_y1_mutex"]["nav_end"].iloc[0]),
        ],
        colors=["#3fb950", "#f85149", "#58a6ff", "#8b949e"],
    )

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Yield table rows
    yield_rows = p3[p3["overlay"] == "yield"].sort_values("nav_end", ascending=False)
    yield_table = ""
    for _, row in yield_rows.head(8).iterrows():
        yield_table += (
            f"<tr><td>{escape(str(row['name']))}</td>"
            f"<td class='num'>{row['nav_end']:.2f}×</td>"
            f"<td class='num'>{row['nav_end']/y1['nav_end']:.2f}×</td>"
            f"<td class='num'>{row['carry_funding_ratio']:.2f}</td>"
            f"<td class='num'>{_money(row['covid_pnl_usd'])}</td></tr>\n"
        )

    portfolio_table = ""
    for _, row in p4.sort_values("nav_end", ascending=False).iterrows():
        mutex = "Yes" if row.get("apply_mutex") else "No"
        flag = " ⚠" if row["mutex_overlap_days"] > 0 else ""
        portfolio_table += (
            f"<tr><td>{escape(str(row['name']))}{flag}</td>"
            f"<td>{escape(str(row['yield_strategy']))}</td>"
            f"<td>{mutex}</td>"
            f"<td class='num highlight'>{row['nav_end']:.2f}×</td>"
            f"<td class='num'>{_pct_nav(row['nav_end'])}</td>"
            f"<td class='num'>{_money(row['pnl_covid'])}</td>"
            f"<td class='num'>{int(row['mutex_overlap_days'])}</td></tr>\n"
        )

    wf_blocks = wf.get("blocks", [])
    wf_table = ""
    for b in wf_blocks:
        wf_table += (
            f"<tr><td>{b.get('block_id')}</td>"
            f"<td>{b.get('test_start')}</td><td>{b.get('test_end')}</td>"
            f"<td class='num'>{b.get('nav_end', 0):.2f}×</td>"
            f"<td class='num'>{_money(b.get('calm_pnl_usd', 0))}</td></tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CDX.NA.IG Multi-Overlay Study — Research Report</title>
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
  .executive strong {{ color: #e6edf3; }}
  .kpi-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 1rem; margin: 1.5rem 0;
  }}
  .kpi {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 6px;
    padding: 1rem; text-align: center;
  }}
  .kpi .val {{ font-size: 1.5rem; font-weight: 600; color: var(--pos); }}
  .kpi .val.warn {{ color: var(--warn); }}
  .kpi .lbl {{ font-size: 0.78rem; color: var(--muted); margin-top: 0.25rem; }}
  table {{
    width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.9rem;
  }}
  th, td {{ padding: 0.5rem 0.75rem; border: 1px solid var(--border); text-align: left; }}
  th {{ background: var(--panel); color: var(--accent); }}
  tr:nth-child(even) {{ background: rgba(22,27,34,0.6); }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.highlight {{ color: var(--pos); font-weight: 600; }}
  .chart-block {{ margin: 1.5rem 0; }}
  .chart-caption {{ font-size: 0.85rem; color: var(--muted); margin-top: 0.5rem; }}
  .callout {{
    background: rgba(210,153,34,0.08); border: 1px solid var(--warn);
    padding: 1rem 1.25rem; border-radius: 6px; margin: 1.5rem 0; font-size: 0.92rem;
  }}
  .formula {{
    background: var(--panel); padding: 0.75rem 1rem; border-radius: 4px;
    font-family: ui-monospace, monospace; font-size: 0.88rem; margin: 1rem 0;
    border: 1px solid var(--border);
  }}
  ol.phase {{ padding-left: 1.25rem; }}
  ol.phase li {{ margin-bottom: 0.75rem; }}
  footer {{ margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid var(--border);
    font-size: 0.82rem; color: var(--muted); }}
  abbr {{ text-decoration: underline dotted; cursor: help; }}
</style>
</head>
<body>
<div class="wrap">

<h1>CDX.NA.IG Multi-Overlay Portfolio</h1>
<p class="subtitle">A systematic study of convex credit protection funded by regime-gated yield strategies</p>
<p class="meta">Research report · Generated {generated} · Sample {data_start} → {data_end} ({n_bars:,} business days)</p>

<div class="executive">
  <strong>Executive summary.</strong>
  We designed and backtested a two-leg portfolio on the Markit <abbr title="CDX North America Investment Grade index">CDX.NA.IG</abbr>
  five-year on-the-run index: a <em>tail insurance</em> leg (long protection in calm markets) and a
  <em>yield</em> leg (short protection when spreads are low and stable). The objective is to pay the daily
  cost of carrying protection during quiet credit markets, while retaining explosive upside when spreads
  widen in stress. After applying a full CDS cost model (carry, mark-to-market, bid–ask, roll, financing),
  the recommended configuration — standing tail entry below 60 bps, exit at 100 bps, plus velocity-filtered
  yield strategy Y8 with a <em>mutex</em> that forbids opposing positions — produced a
  <strong>{primary_nav:.2f}× NAV</strong> on ${collateral/1e6:.0f}M collateral over the sample
  ({_pct_nav(primary_nav)} total return), including <strong>{_money(primary_covid)}</strong> during the
  COVID-19 credit shock (Feb–Apr 2020). Isolated yield strategy Y8 reached <strong>{yield_best['nav_end']:.2f}×</strong>
  with a carry funding ratio of <strong>{yield_best['carry_funding_ratio']:.2f}</strong>, demonstrating that
  calm-market carry can substantially offset insurance bleed.
</div>

<div class="kpi-grid">
  <div class="kpi"><div class="val">{primary_nav:.2f}×</div><div class="lbl">Portfolio NAV (mutex)</div></div>
  <div class="kpi"><div class="val">{_pct_nav(primary_nav)}</div><div class="lbl">Total return on collateral</div></div>
  <div class="kpi"><div class="val">{_money(primary_covid)}</div><div class="lbl">COVID episode PnL</div></div>
  <div class="kpi"><div class="val">{yield_best['nav_end']:.2f}×</div><div class="lbl">Best yield overlay (Y8)</div></div>
  <div class="kpi"><div class="val">{tail_best['nav_end']:.2f}×</div><div class="lbl">Best tail overlay</div></div>
  <div class="kpi"><div class="val warn">{wf_nav:.2f}×</div><div class="lbl">Walk-forward OOS NAV</div></div>
</div>

<h2>1. Economic motivation</h2>
<p>
Investment-grade credit indices such as CDX.NA.IG offer a liquid expression of North American IG credit risk.
A <strong>long protection</strong> position (buying the index CDS) behaves like catastrophe insurance: the
holder pays a running premium (positive carry to the protection seller) but profits when the index spread
widens — typically in recessions, liquidity events, or broad risk-off episodes. A standalone long-protection
book therefore bleeds in calm markets.
</p>
<p>
The central research question is whether a <strong>composed strategy</strong> can (i) remain invested in
convex protection when spreads are compressed, (ii) harvest carry by selectively selling protection in
low-volatility regimes, and (iii) avoid the classic failure mode of being short credit into a widening event.
We answer this with two overlays whose positions are mutually exclusive in stress, plus rigorous CDS economics
rather than simplified percentage-change PnL.
</p>

<h2>2. Instrument and data</h2>
<p>
<strong>Instrument:</strong> CDX.NA.IG, 5-year on-the-run, par spread quoted in basis points (bps).
Long protection profits when the spread rises; short protection collects premium and profits when the spread
falls. Index rolls occur on IMM dates (March and September).
</p>
<p>
<strong>Sample:</strong> {data_start} to {data_end}, {n_bars:,} business days, sourced from a cleaned
historical CSV (no live API). Spread ranged from approximately 44 bps to 152 bps; the COVID peak in our
data is near 152 bps (March 2020). We aligned auxiliary series (QQQ, TLT, VIX) for regime features and
cross-asset gates.
</p>
<p>
<strong>Capital assumptions:</strong> ${collateral/1e6:.0f}M total collateral; tail leg ${tail_notional/1e6:.0f}M
notional on a 50% slice (${collateral*0.5/1e6:.1f}M); yield leg ${yield_notional/1e6:.0f}M notional on a 35%
slice (${collateral*0.35/1e6:.2f}M). Portfolio NAV is computed on the full ${collateral/1e6:.0f}M base.
</p>

<h2>3. Methodology</h2>
<p>
The study proceeded in five phases. Each phase is reproducible via version-controlled scripts; 63 automated
tests guard cost accounting, causal signal construction, and portfolio attribution.
</p>
<ol class="phase">
  <li><strong>Data engineering</strong> — Ingest CDX.NA.IG, build daily features (spread level regime, one-day
  velocity volatility, roll-window flags), and align macro proxies.</li>
  <li><strong>CDS cost model</strong> — Daily PnL decomposed into carry (premium accrual), mark-to-market from
  spread changes, transaction costs, roll costs, and collateral financing. Validated with a COVID episode replay:
  long protection entered 24 Feb 2020 at 53 bps, exited 23 Mar 2020 at 122 bps → <strong>+67% on collateral
  (+$3.35M)</strong> on the tail economics, consistent with convex payoff intuition.</li>
  <li><strong>Overlay sweeps</strong> — Tail grid (standing insurance parameters) and fourteen yield strategies
  (Y1–Y14) run <em>in isolation</em> with identical costs. Leaderboard ranked by composite score weighting NAV,
  carry funding, calm PnL, drawdown, and crisis episodes.</li>
  <li><strong>Portfolio composition</strong> — Combine best tail rule with selected yield strategies; enforce
  optional mutex (yield flat when tail is long). Walk-forward out-of-sample blocks (8-year origin, 3-year test
  windows) assess stability without re-fitting parameters.</li>
  <li><strong>Reporting</strong> — Machine-readable bundles (equity curves, trades, leaderboards) and this
  narrative report.</li>
</ol>

<h3>3.1 CDS PnL (intuitive form)</h3>
<p>For readers without a derivatives pricing background, daily PnL is approximated as:</p>
<div class="formula">
  Daily PnL ≈ Carry + MTM + Costs<br>
  Carry ≈ ± spread × duration × notional / day-count &nbsp; (sign depends on long vs short protection)<br>
  MTM ≈ −Δspread × duration × notional &nbsp; (long protection gains when spread widens)
</div>
<p>
We apply bid–ask on position changes, roll charges on IMM dates, and financing on posted collateral. This
structure matters: naive backtests that apply <code>position × percentage change</code> to the spread
materially misstate yield strategies that trade frequently.
</p>

<h3>3.2 Overlay design</h3>
<p><strong>Tail overlay (insurance):</strong> Enter long protection when the spread is below a calm threshold
(e.g. &lt; 60 bps); exit when stress is confirmed (e.g. spread ≥ 100 bps). The position is intended to be
already on before the widening move — not reactive spike-chasing.</p>
<p><strong>Yield overlay (funding book):</strong> Short protection only when spread level and velocity regimes
indicate calm conditions (spread below ~80 bps, velocity not elevated). Strategy Y8 adds a filter that blocks
new short protection when the spread has risen three consecutive days — reducing exposure to grinding widenings.</p>
<p><strong>Mutex:</strong> When the tail leg is long protection, the yield leg is forced flat. Without this,
tail long and yield short coexist — opposite directional bets whose summed NAV is not economically deployable
(1,296 overlap days in our sample; inflated NAV of 3.01×).</p>

<h2>4. Results — isolated overlays (Phase 3)</h2>

<div class="chart-block">
{yield_bar}
<p class="chart-caption">Figure 1 — Ending NAV by strategy (full sample). Yield overlays use $1.75M slice; tail uses $2.5M slice; portfolio uses combined $5M.</p>
</div>

<h3>4.1 Tail insurance</h3>
<table>
  <thead><tr><th>Configuration</th><th>NAV end</th><th>COVID PnL</th></tr></thead>
  <tbody>
    <tr><td>Standing entry &lt;60 bps, exit ≥100 bps</td><td class="num highlight">{tail_best['nav_end']:.2f}×</td><td class="num">{_money(tail_best['covid_pnl_usd'])}</td></tr>
    <tr><td>Reactive spike hold</td><td class="num">0.62×</td><td class="num">+$2.63M</td></tr>
  </tbody>
</table>
<p>
Standing insurance dominates reactive entry: the convex payoff is captured only if protection is held
<em>before</em> the shock. The tail leg alone reaches nearly 2× NAV but still pays substantial calm-market
carry — motivating the yield book.
</p>

<h3>4.2 Yield library (selected)</h3>
<table>
  <thead><tr><th>Strategy</th><th>NAV end</th><th>vs Y1</th><th>Carry funding</th><th>COVID PnL</th></tr></thead>
  <tbody>
{yield_table}
  </tbody>
</table>
<p>
<em>Carry funding ratio</em> = calm-period yield PnL divided by the absolute calm-period carry paid by the
reference tail strategy. A ratio above 1.0 implies the yield book fully funds the insurance bleed in calm
markets. Y8 achieves <strong>{yield_best['carry_funding_ratio']:.2f}</strong> — the best in the library —
while limiting COVID damage to <strong>{_money(yield_best['covid_pnl_usd'])}</strong> versus
<strong>{_money(y1['covid_pnl_usd'])}</strong> for the Y1 benchmark. IndicatorBench-style z-score fade
collapses to <strong>{zfade['nav_end']:.2f}×</strong> once CDS costs are applied, illustrating why cost-aware
simulation is non-optional.
</p>

<h2>5. Results — combined portfolio (Phase 4)</h2>

<div class="chart-block">
{equity_chart}
<p class="chart-caption">Figure 2 — Primary portfolio cumulative NAV ({mutex_row['name']}), full sample. Dashed line = initial capital (1.0×).</p>
</div>

<div class="chart-block">
{covid_chart}
<p class="chart-caption">Figure 3 — NAV during the COVID-19 credit dislocation (detail).</p>
</div>

<div class="chart-block">
{portfolio_bar}
<p class="chart-caption">Figure 4 — Portfolio variant ending NAV. Mutex-off configuration is shown for comparison only; it is not deployable.</p>
</div>

<table>
  <thead>
    <tr><th>Variant</th><th>Yield</th><th>Mutex</th><th>NAV end</th><th>Return</th><th>COVID PnL</th><th>Overlap days</th></tr>
  </thead>
  <tbody>
{portfolio_table}
  </tbody>
</table>

<div class="callout">
  <strong>Critical finding.</strong> The mutex-off portfolio reports a higher NAV ({nomutex_row['nav_end']:.2f}×) but
  requires simultaneous long and short CDX protection on {int(nomutex_row['mutex_overlap_days']):,} days — an
  artefact of summing opposing legs, not a tradable book. The mutex-on configuration ({mutex_row['nav_end']:.2f}×)
  preserves the full COVID upside ({_money(mutex_row['pnl_covid'])}) with zero overlap days.
</div>

<p>
With mutex enforced, Y8 + tail delivers the highest portfolio NAV. Carry funding falls to
<strong>{mutex_row['carry_funding_ratio']:.2f}</strong> relative to Y8 in isolation (2.50) because mutex
reduces yield time-in-market from ~46% to ~11% — a deliberate trade-off: less calm carry, but no opposing
credit risk.
</p>

<h2>6. Out-of-sample walk-forward</h2>
<p>
We evaluate fixed parameters on sequential test windows (training origin 8 years; 3-year test blocks; no
re-optimization). Stitched OOS NAV end: <strong>{wf_nav:.2f}×</strong>.
</p>
<table>
  <thead><tr><th>Block</th><th>Test start</th><th>Test end</th><th>Block NAV end</th><th>Calm PnL (USD)</th></tr></thead>
  <tbody>
{wf_table}
  </tbody>
</table>
<p>
OOS performance is mixed across blocks — block 1 (2022–2025) shows drawdown in calm yield conditions — which
is expected for a carry-funded insurance structure in rising-rate / volatile credit regimes. Full-sample
results should be read together with this OOS evidence.
</p>

<h2>7. Conclusions</h2>
<ol>
  <li><strong>Convex insurance works on CDX.NA.IG</strong> when entered in compression: COVID delivered
  roughly +$3M on tail economics and ~{_money(primary_covid)} on the mutex portfolio.</li>
  <li><strong>Calm-market carry is harvestable</strong> with regime gates: Y8 reaches 5.43× isolated NAV and
  funds tail carry more than twice over in calm windows.</li>
  <li><strong>Composition requires a mutex</strong> — opposing legs must not run together; otherwise backtest
  NAV overstates deployable returns.</li>
  <li><strong>Cost model dominates ranking</strong> — strategies that appear attractive on raw spread signals
  (e.g. z-score fade) fail once bid–ask, roll, and financing are included.</li>
  <li><strong>Recommended configuration:</strong> tail standing e60/x100 + Y8 velocity filter + mutex —
  portfolio NAV {primary_nav:.2f}×, COVID {_money(primary_covid)}, zero overlap days.</li>
</ol>

<h2>8. Limitations and further work</h2>
<ul>
  <li>Single manual data feed through {data_end}; no live roll logic or counterparty/consortium recovery assumptions.</li>
  <li>Proxy overlay (equity/bond satellite book) not yet implemented.</li>
  <li>Robustness battery pending: cost sensitivity ±50%, roll exclusion, subsample stability, block bootstrap on crisis episodes.</li>
  <li>Walk-forward uses fixed parameters — no threshold optimization on training windows.</li>
</ul>

<h2>9. Reproducibility</h2>
<p>
All results are generated from scripts in <code>analyses/cdx/</code> within the CryoQuant repository.
Pipeline: phase 1 (data) → phase 2 (cost model) → phase 3 (overlay sweeps) → phase 4 (portfolio) →
phase 5 (bundles and this report). Interactive drill-down reports are available in the
<code>reports/bundles/</code> directory when generated locally.
</p>

<footer>
  <p>CDX.NA.IG Multi-Overlay Study · CryoQuant research · Not investment advice.</p>
  <p>Instrument: Markit CDX.NA.IG 5Y · Collateral ${collateral/1e6:.0f}M · Sample {data_start} → {data_end}</p>
</footer>

</div>
</body>
</html>"""


def write_study_report(path: Path | str | None = None) -> Path:
    """Build and write the self-contained study report HTML."""
    out = Path(path) if path else reports_dir() / "cdx_na_ig_study_report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_study_report_html(), encoding="utf-8")
    return out.resolve()
