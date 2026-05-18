"""gen_summary.py — Generate SUMMARY.html (human) and AGENT_BRIEF.md (AI agent)."""
from pathlib import Path

HERE = Path(__file__).resolve().parent

def svg(name: str) -> str:
    return (HERE / name).read_text()

# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Long Directional BTC Options — Research Summary</title>
<style>
  :root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --border: #2e3148;
    --accent: #6c8ebf;
    --green: #59a14f;
    --red: #e15759;
    --orange: #f28e2b;
    --text: #dce1ec;
    --muted: #8891a8;
    --code-bg: #141720;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; font-size: 15px; line-height: 1.65; padding: 0 0 80px; }}
  .hero {{ background: linear-gradient(135deg, #12162a 0%, #1a1d27 100%); border-bottom: 1px solid var(--border); padding: 52px 48px 44px; }}
  .hero h1 {{ font-size: 2.1rem; font-weight: 700; color: #fff; letter-spacing: -0.5px; margin-bottom: 10px; }}
  .hero .sub {{ color: var(--muted); font-size: 0.95rem; }}
  .hero .badges {{ margin-top: 18px; display: flex; gap: 10px; flex-wrap: wrap; }}
  .badge {{ background: var(--surface); border: 1px solid var(--border); border-radius: 20px; padding: 4px 14px; font-size: 0.82rem; color: var(--muted); }}
  .badge.green {{ border-color: var(--green); color: var(--green); }}
  .badge.orange {{ border-color: var(--orange); color: var(--orange); }}
  .badge.red {{ border-color: var(--red); color: var(--red); }}
  .container {{ max-width: 1140px; margin: 0 auto; padding: 0 36px; }}
  h2 {{ font-size: 1.35rem; font-weight: 600; color: #fff; margin: 52px 0 16px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }}
  h3 {{ font-size: 1.05rem; font-weight: 600; color: var(--accent); margin: 28px 0 10px; }}
  p {{ color: var(--text); margin-bottom: 12px; }}
  .callout {{ background: var(--surface); border-left: 4px solid var(--accent); border-radius: 0 6px 6px 0; padding: 16px 20px; margin: 20px 0; }}
  .callout.green {{ border-color: var(--green); }}
  .callout.orange {{ border-color: var(--orange); }}
  .callout strong {{ color: #fff; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0 24px; font-size: 0.88rem; }}
  th {{ background: #1f2235; color: var(--muted); text-align: left; padding: 9px 12px; font-weight: 600; border-bottom: 2px solid var(--border); }}
  td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); color: var(--text); }}
  tr:hover td {{ background: #1e2133; }}
  td.hi {{ color: var(--green); font-weight: 600; }}
  td.lo {{ color: var(--red); }}
  td.mid {{ color: var(--orange); }}
  code {{ background: var(--code-bg); border: 1px solid var(--border); border-radius: 4px; padding: 2px 7px; font-size: 0.85em; color: #aac8ff; font-family: 'JetBrains Mono', 'Fira Code', monospace; }}
  pre {{ background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px; padding: 18px 20px; overflow-x: auto; margin: 14px 0 24px; font-size: 0.84rem; line-height: 1.55; color: #aac8ff; font-family: 'JetBrains Mono', 'Fira Code', monospace; }}
  .chart-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin: 20px 0 32px; }}
  .chart-grid.wide {{ grid-template-columns: 1fr; }}
  .chart-box {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; overflow: hidden; }}
  .chart-box h4 {{ font-size: 0.82rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px; }}
  .chart-box svg {{ width: 100%; height: auto; display: block; }}
  .timeline {{ position: relative; padding-left: 28px; margin: 8px 0; }}
  .timeline::before {{ content: ''; position: absolute; left: 7px; top: 6px; bottom: 6px; width: 2px; background: var(--border); }}
  .tl-item {{ position: relative; margin-bottom: 18px; }}
  .tl-item::before {{ content: ''; position: absolute; left: -24px; top: 6px; width: 10px; height: 10px; background: var(--accent); border-radius: 50%; border: 2px solid var(--bg); }}
  .tl-item.done::before {{ background: var(--green); }}
  .tl-label {{ font-size: 0.78rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 3px; }}
  .tl-text {{ color: var(--text); font-size: 0.9rem; }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 16px 0 28px; }}
  .stat-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px 18px; }}
  .stat-card .val {{ font-size: 1.8rem; font-weight: 700; color: #fff; line-height: 1; margin-bottom: 5px; }}
  .stat-card .val.green {{ color: var(--green); }}
  .stat-card .val.orange {{ color: var(--orange); }}
  .stat-card .lbl {{ font-size: 0.78rem; color: var(--muted); }}
  .file-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin: 12px 0; }}
  .file-item {{ background: var(--code-bg); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; font-size: 0.82rem; }}
  .file-item .fname {{ color: #aac8ff; font-family: monospace; }}
  .file-item .fdesc {{ color: var(--muted); font-size: 0.76rem; margin-top: 2px; }}
  @media (max-width: 800px) {{
    .chart-grid, .stat-grid, .file-grid {{ grid-template-columns: 1fr; }}
    .hero {{ padding: 32px 20px 28px; }}
    .container {{ padding: 0 16px; }}
  }}
</style>
</head>
<body>

<div class="hero">
  <div class="container">
    <h1>Long Directional BTC Options</h1>
    <div class="sub">Deribit BTC options · 2026-01-01 → 2026-05-12 · Scripts 01–10 complete</div>
    <div class="badges">
      <span class="badge green">87.2% base rate (MTF-high)</span>
      <span class="badge green">+7.3% EV per trade</span>
      <span class="badge orange">~11 trades / month</span>
      <span class="badge">15,347 tradeable / 26,354 candidates</span>
      <span class="badge">379 days of spot · 546k 1-min bars</span>
    </div>
  </div>
</div>

<div class="container">

<!-- ── EXECUTIVE SUMMARY ─────────────────────────────────────────────────── -->
<h2>Executive Summary</h2>
<p>We ran a systematic backwards analysis of BTC Deribit options to identify conditions under which
buying a directional option at the ask is EV-positive after fees. An option entry is labelled
<strong>tradeable</strong> if its bid price reaches ≥ 1.20× the entry ask before expiry − 1h.
The dataset spans 26,354 candidate entries across all 4h UTC boundaries from Jan to May 2026.</p>

<div class="stat-grid">
  <div class="stat-card"><div class="val green">87.2%</div><div class="lbl">Base rate — best entry kernel (MTF-high)</div></div>
  <div class="stat-card"><div class="val green">+7.3%</div><div class="lbl">EV per trade at TP=2.0× (MTF-high)</div></div>
  <div class="stat-card"><div class="val orange">2.43×</div><div class="lbl">Median winner peak (entry ask multiple)</div></div>
  <div class="stat-card"><div class="val">5.4h</div><div class="lbl">Median hold time to first 1.2× crossover</div></div>
</div>

<div class="callout green">
  <strong>First EV-proven entry kernel:</strong><br>
  Spread ≤ 10% of mark &nbsp;+&nbsp; 4h aligned momentum ≥ 1.5% &nbsp;+&nbsp; 1h aligned momentum ≥ 0.5%<br>
  DTE 4–5 · delta 0.30–0.40 · Take profit at 2.0× entry ask · ~11 trades/month
</div>

<!-- ── WORKFLOW TIMELINE ──────────────────────────────────────────────────── -->
<h2>Research Workflow</h2>
<div class="timeline">
  <div class="tl-item done">
    <div class="tl-label">Script 01 — Scan</div>
    <div class="tl-text">Scanned all Deribit 5-min option snapshots (DTE 1–7, |delta| 0.10–0.40, ask ≥ $75) across 4h entry boundaries.
    Labelled 15,347 / 26,354 candidates as tradeable. Skip reasons: 35.1% never hit 1.2×, 4.9% fee-killed, 1.8% ask too low.</div>
  </div>
  <div class="tl-item done">
    <div class="tl-label">Script 02 — Enrich context</div>
    <div class="tl-text">For every tradeable trade, located the first 1.2× crossover snapshot and captured hold_hours, exit_bid, gross_gain_pct,
    net_pnl_usd, entry_hour_utc, entry_date, plus prior spot momentum at 1h / 4h / 24h windows. Built <code>tradeable_longs_enriched.parquet</code>.</div>
  </div>
  <div class="tl-item done">
    <div class="tl-label">Script 03 — Frequency stats</div>
    <div class="tl-text">Base rate by DTE, delta, and side. Sweet spot: DTE 4–5 (63–68%), delta ≥ 0.30 (67–69%), calls ≈ puts (58.6% vs 60.0%).
    Delta 0.10 options ($18 median PnL) are borderline uneconomical.</div>
  </div>
  <div class="tl-item done">
    <div class="tl-label">Script 04 — Timing analysis</div>
    <div class="tl-text">Best entry hour: 12:00 UTC (63.6%, resolves in 3.2h median — 2h before NY open). Best day: Sunday (66.3%).
    Saturday entries are slowest (11.3h median). Built hour × DTE heatmap.</div>
  </div>
  <div class="tl-item done">
    <div class="tl-label">Script 05 — Vol regime</div>
    <div class="tl-text">Measured implied vs realised vol (IV − HV24). Negative IV-premium is the norm: 58% of entries have IV below realised vol,
    meaning options are often cheap vs realised. Note: HV scaling bug found (sqrt factor) — ordinal rankings unaffected.</div>
  </div>
  <div class="tl-item done">
    <div class="tl-label">Script 06 — Entry quality</div>
    <div class="tl-text">Bid-ask spread ≤ 10% of mark is the single strongest filter: +9pp base rate uplift (58.2% → 67.2%).
    Spread also highly predictive of loser quality — wide-spread options almost never trade profitably.</div>
  </div>
  <div class="tl-item done">
    <div class="tl-label">Script 07 — Momentum features (Phase 0)</div>
    <div class="tl-text">Computed spot_30m / 1h / 4h / 24h prior momentum for all 26,354 candidates.
    Tight spread + 4h ≥ 0.3% + 1h ≥ 0.5% → 80.6% at 0.93 windows/day.
    Tight spread + 4h ≥ 1.5% + 1h ≥ 0.5% → 79.7%.</div>
  </div>
  <div class="tl-item done">
    <div class="tl-label">Script 08 — MTF heatmap (Phase 1)</div>
    <div class="tl-text">Full 4h × 1h cross-tabulation for calls and puts separately.
    Key finding: puts neutral 4h + 1h just starting down (−1.5–−0.5%) → <strong>93.5%</strong> (early-move entry).
    Both-aligned ≥ 1.5% + 1h ≥ 0.5% → <strong>87.2%</strong>. Counter-direction penalties confirmed: 28–47%.</div>
  </div>
  <div class="tl-item done">
    <div class="tl-label">Script 09 — Winner magnitude</div>
    <div class="tl-text">Full rescan of all 15,347 winners across every snapshot to find peak_multiple (not just first 1.2× cross).
    Median peak 2.43×, mean 3.93×. EV table confirms: MTF-high at TP=2.0× → <strong>+7.3%/trade</strong>. Break-even base rate = 81.3%.</div>
  </div>
  <div class="tl-item done">
    <div class="tl-label">Script 10 — Stop calibration</div>
    <div class="tl-text">MAE (max adverse spot excursion) computed for all 15,347 winners using 546k rows of 1-min spot data.
    Peak ≥ 2× winners: p50 MAE only 0.96%. Stop −2.0% preserves 74% of big winners while catching 15% of losers.
    Time gate at 36h catches 93% of winners. Joint grid produced.</div>
  </div>
</div>

<!-- ── KEY FINDINGS ───────────────────────────────────────────────────────── -->
<h2>Key Statistical Findings</h2>

<h3>Baseline (no filter)</h3>
<table>
  <tr><th>Metric</th><th>Value</th></tr>
  <tr><td>Total candidates</td><td>26,354</td></tr>
  <tr><td>Tradeable (bid ≥ 1.20× ask before expiry−1h)</td><td class="hi">15,347 (58.2%)</td></tr>
  <tr><td>Never hit 1.2×</td><td class="lo">9,244 (35.1%)</td></tr>
  <tr><td>Fee-killed</td><td class="lo">1,281 (4.9%)</td></tr>
  <tr><td>Median hold to first 1.2× cross</td><td>5.4h</td></tr>
  <tr><td>p90 hold time</td><td>30.1h</td></tr>
  <tr><td>Calls base rate</td><td>58.6%</td></tr>
  <tr><td>Puts base rate</td><td>60.0%</td></tr>
</table>

<h3>Filter progression (spread ≤ 10% + MTF momentum)</h3>
<table>
  <tr><th>Filter</th><th>Base rate</th><th>Windows/day</th><th>Trades/month</th></tr>
  <tr><td>None</td><td class="lo">58.2%</td><td>~6.6</td><td>~200</td></tr>
  <tr><td>Spread ≤ 10%</td><td class="mid">67.2%</td><td>—</td><td>—</td></tr>
  <tr><td>Spread + 4h ≥ 0.3% + 1h ≥ 0.5%</td><td class="mid">80.6%</td><td>0.93</td><td>~28</td></tr>
  <tr><td>Spread + 4h ≥ 1.5% + 1h ≥ 0.5%</td><td class="hi">87.2%</td><td>0.36</td><td>~11</td></tr>
  <tr><td>Spread + 4h ≥ 2.0% + 1h ≥ 0.5%</td><td class="hi">90.3%</td><td>0.23</td><td>~7</td></tr>
</table>

<h3>EV at TP = 2.0× (EV = base_rate × f(TP) × TP − 1)</h3>
<table>
  <tr><th>Base rate (filter)</th><th>% of winners reaching 2.0×</th><th>EV at TP=2.0×</th></tr>
  <tr><td>58.2% — no filter</td><td>61.5%</td><td class="lo">−28.4%</td></tr>
  <tr><td>67.2% — spread only</td><td>61.5%</td><td class="lo">−17.3%</td></tr>
  <tr><td>80.6% — MTF kernel</td><td>61.5%</td><td class="lo">−0.8%</td></tr>
  <tr><td class="hi">87.2% — MTF-high</td><td>61.5%</td><td class="hi">+7.3%</td></tr>
</table>
<p style="color: var(--muted); font-size:0.85rem">Break-even base rate at TP=2.0×: 81.3%. Winners fraction reaching TP: 1.5×=81.7%, 1.75×=70.2%, 2.0×=61.5%, 3.0×=39.8%.</p>

<h3>Winner peak magnitude</h3>
<table>
  <tr><th>Percentile</th><th>Peak multiple</th></tr>
  <tr><td>Median (p50)</td><td class="hi">2.43×</td></tr>
  <tr><td>Mean</td><td class="hi">3.93×</td></tr>
  <tr><td>p75</td><td>4.38×</td></tr>
  <tr><td>p90</td><td>7.40×</td></tr>
  <tr><td>p99</td><td>25.64×</td></tr>
</table>

<h3>Stop calibration: MAE of winners</h3>
<table>
  <tr><th>Group</th><th>p50 MAE</th><th>p90 MAE</th><th>Safe at −1.5%</th><th>Safe at −2.0%</th><th>Safe at −2.5%</th></tr>
  <tr><td>Calls — peak ≥ 2×</td><td>0.99%</td><td>3.40%</td><td class="mid">65%</td><td class="hi">75%</td><td class="hi">83%</td></tr>
  <tr><td>Puts  — peak ≥ 2×</td><td>0.93%</td><td>3.60%</td><td class="mid">65%</td><td class="hi">75%</td><td class="hi">81%</td></tr>
  <tr><td>Calls — peak &lt; 2×</td><td>2.81%</td><td>7.70%</td><td class="lo">21%</td><td class="lo">31%</td><td class="lo">44%</td></tr>
  <tr><td>All winners</td><td>1.58%</td><td>5.50%</td><td>48%</td><td class="mid">58%</td><td class="mid">67%</td></tr>
</table>

<h3>Stop selectivity: losers vs winners (checked 8h after entry)</h3>
<table>
  <tr><th>Adverse stop</th><th>Losers stopped</th><th>Winners stopped</th><th>Selectivity gap</th></tr>
  <tr><td>−1.0%</td><td class="mid">33.6%</td><td class="lo">8.5%</td><td>25pp</td></tr>
  <tr><td>−1.5%</td><td class="mid">22.7%</td><td>4.7%</td><td>18pp</td></tr>
  <tr><td><strong>−2.0%</strong></td><td>15.3%</td><td class="hi">2.2%</td><td class="hi">13pp</td></tr>
  <tr><td>−2.5%</td><td>11.4%</td><td class="hi">1.3%</td><td>10pp</td></tr>
</table>

<h3>Time gate CDF</h3>
<table>
  <tr><th>Gate</th><th>All winners showing ≥1.2×</th><th>Peak ≥ 2× showing ≥1.2×</th></tr>
  <tr><td>8h</td><td>60%</td><td>59%</td></tr>
  <tr><td>12h</td><td>71%</td><td>69%</td></tr>
  <tr><td>24h</td><td>86%</td><td>85%</td></tr>
  <tr><td><strong>36h</strong></td><td class="hi"><strong>93%</strong></td><td class="hi"><strong>93%</strong></td></tr>
  <tr><td>48h</td><td>96%</td><td>96%</td></tr>
</table>

<!-- ── CHARTS ────────────────────────────────────────────────────────────── -->
<h2>Charts</h2>

<div class="chart-grid wide">
  <div class="chart-box">
    <h4>Frequency overview — base rate by DTE, delta, side</h4>
    {svg("freq_overview.svg")}
  </div>
</div>

<div class="chart-grid">
  <div class="chart-box">
    <h4>Phase 0 — momentum filter analysis</h4>
    {svg("phase0_overview.svg")}
  </div>
  <div class="chart-box">
    <h4>Phase 1 — MTF alignment heatmap</h4>
    {svg("phase1_overview.svg")}
  </div>
</div>

<div class="chart-grid wide">
  <div class="chart-box">
    <h4>Winner magnitude — peak multiple distribution and EV table</h4>
    {svg("magnitude_overview.svg")}
  </div>
</div>

<div class="chart-grid wide">
  <div class="chart-box">
    <h4>Stop calibration — MAE, time gate, loser check, joint grid</h4>
    {svg("stop_calibration.svg")}
  </div>
</div>

<div class="chart-grid">
  <div class="chart-box">
    <h4>Timing — hour × DTE heatmap</h4>
    {svg("timing_heatmap.svg")}
  </div>
  <div class="chart-box">
    <h4>Volatility regime</h4>
    {svg("vol_regime.svg")}
  </div>
</div>

<div class="chart-grid">
  <div class="chart-box">
    <h4>Timing overview</h4>
    {svg("timing_overview.svg")}
  </div>
  <div class="chart-box">
    <h4>Entry quality (spread analysis)</h4>
    {svg("entry_quality.svg")}
  </div>
</div>

<!-- ── STRATEGY SPEC ──────────────────────────────────────────────────────── -->
<h2>Final Strategy Specification</h2>

<div class="callout green">
  <strong>Entry (all conditions required):</strong><br>
  ① Spread ≤ 10% of mark price &nbsp; ② DTE 4–5 at entry &nbsp; ③ |delta| 0.30–0.40<br>
  ④ 4h prior BTC spot move ≥ 1.5% in trade direction &nbsp; ⑤ 1h prior BTC spot move ≥ 0.5% in trade direction
</div>

<div class="callout">
  <strong>Take profit:</strong> Exit when option bid ≥ entry_ask × 2.0 (checked every 5-min snapshot)
</div>

<div class="callout orange">
  <strong>Stop loss A — spot adverse excursion:</strong> Exit when BTC spot moves ≥ 2.0% against trade direction from entry spot.
  Measured on 1-min closes. Preserves 74–75% of peak ≥ 2× winners; stops only 2.2% of winners within 8h.
</div>

<div class="callout orange">
  <strong>Stop loss B — time gate:</strong> Exit 36h after entry if bid &lt; entry_ask × 1.30 (not yet 30% in profit).
  93% of all winners have already shown ≥1.2× momentum by 36h; holding further consumes theta at DTE 4–5.
</div>

<h3>Backtester parameter grid</h3>
<table>
  <tr><th>Parameter</th><th>Grid values</th><th>Default</th></tr>
  <tr><td><code>4h_momentum_thr</code> (%)</td><td>0.3, 0.5, 1.0, 1.5, 2.0</td><td class="hi">1.5</td></tr>
  <tr><td><code>1h_momentum_thr</code> (%)</td><td>0.3, 0.5, 1.0</td><td class="hi">0.5</td></tr>
  <tr><td><code>spread_max_pct</code></td><td>5, 10, 15</td><td class="hi">10</td></tr>
  <tr><td><code>dte_range</code></td><td>(4,5), (3,5), (4,6)</td><td class="hi">(4,5)</td></tr>
  <tr><td><code>delta_range</code></td><td>(0.25,0.35), (0.30,0.40), (0.35,0.50)</td><td class="hi">(0.30,0.40)</td></tr>
  <tr><td><code>tp_mult</code></td><td>1.5, 1.75, 2.0, 2.5, 3.0</td><td class="hi">2.0</td></tr>
  <tr><td><code>spot_stop_pct</code></td><td>1.0, 1.5, 2.0, 2.5, 3.0, off</td><td class="hi">2.0</td></tr>
  <tr><td><code>time_gate_h</code></td><td>18, 24, 36, 48, off</td><td class="hi">36</td></tr>
  <tr><td><code>time_gate_min_gain_pct</code></td><td>20, 30, 50</td><td class="hi">30</td></tr>
  <tr><td><code>session_filter</code></td><td>off, US_only (12/16/20 UTC)</td><td class="hi">off</td></tr>
</table>

<h3>Fee model (Deribit)</h3>
<pre>entry_fee_btc = min(0.0003, 0.125 × entry_mark_btc)   # per leg
exit_fee_btc  = min(0.0003, 0.125 × exit_mark_btc)    # per leg
round_trip    = entry_fee_btc + exit_fee_btc</pre>

<!-- ── FILE REFERENCE ─────────────────────────────────────────────────────── -->
<h2>File Reference</h2>

<h3>Analysis scripts</h3>
<div class="file-grid">
  <div class="file-item"><div class="fname">01_scan_tradeable_longs.py</div><div class="fdesc">Scan 5-min option snapshots, label tradeable candidates</div></div>
  <div class="file-item"><div class="fname">02_enrich_context.py</div><div class="fdesc">Enrich winners with hold_hours, exit_bid, prior momentum</div></div>
  <div class="file-item"><div class="fname">03_frequency_stats.py</div><div class="fdesc">Base rate by DTE, delta, side</div></div>
  <div class="file-item"><div class="fname">04_timing_analysis.py</div><div class="fdesc">Base rate by hour, day-of-week; hold period CDF</div></div>
  <div class="file-item"><div class="fname">05_vol_regime.py</div><div class="fdesc">IV vs realised HV regime analysis</div></div>
  <div class="file-item"><div class="fname">06_entry_quality.py</div><div class="fdesc">Spread analysis; entry quality filters</div></div>
  <div class="file-item"><div class="fname">07_candidates_momentum.py</div><div class="fdesc">Phase 0: momentum features for all candidates</div></div>
  <div class="file-item"><div class="fname">08_mtf_momentum.py</div><div class="fdesc">Phase 1: 4h × 1h cross-tabulation heatmaps</div></div>
  <div class="file-item"><div class="fname">09_winner_magnitude.py</div><div class="fdesc">Full peak_multiple rescan; EV table</div></div>
  <div class="file-item"><div class="fname">10_stop_calibration.py</div><div class="fdesc">MAE distribution, time gate CDF, loser check, joint grid</div></div>
</div>

<h3>Key data files</h3>
<div class="file-grid">
  <div class="file-item"><div class="fname">candidates_summary.parquet</div><div class="fdesc">26,354 candidates with tradeable label, entry context</div></div>
  <div class="file-item"><div class="fname">tradeable_longs_enriched.parquet</div><div class="fdesc">15,347 winners: hold_hours, exit_bid, momentum features</div></div>
  <div class="file-item"><div class="fname">candidates_enriched.parquet</div><div class="fdesc">All 26,354 + spread_pct + momentum windows</div></div>
  <div class="file-item"><div class="fname">winner_peaks.parquet</div><div class="fdesc">15,347 winners + peak_multiple from full rescan</div></div>
  <div class="file-item"><div class="fname">ev_table.csv</div><div class="fdesc">EV grid across TP multiples and base rates</div></div>
  <div class="file-item"><div class="fname">phase1_both_aligned.csv</div><div class="fdesc">MTF alignment filter table (4h × 1h combinations)</div></div>
  <div class="file-item"><div class="fname">stop_mae_distribution.csv</div><div class="fdesc">MAE percentiles for winners by direction/TP category</div></div>
  <div class="file-item"><div class="fname">stop_time_gate.csv</div><div class="fdesc">CDF of hold_hours by peak_multiple category</div></div>
  <div class="file-item"><div class="fname">stop_loser_check.csv</div><div class="fdesc">Loser/winner adverse move rates at each stop threshold</div></div>
  <div class="file-item"><div class="fname">stop_joint_grid.csv</div><div class="fdesc">% winners preserved under joint (stop × gate) grid</div></div>
</div>

<h3>Strategy documents</h3>
<div class="file-grid">
  <div class="file-item"><div class="fname">KERNEL_STRATEGY.md</div><div class="fdesc">Living strategy spec — full backtester-ready description</div></div>
  <div class="file-item"><div class="fname">AGENT_BRIEF.md</div><div class="fdesc">AI agent reference (this doc, text-only)</div></div>
  <div class="file-item"><div class="fname">SUMMARY.html</div><div class="fdesc">Human summary with embedded charts (this file)</div></div>
</div>

</div><!-- /container -->
</body>
</html>
"""

(HERE / "SUMMARY.html").write_text(HTML)
print(f"Wrote SUMMARY.html ({len(HTML):,} bytes)")

# ---------------------------------------------------------------------------
# AGENT_BRIEF.md
# ---------------------------------------------------------------------------

MD = """# BTC Long Directional Options — Agent Brief

_Generated: 2026-05-15 · Scripts 01–10 complete_

## Purpose

Backwards analysis of BTC Deribit options to identify conditions under which buying a directional
option at the ask is EV-positive after fees. An option entry is **tradeable** if its bid reaches
≥ 1.20× the entry ask before expiry − 1h. Dataset: 2026-01-01 → 2026-05-12, Deribit BTC weekly
options, 4h entry boundaries (00/04/08/12/16/20 UTC).

---

## Dataset

| Key fact | Value |
|---|---|
| Total candidate entries | 26,354 |
| Tradeable (profitable) | 15,347 (58.2%) |
| Never hit 1.2× | 9,244 (35.1%) |
| Fee-killed | 1,281 (4.9%) |
| Date range | 2026-01-01 → 2026-05-12 |
| Spot data | 546,137 rows (1-min OHLC, 379 days) |
| Options data | 5-min snapshots, Deribit BTC weekly options |

**Labelling rule:** `tradeable = (bid_price ≥ entry_ask × 1.20)` at any 5-min snapshot from
entry to expiry − 1h (Deribit expire 08:00 UTC → cutoff 07:00 UTC).

**Fee model (per leg):** `fee_btc = min(0.0003, 0.125 × mark_price_btc)`. Round trip = entry + exit.

---

## Workflow History (Scripts 01–10)

### 01 — Scan tradeable longs
Scanned all 5-min option snapshots. Filters: DTE 1–7, |delta| 0.10–0.40, entry ask ≥ $75,
standard 4h UTC boundaries. Produced `candidates_summary.parquet` (26,354 rows).

### 02 — Enrich context
For each tradeable winner: located first 1.2× crossover, computed hold_hours, exit_bid,
gross_gain_pct, net_pnl_usd. Looked up prior spot momentum at 1h/4h/24h windows before entry.
Produced `tradeable_longs_enriched.parquet`.

Key numbers from enriched file:
- hold_hours: median 5.4h, p75 14.7h, p90 30.1h
- gross_gain_pct (to first 1.2× cross): median 26.7%, mean 32.5%
- net_pnl_usd: median $84 calls, $93 puts

### 03 — Frequency stats
Base rate by DTE: DTE 5 = 67.7%, DTE 4 = 63.4%, DTE 1 = 51.5% (too hard).
Base rate by delta: monotone — delta 0.40 = 69.1%, delta 0.10 = 42.1%.
Calls vs puts: 58.6% vs 60.0% (no structural asymmetry).
**Sweet spot: DTE 4–5, delta 0.30–0.40.**

### 04 — Timing analysis
Best hour: 12:00 UTC (63.6%, 3.2h median). Best day: Sunday (66.3%). Saturday = 11.3h median.
DTE=1 resolves 90% within 12h. DTE=7 takes up to 68h (p90).

### 05 — Vol regime
Negative IV-premium common (58% of entries: IV < HV24). Options are often cheap vs realised.
Note: HV scaling bug found (sqrt(365×288) used instead of sqrt(365×1440)) — ordinal ranks valid.

### 06 — Entry quality
Spread ≤ 10% of mark: **+9pp** base rate (58.2% → 67.2%). Single strongest individual filter.
Wide-spread options (>20%) barely reach 45% base rate.

### 07 — Momentum features (Phase 0)
Computed spread_pct + spot_30m/1h/4h/24h prior momentum for all 26,354 candidates.
Key output: `candidates_enriched.parquet`, `phase0_by_4h_momentum.csv`.
Best Phase 0 combo: tight spread + 4h ≥ 1.5% + 1h ≥ 0.5% → 80.6% at 0.93 windows/day.

Notable sub-patterns (4h momentum buckets, tight spread):
- Puts after crash (<−3%): **97.3%** (n=111) — directional + IV spike. Strongest single signal.
- Calls after crash (<−3%): **89.2%** (n=74) — IV expansion pumps calls despite adverse direction.
- Calls after +1.5–3% rise: **85.3%** (n=279) — directional continuation.
- Puts into +1.5%+ 4h rise: **47.6%** — strong counter-direction penalty.

### 08 — MTF momentum (Phase 1)
Full 4h × 1h cross-tabulation for calls and puts separately. US session interaction.

Both-aligned filter table (tight spread, all DTE/delta):

| 4h thr | 1h thr | Base rate | Windows/day | Trades/month |
|---|---|---|---|---|
| ≥0.3% | ≥0.5% | 80.6% | 0.93 | ~28 |
| ≥1.0% | ≥0.5% | 80.0% | 0.59 | ~18 |
| **≥1.5%** | **≥0.5%** | **87.2%** | **0.36** | **~11** |
| ≥2.0% | ≥0.5% | 90.3% | 0.23 | ~7 |

Notable heatmap cells:
- Calls: strong up 4h + mild up 1h (+0.5–+1.5%) → 86.4%
- Puts: neutral 4h + 1h just starting down (−1.5–−0.5%) → **93.5%** (early-move entry)
- Counter-direction: puts into strong 4h up → 28–47%

US session (12/16/20 UTC) + 4h ≥ 1%: 75.9% vs Non-US: 72.1% (+3.8pp).

### 09 — Winner magnitude
Full rescan of 15,347 winners to find peak_multiple (max bid / entry_ask_btc, all snapshots).
Produced `winner_peaks.parquet`.

Peak distribution: mean 3.93×, **median 2.43×**, p75 4.38×, p90 7.40×, p99 25.64×.

EV formula: `EV(TP) = base_rate × f(TP) × TP − 1`  
f(TP) = fraction of tradeable winners reaching TP:
- 1.5× = 81.7%, 1.75× = 70.2%, **2.0× = 61.5%**, 3.0× = 39.8%

EV at TP=2.0× by kernel:
- 80.6% kernel: **−0.8%** (0.7pp below break-even of 81.3%)
- **87.2% kernel: +7.3%** ← first EV-proven specification

### 10 — Stop calibration
MAE (max adverse spot excursion) for all 15,347 winners using 1-min OHLC spot data.
- Calls used spot LOW (worst case intraday drop)
- Puts used spot HIGH (worst case intraday rise)

**MAE summary:**

| Group | p50 MAE | Safe at −1.5% | Safe at −2.0% |
|---|---|---|---|
| Calls — peak ≥ 2× | 0.99% | 65% | 75% |
| Puts  — peak ≥ 2× | 0.93% | 65% | 74% |
| All winners | 1.58% | 48% | 58% |

**Stop selectivity (8h check):**

| Stop | Losers stopped | Winners stopped | Gap |
|---|---|---|---|
| −1.0% | 33.6% | 8.5% | 25pp |
| −1.5% | 22.7% | 4.7% | 18pp |
| −2.0% | 15.3% | 2.2% | 13pp |

**Time gate CDF (hold_hours to first 1.2× sign):**
- 24h → 86% of all winners + 85% of peak≥2× winners
- **36h → 93% of all winners + 93% of peak≥2×** ← recommended default
- 48h → 96%

Big winners (peak ≥ 2×) and all winners have nearly identical time CDFs — no "patient big winner" segment.

---

## Final Strategy Specification

### Entry conditions (all required)

| Condition | Value |
|---|---|
| Spread ≤ N% of mark | ≤ 10% (grid: 5, 10, 15) |
| DTE at entry | 4–5 (grid: (3,5), (4,5), (4,6)) |
| \|delta\| at entry | 0.30–0.40 (grid: (0.25,0.35), (0.30,0.40), (0.35,0.50)) |
| 4h prior spot momentum aligned | ≥ 1.5% (grid: 0.3, 0.5, 1.0, 1.5, 2.0) |
| 1h prior spot momentum aligned | ≥ 0.5% (grid: 0.3, 0.5, 1.0) |
| Entry cadence | 4h UTC boundaries: 00, 04, 08, 12, 16, 20 |

"Aligned" = call requires positive %, put requires negative % (above thresholds are magnitudes).

### Take profit

Exit when `bid_price ≥ entry_ask × tp_mult` at any 5-min snapshot.
- Default TP: **2.0×**
- Grid: [1.5, 1.75, 2.0, 2.5, 3.0]

### Stop A — spot adverse excursion

Exit when BTC spot (1-min close) moves ≥ `spot_stop_pct` % against trade direction from entry spot.
- Default: **2.0%**
- Grid: [1.0, 1.5, 2.0, 2.5, 3.0, off]
- Rationale: preserves 74–75% of peak ≥ 2× winners, captures 15% of losers within 8h

### Stop B — time gate

Exit `time_gate_h` hours after entry if `bid_price < entry_ask × time_gate_min_gain`.
- Default: **36h + 1.30× (30% gain threshold)**
- Grid: gates [18, 24, 36, 48, off] × gain threshold [1.20, 1.30, 1.50]
- Rationale: 93% of winners show ≥1.2× momentum by 36h; holding further is mostly theta bleed

### Fee model

```
entry_fee_btc = min(0.0003, 0.125 × entry_mark_btc)
exit_fee_btc  = min(0.0003, 0.125 × exit_mark_btc)
round_trip    = entry_fee_btc + exit_fee_btc
```

Trade at ask on entry, bid on exit. No additional slippage modelled.

### Expected performance (pre-backtest estimates)

| Metric | Value |
|---|---|
| Base rate | 87.2% |
| EV per trade at TP=2.0× | +7.3% |
| Frequency | ~11 trades/month (~0.36/day) |
| Median winner hold | 5.4h (to first 1.2× cross) |
| % big winners (peak ≥ 2×) safe from −2% spot stop | 74–75% |

---

## Backtester Parameter Grid

Default parameters marked with *.

| Parameter | Grid | Default |
|---|---|---|
| 4h_momentum_thr | 0.3, 0.5, 1.0, 1.5, 2.0 | **1.5** |
| 1h_momentum_thr | 0.3, 0.5, 1.0 | **0.5** |
| spread_max_pct | 5, 10, 15 | **10** |
| dte_range | (3,5), (4,5), (4,6) | **(4,5)** |
| delta_range | (0.25,0.35), (0.30,0.40), (0.35,0.50) | **(0.30,0.40)** |
| tp_mult | 1.5, 1.75, 2.0, 2.5, 3.0 | **2.0** |
| spot_stop_pct | 1.0, 1.5, 2.0, 2.5, 3.0, off | **2.0** |
| time_gate_h | 18, 24, 36, 48, off | **36** |
| time_gate_min_gain_pct | 20, 30, 50 | **30** |
| session_filter | off, US_only | **off** |

**Priority run:** defaults only (1 backtest) to confirm baseline EV.  
**Reduced grid:** fix spread=10, dte=(4,5), delta=(0.30,0.40), session=off.  
Vary: 4h_thr (3) × 1h_thr (3) × tp_mult (3) × spot_stop (3) × time_gate (3) = 243 combinations.

---

## File Index

### Analysis scripts
| File | Purpose |
|---|---|
| 01_scan_tradeable_longs.py | Scan options snapshots, label tradeable |
| 02_enrich_context.py | Enrich winners with hold_hours, exit_bid, momentum |
| 03_frequency_stats.py | Base rate by DTE, delta, side |
| 04_timing_analysis.py | Base rate by hour, day-of-week; hold CDF |
| 05_vol_regime.py | IV vs realised vol regime |
| 06_entry_quality.py | Spread analysis |
| 07_candidates_momentum.py | Phase 0: momentum features for all candidates |
| 08_mtf_momentum.py | Phase 1: 4h × 1h heatmaps |
| 09_winner_magnitude.py | Full peak rescan; EV table |
| 10_stop_calibration.py | MAE distribution, time gate, loser check, joint grid |

### Key data files
| File | Contents |
|---|---|
| candidates_summary.parquet | 26,354 candidates + tradeable label |
| tradeable_longs_enriched.parquet | 15,347 winners + hold_hours, exit_bid, momentum |
| candidates_enriched.parquet | 26,354 candidates + spread_pct + all momentum features |
| winner_peaks.parquet | 15,347 winners + peak_multiple (full rescan) |
| ev_table.csv | EV across TP multiples × base rates |
| phase0_by_4h_momentum.csv | Base rate by 4h momentum bucket |
| phase1_both_aligned.csv | MTF alignment table (4h × 1h) |
| phase1_heatmap_calls.csv | 4h × 1h heatmap — calls |
| phase1_heatmap_puts.csv | 4h × 1h heatmap — puts |
| stop_mae_distribution.csv | MAE percentiles by direction + TP category |
| stop_time_gate.csv | CDF of hold_hours by peak category |
| stop_loser_check.csv | Loser/winner adverse move rates at each stop × time |
| stop_joint_grid.csv | % winners preserved under (stop_pct × time_gate) grid |

### Strategy documents
| File | Contents |
|---|---|
| KERNEL_STRATEGY.md | Full backtester-ready strategy spec (detailed) |
| AGENT_BRIEF.md | This file — AI agent reference |
| SUMMARY.html | Human summary with all charts embedded |
| ENTRY_SIGNAL_PLAN.md | Phase-by-phase entry signal plan |
| FINDINGS.md | Raw findings per script |

### Charts (SVG)
| File | Contents |
|---|---|
| freq_overview.svg | Base rate by DTE, delta, side, momentum |
| phase0_overview.svg | Phase 0 momentum filter analysis |
| phase1_overview.svg | Phase 1 MTF heatmap |
| magnitude_overview.svg | Winner peak distribution and EV table |
| stop_calibration.svg | MAE histogram, survival, loser check, joint grid |
| timing_overview.svg | Hold time distributions |
| timing_heatmap.svg | Hour × DTE base rate heatmap |
| vol_regime.svg | IV vs realised vol |
| entry_quality.svg | Spread analysis |
"""

(HERE / "AGENT_BRIEF.md").write_text(MD)
print(f"Wrote AGENT_BRIEF.md ({len(MD):,} bytes)")
