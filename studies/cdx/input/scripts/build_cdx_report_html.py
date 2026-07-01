#!/usr/bin/env python3
"""Build self-contained HTML report from CDX stress analysis with embedded charts."""
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
OUT = ROOT / "reports" / "cdx_na_ig_nasdaq_stress_analysis_2026-06-10.html"


def b64_img(name: str) -> str:
    data = base64.b64encode((ASSETS / name).read_bytes()).decode()
    return f"data:image/png;base64,{data}"


CHARTS = {
    "cdx_regimes.png": "Regime velocity volatility and sample-day frequency",
    "cdx_granger_regimes.png": "Regime-conditional Granger F-statistics (3-day % spec)",
    "cdx_recovery_signal.png": "Confirmed tightening signal — forward NASDAQ returns",
    "cdx_drawdown_scatter.png": "CDX move magnitude vs NASDAQ drawdown depth (11 events)",
}


def chart_block(filename: str) -> str:
    cap = CHARTS[filename]
    src = b64_img(filename)
    return f"""<figure class="chart-wrap">
  <img src="{src}" alt="{cap}" loading="lazy"/>
  <figcaption class="chart-caption">{cap}</figcaption>
</figure>"""


HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover"/>
<meta name="apple-mobile-web-app-capable" content="yes"/>
<title>CDX NA IG &amp; NASDAQ Under Stress — Research Brief</title>
<style>
  :root {{
    --green:   #2E6B5A;
    --green-lt:#EBF4F1;
    --tan:     #D4C5A9;
    --tan-lt:  #FAF8F4;
    --red:     #A03030;
    --navy:    #1A2B3C;
    --grey:    #5A6272;
    --border:  #D6D9DF;
    --bg:      #F8F8F8;
    --safe-b:  env(safe-area-inset-bottom, 0px);
    --safe-t:  env(safe-area-inset-top, 0px);
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html {{ -webkit-text-size-adjust: 100%; }}
  body {{
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    background: #fff;
    color: #222;
    line-height: 1.65;
    font-size: 16px;
    padding-top: var(--safe-t);
    padding-bottom: var(--safe-b);
  }}
  .cover {{
    background: linear-gradient(155deg, var(--navy) 0%, #243A52 50%, var(--green) 100%);
    color: #fff;
    padding: max(48px, var(--safe-t)) 24px 40px;
  }}
  .cover .brand {{ font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; opacity: 0.72; }}
  .cover h1 {{ font-size: clamp(1.5rem, 5.5vw, 2.15rem); font-weight: 700; line-height: 1.2; margin: 14px 0 10px; }}
  .cover .subtitle {{ font-size: clamp(0.95rem, 3.5vw, 1.1rem); opacity: 0.88; line-height: 1.45; max-width: 36em; }}
  .cover-meta {{ display: flex; flex-wrap: wrap; gap: 20px 32px; margin-top: 28px; font-size: 13px; }}
  .cover-meta dt {{ opacity: 0.65; font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; }}
  .cover-meta dd {{ font-weight: 600; margin-top: 2px; }}
  .disclaimer-banner {{
    background: #FDF6EC; border-bottom: 1px solid #E8D4B0;
    padding: 12px 20px; font-size: 13px; color: #6B4E2A;
    line-height: 1.45;
  }}
  .page-wrap {{ max-width: 900px; margin: 0 auto; padding: 28px 20px 48px; }}
  .toc {{
    background: var(--tan-lt); border: 1px solid var(--tan);
    border-radius: 10px; padding: 20px 22px; margin-bottom: 32px;
  }}
  .toc h2 {{ font-size: 15px; margin: 0 0 12px; color: var(--green); border: none; padding: 0; }}
  .toc ol {{ margin: 0 0 0 20px; font-size: 14px; }}
  .toc li {{ margin-bottom: 6px; }}
  .toc a {{ color: var(--navy); text-decoration: none; }}
  .section-label {{
    font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase;
    color: var(--green); margin-top: 40px; margin-bottom: 4px;
  }}
  h2 {{
    font-size: clamp(1.25rem, 4vw, 1.65rem); font-weight: 700; color: var(--navy);
    border-bottom: 2px solid var(--green); padding-bottom: 8px; margin-bottom: 18px;
  }}
  h3 {{ font-size: 1.1rem; font-weight: 700; color: var(--navy); margin: 28px 0 10px; }}
  h4 {{ font-size: 0.95rem; font-weight: 600; color: var(--grey); margin: 20px 0 8px; }}
  p {{ margin-bottom: 14px; }}
  ul, ol {{ margin: 0 0 14px 22px; }}
  li {{ margin-bottom: 6px; }}
  strong {{ font-weight: 600; }}
  em {{ font-style: italic; }}
  a {{ color: var(--green); word-break: break-word; }}
  .callout {{
    background: var(--green-lt); border-left: 4px solid var(--green);
    padding: 16px 18px; border-radius: 0 8px 8px 0; margin: 20px 0; font-size: 15px;
  }}
  .callout.warn {{ background: #FDF6EC; border-left-color: #D4904A; }}
  .kpi-grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 12px; margin: 20px 0;
  }}
  .kpi-card {{
    background: var(--green-lt); border: 1px solid #C5DDD8;
    border-radius: 8px; padding: 14px 12px; text-align: center;
  }}
  .kpi-card .kpi-label {{ font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--grey); }}
  .kpi-card .kpi-value {{ font-size: 1.35rem; font-weight: 700; color: var(--navy); margin-top: 4px; }}
  .kpi-card .kpi-sub {{ font-size: 11px; color: var(--grey); margin-top: 2px; }}
  .table-scroll {{ overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 16px 0 20px; }}
  table {{
    width: 100%; min-width: 280px; border-collapse: collapse;
    font-size: 13px;
  }}
  thead tr {{ background: var(--navy); color: #fff; }}
  thead th {{
    padding: 10px 12px; text-align: right; font-size: 11px;
    font-weight: 600; white-space: nowrap;
  }}
  thead th:first-child {{ text-align: left; }}
  tbody tr:nth-child(even) {{ background: #F5F6F8; }}
  tbody td {{ padding: 9px 12px; border-bottom: 1px solid var(--border); text-align: right; }}
  tbody td:first-child {{ text-align: left; }}
  .chart-wrap {{
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px; margin: 24px 0;
  }}
  .chart-wrap img {{ display: block; width: 100%; height: auto; border-radius: 4px; }}
  .chart-caption {{ font-size: 12px; color: var(--grey); margin-top: 10px; font-style: italic; text-align: center; }}
  pre, .code-block {{
    background: #1E2A36; color: #E8ECF0; padding: 16px;
    border-radius: 8px; overflow-x: auto; font-size: 12.5px;
    line-height: 1.5; margin: 16px 0; -webkit-overflow-scrolling: touch;
    font-family: 'SF Mono', Menlo, Consolas, monospace;
  }}
  .rating-yes {{ color: var(--green); font-weight: 600; }}
  .rating-no {{ color: var(--red); font-weight: 600; }}
  .report-footer {{
    border-top: 2px solid var(--border); padding-top: 24px; margin-top: 48px;
    font-size: 12px; color: #888;
  }}
  .checklist {{ list-style: none; margin-left: 0; }}
  .checklist li {{ padding-left: 1.4em; position: relative; }}
  .checklist li::before {{ content: "☐"; position: absolute; left: 0; color: var(--grey); }}
  @media (max-width: 480px) {{
    .page-wrap {{ padding: 20px 16px 40px; }}
    body {{ font-size: 15px; }}
    thead th, tbody td {{ padding: 8px 10px; font-size: 12px; }}
    .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }}
  }}
  @media print {{
    .cover {{ page-break-after: always; }}
    .chart-wrap {{ break-inside: avoid; }}
  }}
</style>
</head>
<body>

<header class="cover">
  <div class="brand">Research Brief · Credit Markets</div>
  <h1>CDX NA IG and NASDAQ Under Stress</h1>
  <p class="subtitle">Managing drawdown and recovery risk with credit-market signals — analysis of Nguyen (2026) working paper.</p>
  <dl class="cover-meta">
    <div><dt>Date</dt><dd>2026-06-10</dd></div>
    <div><dt>Audience</dt><dd>AI agents &amp; human readers</dd></div>
    <div><dt>Sample</dt><dd>3,668 daily obs · Sep 2011 – Jun 2026</dd></div>
  </dl>
</header>

<div class="disclaimer-banner">
  <strong>Not investment advice.</strong> This brief summarizes academic research. The source paper carries the same disclaimer.
</div>

<main class="page-wrap">

<nav class="toc" aria-label="Table of contents">
  <h2>Contents</h2>
  <ol>
    <li><a href="#exec">Executive Summary</a></li>
    <li><a href="#intro">Introduction and Scope</a></li>
    <li><a href="#method">Methodology</a></li>
    <li><a href="#results">Key Empirical Results</a></li>
    <li><a href="#strategy">Trading Strategy</a></li>
    <li><a href="#literature">Literature Context</a></li>
    <li><a href="#opinion">Opinion</a></li>
    <li><a href="#next">Next Steps</a></li>
    <li><a href="#conclusion">Conclusion</a></li>
    <li><a href="#sources">Sources</a></li>
  </ol>
</nav>

<section id="exec">
<p class="section-label">Overview</p>
<h2>Executive Summary</h2>
<p>Thao Nguyen's 2026 working paper argues that <strong>CDX NA IG</strong> is a high-value <strong>risk overlay</strong> for a long-horizon <strong>NASDAQ</strong> allocation—not a tool to time corrections from calm markets, but a disciplined way to <strong>trim, hold, and rebuild</strong> equity exposure once stress is underway.</p>

<div class="kpi-grid">
  <div class="kpi-card"><div class="kpi-label">Sample</div><div class="kpi-value">3,668</div><div class="kpi-sub">daily observations</div></div>
  <div class="kpi-card"><div class="kpi-label">Coincident ρ</div><div class="kpi-value">−0.67 to −0.82</div><div class="kpi-sub">by regime</div></div>
  <div class="kpi-card"><div class="kpi-label">Recovery (20d)</div><div class="kpi-value">+2.43%</div><div class="kpi-sub">75% hit rate confirmed</div></div>
  <div class="kpi-card"><div class="kpi-label">OOS 2023–26</div><div class="kpi-value">+5.01%</div><div class="kpi-sub">85% hit rate</div></div>
</div>

<p>Using a <strong>3-state Markov-Switching VAR</strong> with regimes defined by the <strong>volatility of CDX spread velocity</strong> (3-day % change), the paper establishes three empirical pillars:</p>
<ol>
  <li><strong>Coincident stress gauge:</strong> A sharp widening (+3% 3-day move) coincides with NASDAQ declines in <strong>85–91%</strong> of cases.</li>
  <li><strong>Regime-conditional leadership:</strong> CDX Granger-causes NASDAQ only in <strong>Moderate-</strong> and <strong>High-Stress</strong> regimes (F ≈ 5.2 and 5.0, p &lt; 0.01). In calm markets, CDX has no predictive power (p = 0.095).</li>
  <li><strong>Recovery signal:</strong> A sharp tightening (−5% 3-day move) in <strong>High-Stress</strong>, especially when <strong>confirmed</strong> (a second tightening within ~20 days), precedes positive NASDAQ returns.</li>
</ol>

<div class="callout">
  <strong>Central insight:</strong> Stress is better defined by velocity turbulence than by spread level. Moderate- and High-Stress regimes sit at nearly identical median CDX levels (~71 vs ~70 bps) but differ <strong>2.5×</strong> in velocity volatility (σ ≈ 3.0% vs 7.6%).
</div>

<p><strong>Trading takeaway:</strong> Stay fully invested in calm regimes; on confirmed stress widening, scale down NASDAQ exposure proportional to CDX move severity; on confirmed high-stress tightening, rebuild exposure. The framework is risk management, not alpha generation vs buy-and-hold over full cycles.</p>
</section>

<section id="intro">
<p class="section-label">Section 1</p>
<h2>Introduction and Scope</h2>

<h3>1.1 Research question</h3>
<p>Can CDX NA IG inform <strong>dynamic sizing</strong> of NASDAQ exposure through stress episodes—trimming as corrections develop and rebuilding as they resolve—without requiring forecasts from tranquil conditions?</p>

<h3>1.2 Why CDX NA IG</h3>
<div class="table-scroll"><table>
<thead><tr><th>Criterion</th><th>CDX NA IG rationale</th></tr></thead>
<tbody>
<tr><td>Liquidity</td><td>Among the most liquid credit instruments globally</td></tr>
<tr><td>Systemic signal</td><td>IG basket of 125 NA issuers; macro-driven</td></tr>
<tr><td>Economic link</td><td>NA large-cap issuer overlap with US equity indices</td></tr>
<tr><td>History</td><td>Continuous post-GFC data; modern cleared market</td></tr>
</tbody></table></div>

<h3>1.3 Why NASDAQ</h3>
<p>Technology-heavy benchmark with high sensitivity to funding conditions and risk appetite—a demanding test case for a credit overlay.</p>

<h3>1.4 Sample design</h3>
<p>Sample starts <strong>September 2011</strong> (post-GFC), reflecting post-Dodd-Frank / EMIR central clearing. Gross CDS notional fell from ~$62tn (2007) to &lt;$10tn (2017).</p>

<h3>1.5 External market context (June 2026)</h3>
<div class="table-scroll"><table>
<thead><tr><th>Date / period</th><th>CDX IG spread</th><th>Source</th></tr></thead>
<tbody>
<tr><td>End-2024</td><td>~50 bps</td><td>Algonquin / Bloomberg</td></tr>
<tr><td>Apr 2025</td><td>~69 bps</td><td>Algonquin</td></tr>
<tr><td>May 2025</td><td>~56 bps</td><td>Algonquin</td></tr>
<tr><td>Dec 2025</td><td>~49 bps</td><td>SOLVE</td></tr>
<tr><td>Mar 2026</td><td>~58.9 bps</td><td>Cbonds / ICE</td></tr>
</tbody></table></div>
<p>Current levels (~50–60 bps) sit <strong>below</strong> stress-episode peaks (61–152 bps), consistent with a non–high-stress environment unless velocity spikes.</p>
</section>

<section id="method">
<p class="section-label">Section 2</p>
<h2>Methodology</h2>

<h3>2.1 Data transforms</h3>
<ul>
  <li><strong>CDX:</strong> First differences of 5Y on-the-run spread; 1/3/5-day changes in bps and %</li>
  <li><strong>NASDAQ:</strong> Log returns</li>
  <li><strong>Stationarity:</strong> ADF tests passed</li>
</ul>

<h3>2.2 Velocity vs volatility</h3>
<div class="table-scroll"><table>
<thead><tr><th>Concept</th><th>Definition</th><th>Role</th></tr></thead>
<tbody>
<tr><td><strong>Velocity</strong></td><td>3-day % change (S<sub>t</sub> − S<sub>t−3</sub>)/S<sub>t−3</sub></td><td><strong>Signal</strong></td></tr>
<tr><td><strong>Volatility</strong></td><td>σ of velocity series</td><td><strong>Regime</strong></td></tr>
<tr><td><strong>Level</strong></td><td>Absolute spread in bps</td><td>Not primary separator</td></tr>
</tbody></table></div>

<h3>2.3 MS-VAR structure</h3>
<ul>
  <li>3 regimes by ascending velocity volatility (~80 EM iterations)</li>
  <li>Variables: CDX change + NASDAQ return, 3 lags</li>
  <li>Hamilton filter + Markov transitions</li>
  <li>Regime-weighted Granger tests both directions</li>
</ul>

<h3>2.4 Operational signals</h3>
<div class="table-scroll"><table>
<thead><tr><th>Signal</th><th>Rule</th><th>Intent</th></tr></thead>
<tbody>
<tr><td>Widening</td><td>3-day CDX % &gt; +3%</td><td>Confirm drawdown</td></tr>
<tr><td>Tightening</td><td>3-day CDX % &lt; −5%</td><td>Flag recovery</td></tr>
<tr><td>Confirmed</td><td>≥2 tightenings in 20 days</td><td>Filter false rebounds</td></tr>
</tbody></table></div>
</section>

<section id="results">
<p class="section-label">Section 3</p>
<h2>Key Empirical Results</h2>

<h3>3.1 Regime statistics (Table 1)</h3>
<div class="table-scroll"><table>
<thead><tr><th>Metric</th><th>Low-Stress</th><th>Moderate</th><th>High-Stress</th></tr></thead>
<tbody>
<tr><td>Share of days</td><td><strong>63.1%</strong></td><td><strong>29.4%</strong></td><td><strong>7.5%</strong></td></tr>
<tr><td>σ (3-day %)</td><td><strong>2.22%</strong></td><td><strong>2.99%</strong></td><td><strong>7.61%</strong></td></tr>
<tr><td>Median |3-day %|</td><td>2.18%</td><td>3.13%</td><td>8.80%</td></tr>
<tr><td>CDX level (median)</td><td>~63 bps</td><td>~71 bps</td><td>~70 bps</td></tr>
<tr><td>ρ(CDX Δ, NDQ)</td><td>−0.74</td><td>−0.82</td><td>−0.67</td></tr>
</tbody></table></div>
{chart_block("cdx_regimes.png")}

<h3>3.2 Granger causality (Table 2)</h3>
<div class="table-scroll"><table>
<thead><tr><th>Regime</th><th>CDX→NDQ F</th><th>p-value</th><th>Predicts?</th></tr></thead>
<tbody>
<tr><td>Low-Stress</td><td>2.13</td><td>0.095</td><td class="rating-no">No</td></tr>
<tr><td>Moderate-Stress</td><td>5.19</td><td>0.001</td><td class="rating-yes">Yes</td></tr>
<tr><td>High-Stress</td><td>4.99</td><td>0.002</td><td class="rating-yes">Yes</td></tr>
</tbody></table></div>
<p>NASDAQ→CDX F-stats are larger in every regime (mechanical co-movement). The claim is narrowly about forward CDX→NASDAQ significance in stress.</p>
{chart_block("cdx_granger_regimes.png")}

<h3>3.3 Robustness (six specifications)</h3>
<div class="table-scroll"><table>
<thead><tr><th>Specification</th><th>Low</th><th>Moderate</th><th>High</th></tr></thead>
<tbody>
<tr><td>1-day Δ (bps)</td><td>no</td><td>yes</td><td>yes</td></tr>
<tr><td>3-day Δ (bps)</td><td>no</td><td>yes</td><td>yes</td></tr>
<tr><td>5-day Δ (bps)</td><td>no</td><td>yes</td><td>no</td></tr>
<tr><td>1-day %</td><td>marginal</td><td>yes</td><td>yes</td></tr>
<tr><td><strong>3-day %</strong></td><td><strong>no</strong></td><td><strong>yes (6/6)</strong></td><td><strong>yes (4/6)</strong></td></tr>
<tr><td>5-day %</td><td>no</td><td>yes</td><td>no</td></tr>
</tbody></table></div>

<h3>3.4 Asymmetry: peak vs trough</h3>
<div class="table-scroll"><table>
<thead><tr><th>Phase</th><th>CDX role</th><th>Mechanism</th></tr></thead>
<tbody>
<tr><td>Into drawdown</td><td>Widening <strong>coincident</strong></td><td>85–91% NASDAQ already falling; median 28d to trough</td></tr>
<tr><td>Out of drawdown</td><td>Tightening in High-Stress <strong>leading</strong></td><td>Credit reprices before equities recover</td></tr>
</tbody></table></div>

<h3>3.5 Confirmed tightening performance</h3>
<h4>Table 5a — accuracy</h4>
<div class="table-scroll"><table>
<thead><tr><th>Horizon</th><th>Recovery</th><th>Kept falling</th></tr></thead>
<tbody>
<tr><td>5 trading days</td><td>63.8%</td><td>36.2%</td></tr>
<tr><td>10 trading days</td><td>73.8%</td><td>26.2%</td></tr>
<tr><td>20 trading days</td><td><strong>75.5%</strong></td><td>24.5%</td></tr>
<tr><td>20d (99 episodes)</td><td><strong>68%</strong></td><td>32%</td></tr>
</tbody></table></div>

<h4>Table 5b — single vs confirmed</h4>
<div class="table-scroll"><table>
<thead><tr><th>Signal</th><th>n</th><th>Mean fwd 20d</th><th>P(up) 20d</th></tr></thead>
<tbody>
<tr><td>Single tightening</td><td>61</td><td>+0.72%</td><td>64%</td></tr>
<tr><td>Confirmed tightening</td><td>359</td><td><strong>+2.43%</strong></td><td><strong>75%</strong></td></tr>
</tbody></table></div>

<h4>Table 5d — out-of-sample</h4>
<div class="table-scroll"><table>
<thead><tr><th>Cohort</th><th>n</th><th>Mean fwd 20d</th><th>P(up) 20d</th></tr></thead>
<tbody>
<tr><td>In-sample confirmed (≤2022)</td><td>298</td><td>+1.90%</td><td>73%</td></tr>
<tr><td><strong>OOS confirmed (2023–26)</strong></td><td><strong>61</strong></td><td><strong>+5.01%</strong></td><td><strong>85%</strong></td></tr>
<tr><td>OOS episodes (bootstrap)</td><td>17</td><td>+3.09%</td><td>p=0.001</td></tr>
<tr><td>Real-time High-Stress filter</td><td>9</td><td>+6.36%</td><td>9/9 positive</td></tr>
</tbody></table></div>
{chart_block("cdx_recovery_signal.png")}

<h3>3.6 Event study (11 corrections)</h3>
<ul>
  <li>Median drawdown: <strong>−13.1%</strong> · duration: <strong>42</strong> trading days</li>
  <li>Widening: median <strong>12</strong> days after peak; <strong>28</strong> days before trough</li>
  <li>Confirmed tightening: median <strong>3</strong> days from trough (8/11 within one week)</li>
  <li>CDX move vs drawdown: <strong>r = −0.85</strong></li>
</ul>

<h4>Table 6a excerpt</h4>
<div class="table-scroll"><table>
<thead><tr><th>Event</th><th>CDX peak</th><th>CDX move %</th><th>NDQ DD</th></tr></thead>
<tbody>
<tr><td>2020 COVID</td><td>152 bps</td><td>+203%</td><td>−30.1%</td></tr>
<tr><td>2018 Q4</td><td>95 bps</td><td>+37%</td><td>−18.2%</td></tr>
<tr><td>2022 Rates</td><td>102 bps</td><td>+17%</td><td>−17.9%</td></tr>
<tr><td>2023 SVB</td><td>91 bps</td><td>+24%</td><td>−8.0%</td></tr>
<tr><td>2024 Yen-carry</td><td>61 bps</td><td>+26%</td><td>−13.1%</td></tr>
<tr><td>2025 Tariff</td><td>81 bps</td><td>+46%</td><td>−17.7%</td></tr>
<tr><td>2026 Middle East</td><td>68 bps</td><td>+36%</td><td>−12.8%</td></tr>
</tbody></table></div>

<h4>Table 6b excerpt</h4>
<div class="table-scroll"><table>
<thead><tr><th>Event</th><th>NDQ trough</th><th>Signal</th><th>Days to trough</th><th>NDQ +20d</th></tr></thead>
<tbody>
<tr><td>2020 COVID</td><td>2020-03-23</td><td>2020-03-23</td><td>at trough</td><td>+20.4%</td></tr>
<tr><td>2018 Q4</td><td>2018-12-24</td><td>2018-12-28</td><td>2 after</td><td>+6.7%</td></tr>
<tr><td>2023 SVB</td><td>2023-03-10</td><td>2023-03-06</td><td>4 before</td><td>+4.4%</td></tr>
<tr><td>2025 Tariff</td><td>2025-04-08</td><td>2025-04-09</td><td>1 after</td><td>+4.7%</td></tr>
<tr><td>2022 Ukraine</td><td>2022-04-29</td><td>2022-03-30</td><td>21 before</td><td>−10.9%</td></tr>
</tbody></table></div>
{chart_block("cdx_drawdown_scatter.png")}

<div class="callout warn">
  <strong>Caveat:</strong> Magnitude–depth correlation is measured at CDX peak (hindsight). At first widening signal, ultimate CDX move size is unknown—severity must be updated dynamically.
</div>
</section>

<section id="strategy">
<p class="section-label">Section 4</p>
<h2>Trading Strategy — CDX Overlay for NASDAQ</h2>
<p>Rules-based <strong>risk overlay</strong>, not standalone alpha. Operational translation of Sections 6–8.</p>

<h3>4.1 Daily inputs</h3>
<div class="table-scroll"><table>
<thead><tr><th>Input</th><th>Source</th><th>Frequency</th></tr></thead>
<tbody>
<tr><td>CDX NA IG 5Y spread</td><td>Markit/Bloomberg</td><td>Daily close</td></tr>
<tr><td>NASDAQ Composite</td><td>Market data</td><td>Daily close</td></tr>
<tr><td>Regime probabilities</td><td>MS-VAR filtered</td><td>Daily</td></tr>
<tr><td>3-day CDX % change</td><td>Computed</td><td>Daily</td></tr>
</tbody></table></div>

<h3>4.2 Regime assessment</h3>
<ol>
  <li>Load 3-state regime probabilities from MS-VAR.</li>
  <li><strong>Calm:</strong> Low-Stress dominant.</li>
  <li><strong>Elevated:</strong> Moderate- or High-Stress dominant.</li>
  <li><strong>Acute:</strong> High-Stress probability &gt; 50%.</li>
</ol>

<h3>4.3 Position states</h3>
<p>Core weight W<sub>core</sub>; effective weight W<sub>t</sub> ∈ [W<sub>min</sub>, W<sub>core</sub>].</p>
<div class="table-scroll"><table>
<thead><tr><th>State</th><th>Default W<sub>t</sub></th></tr></thead>
<tbody>
<tr><td>Calm</td><td>W<sub>core</sub> (full)</td></tr>
<tr><td>Stress — defensive</td><td>W<sub>core</sub> − Δ<sub>t</sub></td></tr>
<tr><td>Post-recovery rebuild</td><td>Ramp toward W<sub>core</sub></td></tr>
</tbody></table></div>

<h3>4.4 Defensive trim (widening)</h3>
<p><strong>Triggers (all required):</strong></p>
<ol>
  <li>3-day CDX % &gt; +3%</li>
  <li>Regime is Moderate- or High-Stress</li>
  <li>Optional: NASDAQ already in drawdown</li>
</ol>
<p><strong>Illustrative sizing tiers:</strong></p>
<div class="table-scroll"><table>
<thead><tr><th>CDX % move (cumulative)</th><th>Illustrative trim Δ<sub>t</sub></th></tr></thead>
<tbody>
<tr><td>+3% to +10%</td><td>10–15% of W<sub>core</sub></td></tr>
<tr><td>+10% to +30%</td><td>20–35%</td></tr>
<tr><td>&gt; +30%</td><td>40–50% (cap per mandate)</td></tr>
</tbody></table></div>

<h3>4.5 Hold through stress</h3>
<p>Maintain reduced weight in Moderate/High-Stress without recovery signal. Monitor CDX velocity daily; cross-check VIX, MOVE, news flow.</p>

<h3>4.6 Rebuild (confirmed tightening)</h3>
<p><strong>Triggers:</strong> High-Stress regime + 3-day CDX % &lt; −5% + second tightening within 20 days.</p>
<p><strong>Action:</strong> Scale back toward W<sub>core</sub> over 5–20 trading days. Expect +2% to +5% mean 20d forward return—probabilistic (~25% false at 20d).</p>
<p><strong>False signals:</strong> 2022 Ukraine/rates had second selling leg ~3 weeks after early tightening. Ignore tightening-only signals in Low/Moderate stress.</p>

<h3>4.7 Optional CDX hedge</h3>
<div class="table-scroll"><table>
<thead><tr><th>Phase</th><th>Credit action</th></tr></thead>
<tbody>
<tr><td>Moderate/High + widening</td><td>Buy CDX protection, sized to equity trim</td></tr>
<tr><td>Confirmed High-Stress tightening</td><td>Unwind protection as equities rebuilt</td></tr>
</tbody></table></div>

<h3>4.8 What NOT to do</h3>
<ul>
  <li>Do not trade CDX signals in Low-Stress (whipsaw)</li>
  <li>Do not expect prediction from calm markets (widening lags peak ~12 days)</li>
  <li>Do not treat as alpha vs buy-and-hold</li>
  <li>Do not use spread level alone—velocity regime matters</li>
</ul>

<h3>4.9 Agent decision tree</h3>
<pre>IF regime == Low-Stress:
    W = W_core
ELIF widening (+3% 3d) AND regime in {{Moderate, High}}:
    W = W_core - scale_trim(CDX_move_magnitude)
ELIF regime == High-Stress AND confirmed_tightening (-5% twice in 20d):
    W -> ramp toward W_core over 5-20d
ELSE:
    hold W</pre>
</section>

<section id="literature">
<p class="section-label">Section 5</p>
<h2>Literature and External Research Context</h2>
<div class="table-scroll"><table>
<thead><tr><th>Study</th><th>Relevance</th></tr></thead>
<tbody>
<tr><td>Norden &amp; Weber (2009)</td><td>Equities often lead CDS unconditionally</td></tr>
<tr><td>Hilscher et al. (2015)</td><td>Equity leads credit at high frequency</td></tr>
<tr><td>Forte &amp; Peña (2009)</td><td>Leadership reverses in stress</td></tr>
<tr><td>Alexander &amp; Kaeck (2008)</td><td>Regime-dependent CDS–equity sensitivity</td></tr>
<tr><td>Gilchrist &amp; Zakrajšek (2012)</td><td>Credit spreads predict macro/risk assets</td></tr>
</tbody></table></div>
<p><strong>Reconciliation:</strong> Unconditional tests miss state dependence. CDX leads NASDAQ only when velocity volatility is elevated.</p>
<p><strong>Open gap:</strong> Multivariate model with VIX, MOVE, and Cboe Credit VIX (VIXIG/VIXHY, since Oct 2023).</p>
</section>

<section id="opinion">
<p class="section-label">Section 6</p>
<h2>Opinion (Credit Trader View)</h2>

<h3>6.1 What the paper gets right</h3>
<ul>
  <li><strong>In-stress overlay framing</strong> matches desk practice</li>
  <li><strong>Velocity-based regimes</strong> are a genuine contribution vs level buckets</li>
  <li><strong>Asymmetry</strong> (coincident widening vs leading tightening) is economically coherent</li>
  <li><strong>Honest limitations</strong> — does not oversell OOS results</li>
</ul>

<h3>6.2 Skepticisms</h3>
<ul>
  <li>Regime probabilities are hard to deploy live without frozen specs and roll handling</li>
  <li>NASDAQ-specific; linkage may differ for SPX/value/non-US</li>
  <li>Transaction costs and basis risk not modeled</li>
  <li>VIX/MOVE confounders not in baseline model</li>
  <li>2026 Middle East event partially in-sample</li>
</ul>

<h3>6.3 Overall assessment</h3>
<div class="table-scroll"><table>
<thead><tr><th>Dimension</th><th>Rating</th><th>Comment</th></tr></thead>
<tbody>
<tr><td>Economic intuition</td><td>Strong</td><td>Credit-as-macrorisk framing</td></tr>
<tr><td>Econometric care</td><td>Strong</td><td>Regime conditioning, OOS, clustering</td></tr>
<tr><td>Practical tradability</td><td>Moderate–Strong</td><td>Rules clear; regime estimation hard</td></tr>
<tr><td>Novel alpha claim</td><td>Weak (appropriately)</td><td>Risk management framing</td></tr>
<tr><td>Generalizability</td><td>Moderate</td><td>NASDAQ + CDX IG only</td></tr>
</tbody></table></div>
<p><strong>Bottom line:</strong> One of the more operationally useful academic treatments of CDX–equity linkage. Suitable as a risk overlay specification pending independent backtest with costs and multivariate controls.</p>
</section>

<section id="next">
<p class="section-label">Section 7</p>
<h2>Next Steps and Improvements</h2>

<h3>7.1 For researchers</h3>
<ol>
  <li>Multivariate MS-VAR with VIX, MOVE, Credit VIX</li>
  <li>CDX HY and iTraxx Europe extensions</li>
  <li>Formal portfolio backtest with turnover penalties</li>
  <li>Bootstrap regime stability across CDX rolls</li>
  <li>Publish replication code and data</li>
</ol>

<h3>7.2 For practitioners</h3>
<ol>
  <li>Prototype daily signal engine (velocity, regime, W<sub>t</sub> band)</li>
  <li>Paper trade 6–12 months; log false positives</li>
  <li>Define Mar/Sep roll protocol</li>
  <li>Stress-test 2022-type second-leg paths</li>
  <li>Floor exposure (e.g. never below 50% W<sub>core</sub>)</li>
</ol>

<h3>7.3 Agent parameters</h3>
<div class="table-scroll"><table>
<thead><tr><th>Field</th><th>Value</th></tr></thead>
<tbody>
<tr><td>signal.widening_threshold_3d_pct</td><td>0.03</td></tr>
<tr><td>signal.tightening_threshold_3d_pct</td><td>-0.05</td></tr>
<tr><td>signal.confirmation_window_days</td><td>20</td></tr>
<tr><td>regime.high_stress.sigma_3d_pct</td><td>0.0761</td></tr>
<tr><td>recovery.confirmed.fwd_20d_mean_pct</td><td>2.43</td></tr>
<tr><td>recovery.confirmed.oos_fwd_20d_mean_pct</td><td>5.01</td></tr>
<tr><td>drawdown.cdx_move_vs_ndq_dd_correlation</td><td>-0.85</td></tr>
<tr><td>sample.n_obs</td><td>3668</td></tr>
</tbody></table></div>
</section>

<section id="conclusion">
<p class="section-label">Section 8</p>
<h2>Conclusion</h2>
<p>Nguyen (2026) provides a coherent framework for using <strong>CDX NA IG spread velocity</strong>—not level—to manage <strong>NASDAQ</strong> exposure through stress: <strong>confirm</strong> drawdowns with widening in elevated regimes, <strong>size</strong> defense using CDX move magnitude, and <strong>rebuild</strong> on confirmed tightening in high-stress regimes.</p>
<p>For AI agents: treat regime classification and confirmation logic as first-class state machines; treat hit rates as probabilistic priors, not all-in/all-out triggers.</p>
</section>

<section id="sources">
<p class="section-label">References</p>
<h2>Sources</h2>
<h3>Primary</h3>
<p>Nguyen, T. (2026). <em>CDX NA IG and NASDAQ Under Stress: Managing Drawdown and Recovery Risk with Credit-Market Signals.</em> Working Paper.</p>
<h3>Web (retrieved 2026-06-10)</h3>
<ul>
  <li><a href="https://www.ice.com/products/28555645/Markit-CDXNAIG">ICE Markit CDX.NA.IG</a></li>
  <li><a href="https://cbonds.com/indexes/204395/">CDX.NA.IG 5Y index (~58.9 bps, Mar 2026)</a></li>
  <li><a href="https://www.algonquincap.com/wp-content/uploads/2025/06/20250530.pdf">Algonquin Capital — CDX IG spread history</a></li>
  <li><a href="https://solvefixedincome.com/resources/investment-grade-cds-market-summary-december-2025/">SOLVE — IG CDS Summary Dec 2025</a></li>
</ul>
</section>

<footer class="report-footer">
  <p>Generated 2026-06-10 · Self-contained HTML with embedded charts · Not investment advice.</p>
</footer>

</main>
</body>
</html>
"""

if __name__ == "__main__":
    OUT.write_text(HTML, encoding="utf-8")
    size_kb = OUT.stat().st_size / 1024
    print(f"Wrote {OUT} ({size_kb:.0f} KB)")
