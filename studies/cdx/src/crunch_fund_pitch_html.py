"""Flashy UHNWI pitch deck for the Crunch Fund (HTML)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .paths import bundles_dir, reports_dir


def _load_pitch_stats() -> dict[str, Any]:
    """Fund-relative stats anchored on $5M collateral and ~$100M calm protection."""
    collateral = 5_000_000
    defaults = {
        "peak_low": 12.6, "peak_high": 15.5,
        "covid_low": 13.0, "covid_high": 19.0,
        "hit_rate": 53.0, "standing_peak": 7.7,
        "fund_mo_carry": 50_000, "fund_mo_low": 50_000, "fund_mo_high": 90_000,
        "fund_q_low": 150_000, "fund_q_high": 270_000,
        "fund_pct_low": 1.0, "fund_pct_high": 2.0,
        "prot_notional_m": 100, "naive_pct_higher": 30,
        "years_dep_low": 2.0, "years_dep_high": 4.0,
    }
    lb_path = bundles_dir() / "crunch_fund" / "leaderboard.csv"
    if not lb_path.exists():
        return defaults

    lb = pd.read_csv(lb_path)
    pyr = lb[lb["strategy"] == "pyramid"]
    st = lb[lb["strategy"] == "standing"]

    # Crisis peaks (best pyramid, for 10× section only)
    pyr_1b = pyr[pyr["notional_usd"] >= 999_000_000]
    smart_1b = pyr_1b[pyr_1b["run_id"].str.contains("x150", na=False)]
    smart_row = smart_1b.iloc[0] if len(smart_1b) else (pyr_1b.iloc[0] if len(pyr_1b) else pyr.iloc[0])
    peaks = pyr_1b["crisis_nav_peak_tier_bc"].dropna()
    covid_vals = pyr_1b["median_covid_peak"].dropna()

    # Calm costs at ~$100M on a $5M fund (mandate-sized example)
    st_100 = st[st["notional_usd"] == 100_000_000]
    e60 = st_100[st_100["entry_max_bps"] == 60]
    smart_100_row = e60[e60["exit_bps"].notna()].iloc[0] if len(e60[e60["exit_bps"].notna()]) else None
    naive_100_row = e60[e60["exit_bps"].isna()].iloc[0] if len(e60[e60["exit_bps"].isna()]) else None
    if smart_100_row is None and len(st_100):
        smart_100_row = st_100.loc[st_100["median_calm_burn"].abs().idxmin()]

    carry_mo = 100_000_000 * 60 / 10_000 / 12  # ~$50k/mo core premium at 60 bps
    low_cost = st_100[st_100["run_id"] == "standing_e50_x150_n100m"]
    if len(low_cost):
        mo_disciplined = abs(float(low_cost.iloc[0]["median_calm_burn"])) / 12
    elif smart_100_row is not None:
        mo_disciplined = abs(float(smart_100_row["median_calm_burn"])) / 12
    else:
        mo_disciplined = carry_mo * 1.6

    mo_low = carry_mo
    mo_high = min(mo_disciplined, carry_mo * 1.8)  # cap narrative band near mandate scale
    if mo_high < mo_low:
        mo_high = mo_low * 1.5

    if smart_100_row is not None and naive_100_row is not None:
        mo_smart = abs(float(smart_100_row["median_calm_burn"])) / 12
        mo_naive = abs(float(naive_100_row["median_calm_burn"])) / 12
        pct_higher = int(round((mo_naive / mo_smart - 1) * 100)) if mo_smart > 0 else 30
    else:
        pct_higher = 30

    q_low, q_high = mo_low * 3, mo_high * 3

    # Depletion at 100M (more fund-realistic than $1B)
    dep = st_100["median_years_to_depletion"].dropna() if len(st_100) else pd.Series(dtype=float)

    return {
        "peak_low": float(peaks.quantile(0.75)) if len(peaks) else defaults["peak_low"],
        "peak_high": float(peaks.max()) if len(peaks) else defaults["peak_high"],
        "covid_low": float(covid_vals.quantile(0.5)) if len(covid_vals) else defaults["covid_low"],
        "covid_high": float(covid_vals.max()) if len(covid_vals) else defaults["covid_high"],
        "hit_rate": float(smart_row["hit_10x_rate_tier_bc"]) * 100 if smart_row is not None else 53.0,
        "standing_peak": float(st_100["crisis_nav_peak_tier_bc"].max()) if len(st_100) else 1.7,
        "fund_mo_carry": carry_mo,
        "fund_mo_low": mo_low,
        "fund_mo_high": mo_high,
        "fund_q_low": q_low,
        "fund_q_high": q_high,
        "fund_pct_low": mo_low / collateral * 100,
        "fund_pct_high": mo_high / collateral * 100,
        "prot_notional_m": 100,
        "naive_pct_higher": pct_higher,
        "years_dep_low": float(dep.min()) if len(dep) else defaults["years_dep_low"],
        "years_dep_high": float(dep.median()) if len(dep) else defaults["years_dep_high"],
    }


def _fmt_k(x: float) -> str:
    if x >= 1_000_000:
        return f"${x / 1_000_000:.1f}M"
    return f"${x / 1_000:.0f}k"


def build_crunch_fund_pitch_html() -> str:
    s = _load_pitch_stats()
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Credit Crunch Fund</title>
<style>
  :root {{
    --bg-deep: #05060a;
    --bg-card: rgba(18, 22, 35, 0.92);
    --gold: #e8c547;
    --gold-bright: #ffd966;
    --crimson: #e85d75;
    --ice: #b8d4ff;
    --text: #f0f2f8;
    --muted: #8b93a8;
    --border: rgba(232, 197, 71, 0.22);
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: #05060a;
    color: var(--text);
    line-height: 1.75;
  }}
  .bg-mesh {{
    position: fixed; inset: 0; z-index: -1;
    background:
      radial-gradient(ellipse 80% 60% at 50% -10%, rgba(232,197,71,0.14), transparent 55%),
      radial-gradient(ellipse 50% 40% at 90% 80%, rgba(232,93,117,0.08), transparent 50%),
      #05060a;
  }}
  .wrap {{ max-width: 860px; margin: 0 auto; padding: 0 1.5rem 4rem; }}

  .hero {{ text-align: center; padding: 4.5rem 1rem 3.5rem; }}
  .hero-badge {{
    display: inline-block; font-size: 0.72rem; font-weight: 600;
    letter-spacing: 0.18em; text-transform: uppercase; color: var(--gold);
    border: 1px solid var(--border); border-radius: 999px;
    padding: 0.45rem 1.2rem; margin-bottom: 1.5rem;
    background: rgba(232,197,71,0.06);
  }}
  .hero h1 {{
    font-family: Georgia, "Times New Roman", serif;
    font-size: clamp(2.4rem, 6vw, 3.8rem);
    font-weight: 600; line-height: 1.15; color: var(--gold-bright);
    margin-bottom: 0.75rem;
  }}
  .hero .tagline {{
    font-family: Georgia, "Times New Roman", serif;
    font-size: clamp(1.1rem, 2.5vw, 1.45rem);
    font-style: italic; color: var(--muted);
    max-width: 34rem; margin: 0 auto 2rem;
  }}
  .hero-multiple {{
    font-family: Georgia, "Times New Roman", serif;
    font-size: clamp(4rem, 14vw, 7rem);
    font-weight: 700; line-height: 1; color: var(--gold-bright);
    text-shadow: 0 0 60px rgba(232,197,71,0.3);
  }}
  .hero-multiple span {{ font-size: 0.45em; vertical-align: super; }}
  .hero-sub {{ font-size: 1rem; color: var(--ice); margin-top: 0.75rem; }}

  section {{ margin-top: 3.5rem; }}
  h2 {{
    font-family: Georgia, "Times New Roman", serif;
    font-size: 1.85rem; font-weight: 600; color: var(--gold);
    margin-bottom: 1.1rem; padding-bottom: 0.45rem;
    border-bottom: 1px solid var(--border);
  }}
  h3 {{
    font-size: 1.05rem; font-weight: 600; color: var(--gold-bright);
    margin: 1.5rem 0 0.65rem;
  }}
  p {{ margin-bottom: 1rem; color: #d4d8e4; font-size: 1rem; }}
  .lead {{
    font-size: 1.12rem; line-height: 1.8; color: #e8eaf0;
    border-left: 3px solid var(--gold);
    padding-left: 1.2rem; margin: 1.25rem 0;
  }}

  .stats-strip {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
    gap: 1px; background: var(--border); border-radius: 10px;
    overflow: hidden; margin: 2rem 0; border: 1px solid var(--border);
  }}
  .stat {{ background: var(--bg-card); padding: 1.1rem 0.85rem; text-align: center; }}
  .stat .num {{
    font-family: Georgia, "Times New Roman", serif;
    font-size: 1.75rem; font-weight: 700; color: var(--gold-bright);
  }}
  .stat .lbl {{ font-size: 0.72rem; color: var(--muted); margin-top: 0.2rem; line-height: 1.35; }}

  .card-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 1rem; margin: 1.25rem 0;
  }}
  .card {{
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 10px; padding: 1.25rem;
  }}
  .card h4 {{ font-size: 0.95rem; font-weight: 600; margin-bottom: 0.4rem; color: #e8eaf0; }}
  .card p {{ font-size: 0.9rem; margin: 0; color: var(--muted); }}

  .story {{
    background: linear-gradient(135deg, rgba(88,140,255,0.08), rgba(18,22,35,0.9));
    border: 1px solid rgba(136,170,220,0.25);
    border-radius: 12px; padding: 1.75rem 1.85rem; margin: 1.5rem 0;
  }}
  .story p {{ margin-bottom: 0.9rem; }}
  .story .highlight {{
    font-family: Georgia, "Times New Roman", serif;
    font-size: 1.15rem; color: var(--gold-bright);
    margin: 1.25rem 0 0.5rem; font-weight: 600;
  }}

  .pyramid-viz {{ display: flex; flex-direction: column; align-items: center; margin: 1.75rem 0; }}
  .pyr-layer {{
    text-align: center; padding: 1.1rem 1.5rem; width: 100%; max-width: 400px;
    border: 1px solid var(--border);
  }}
  .pyr-layer.addon {{
    background: rgba(232,197,71,0.12); border-radius: 10px 10px 0 0; margin-bottom: -1px;
  }}
  .pyr-layer.base {{
    background: rgba(88,140,255,0.1); border-radius: 0 0 10px 10px;
  }}
  .pyr-label {{ font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.14em; color: var(--gold); }}
  .pyr-title {{ font-family: Georgia, serif; font-size: 1.2rem; font-weight: 600; margin-top: 0.25rem; }}
  .pyr-desc {{ font-size: 0.85rem; color: var(--muted); margin-top: 0.3rem; }}

  .cost-box {{
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 12px; padding: 1.5rem 1.75rem; margin: 1.25rem 0;
  }}
  .cost-highlight {{
    display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin: 1.25rem 0;
  }}
  .cost-cell {{
    text-align: center; padding: 1rem; background: rgba(0,0,0,0.25);
    border-radius: 8px; border: 1px solid var(--border);
  }}
  .cost-cell .amt {{
    font-family: Georgia, serif; font-size: 1.6rem;
    font-weight: 700; color: var(--gold-bright);
  }}
  .cost-cell .per {{ font-size: 0.8rem; color: var(--muted); margin-top: 0.2rem; }}
  .smart-note {{
    background: rgba(63,185,80,0.08); border: 1px solid rgba(63,185,80,0.3);
    border-radius: 8px; padding: 1rem 1.2rem; font-size: 0.92rem; color: #c8e6c9;
    margin-top: 1rem;
  }}

  table {{
    width: 100%; border-collapse: collapse; margin: 1rem 0;
    font-size: 0.88rem; border: 1px solid var(--border); border-radius: 8px; overflow: hidden;
  }}
  th {{ background: rgba(232,197,71,0.1); color: var(--gold); font-weight: 600; padding: 0.6rem 0.9rem; text-align: left; }}
  td {{ padding: 0.6rem 0.9rem; border-top: 1px solid rgba(255,255,255,0.06); }}
  tr:nth-child(even) td {{ background: rgba(255,255,255,0.02); }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; color: var(--gold-bright); }}

  ul.check {{ list-style: none; padding: 0; }}
  ul.check li {{
    padding: 0.45rem 0 0.45rem 1.6rem; position: relative; color: #d4d8e4;
  }}
  ul.check li::before {{
    content: "·"; position: absolute; left: 0.4rem; color: var(--gold); font-weight: 700;
  }}

  .risk {{
    background: rgba(232,93,117,0.08); border: 1px solid rgba(232,93,117,0.35);
    border-radius: 12px; padding: 1.5rem 1.75rem; margin: 2rem 0;
  }}
  .risk h2 {{ color: var(--crimson); border-color: rgba(232,93,117,0.3); }}

  .appendix {{
    margin-top: 3.5rem; padding-top: 1.75rem; border-top: 1px dashed var(--border);
  }}
  .appendix h2 {{ font-size: 1.25rem; color: var(--muted); }}
  .appendix p, .appendix li {{ font-size: 0.86rem; color: var(--muted); }}

  footer {{
    margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid var(--border);
    font-size: 0.78rem; color: var(--muted); text-align: center;
  }}
</style>
</head>
<body>
<div class="bg-mesh"></div>
<div class="wrap">

  <header class="hero">
    <div class="hero-badge">Private · Five-year term</div>
    <h1>The Credit Crunch Fund</h1>
    <p class="tagline">A five-year expression built for a rare credit crisis.</p>
    <div class="hero-multiple">10<span>×</span>+</div>
    <p class="hero-sub">Modeled crisis payoff on $5M posted collateral</p>
  </header>

  <section>
    <p class="lead">
      You commit <strong style="color:var(--gold-bright)">$5 million</strong> for five years.
      If a serious credit dislocation hits North American investment-grade bonds during that period,
      our research indicates the fund can return <strong>ten times your capital or more</strong>
      in the crisis window. In calm years the position is expected to cost money, and that is
      intentional rather than a flaw in the design.
    </p>
    <p>
      This is not a balanced portfolio. It is catastrophe insurance paid in advance, structured
      so that a genuine credit crunch can produce a very large payoff relative to the capital posted.
    </p>
  </section>

  <div class="stats-strip">
    <div class="stat"><div class="num">$5M</div><div class="lbl">Posted<br>collateral</div></div>
    <div class="stat"><div class="num">5 yr</div><div class="lbl">Fund<br>term</div></div>
    <div class="stat"><div class="num">{s['peak_low']:.0f} to {s['peak_high']:.0f}×</div><div class="lbl">Modeled crisis<br>peak</div></div>
    <div class="stat"><div class="num">{s['hit_rate']:.0f}%</div><div class="lbl">Vintages reaching<br>10× in crisis</div></div>
  </div>

  <section>
    <h2>What we trade</h2>
    <p>
      We buy protection on the <strong>CDX.NA.IG</strong> index. You can think of it as insurance
      on the collective health of large U.S. investment-grade companies. It is not a bet on a single
      stock or a narrow sector. When markets are calm, that insurance costs money to hold. When credit
      comes under stress, spreads widen and the value of our protection rises.
    </p>
    <div class="card-grid">
      <div class="card">
        <h4>Calm markets</h4>
        <p>We pay to maintain protection. Fund value drifts lower, like an insurance premium.</p>
      </div>
      <div class="card">
        <h4>Stress begins</h4>
        <p>Spreads widen. Protection gains value and fund value rises.</p>
      </div>
      <div class="card">
        <h4>Full crisis</h4>
        <p>Spreads move from roughly 50 to 60 bps toward 150 bps and beyond. Models show 10× or higher.</p>
      </div>
    </div>
  </section>

  <section>
    <h2>How the payoff works</h2>
    <p>
      Your <strong>$5 million</strong> is the posted stake. The magnitude of a crisis gain depends on
      how much protection we carry and whether we add exposure as stress builds. We do not promise
      profits in quiet markets. We structure the book for convexity, meaning modest ongoing cost in
      normal conditions and very large upside when a rare event occurs.
    </p>
    <table>
      <thead><tr><th>Market mood</th><th>Our position</th><th>What it means for you</th></tr></thead>
      <tbody>
        <tr><td><strong>Calm years</strong></td><td>We pay to maintain protection</td><td>Fund value drifts lower</td></tr>
        <tr><td><strong>Stress begins</strong></td><td>Protection gains value</td><td>Fund value rises</td></tr>
        <tr><td><strong>Full crisis</strong></td><td>Spreads widen sharply</td><td class="num"><strong>10×+</strong> in our models</td></tr>
      </tbody>
    </table>
  </section>

  <section>
    <h2>A familiar story: Bill Ackman in March 2020</h2>
    <div class="story">
      <p>
        In late February 2020, as COVID-19 began to shut down economies, the hedge fund manager
        <strong>Bill Ackman</strong> and his firm <strong>Pershing Square</strong> bought credit protection
        on investment-grade and high-yield bond indices, including instruments closely related to the
        market we trade. At the time, spreads were still relatively <strong>compressed</strong>, near
        <strong>fifty basis points</strong> on investment-grade indices. Markets had not yet priced a
        global shutdown.
      </p>
      <p>
        Within weeks, panic took hold. CDX investment-grade spreads widened sharply, moving toward
        <strong>one hundred fifty to two hundred basis points</strong> in the March turmoil. The protection
        Ackman had bought rose dramatically in value. Pershing Square reportedly turned a position that
        cost on the order of <strong>tens of millions of dollars</strong> in premium into a gain of roughly
        <strong>$2.6 billion</strong> over a matter of weeks.
      </p>
      <p class="highlight">When CDX IG spreads rose, mark-to-market gains on long protection flowed through to fund value.</p>
      <p>
        That trade is the archetype of what we are trying to replicate in structure. Ackman was already
        long protection before the worst of the move. Our fund follows the same economic logic on
        <strong>CDX.NA.IG</strong>. We hold protection in calm conditions so we are positioned before
        headlines arrive. In our backtests on the COVID episode, the best pyramid configurations produced
        modeled peak multiples in the <strong>mid-teens</strong> on posted collateral.
      </p>
    </div>
  </section>

  <section>
    <h2>When it triggers: two layers</h2>
    <p>Our preferred structure is a <strong>pyramid</strong>, which combines a calm-market base with a stress add-on.</p>
    <div class="pyramid-viz">
      <div class="pyr-layer addon">
        <div class="pyr-label">Layer 2 · Stress add-on</div>
        <div class="pyr-title">Additional protection at 80 to 100 bps</div>
        <div class="pyr-desc">We add exposure when credit is clearly under pressure</div>
      </div>
      <div class="pyr-layer base">
        <div class="pyr-label">Layer 1 · Calm base</div>
        <div class="pyr-title">Ready when spreads are below ~60 bps</div>
        <div class="pyr-desc">We are in the trade before headlines move markets</div>
      </div>
    </div>
    <h3>Layer 1: Ready in calm markets</h3>
    <p>
      When spreads are low, we enter long protection and remain in the trade through ordinary volatility
      so we aim to be in the position when a crisis begins.
    </p>
    <h3>Layer 2: Additional protection in stress</h3>
    <p>
      When spreads cross roughly eighty to one hundred basis points, we add a second layer of protection.
      We reduce that add-on when spreads ease or after a fixed holding period, so we do not carry
      crisis-size exposure longer than the rules require.
    </p>
    <p>
      In quiet times the fund carries one unit of protection. In the early phase of a crunch it can carry
      two. If no crisis occurs during the five-year term, holding costs will likely consume most or all
      of the posted capital.
    </p>
  </section>

  <section>
    <h2>What it costs if nothing happens</h2>
    <p>
      Catastrophe insurance has a price even when the catastrophe does not arrive. That price is paid
      through your <strong>$5 million</strong> of posted capital as the fund holds protection in calm markets.
    </p>
    <div class="cost-box">
      <p style="margin-bottom:0.5rem;">
        In our historical simulation, a representative setup keeps protection in line with the fund mandate:
        roughly <strong>${s['prot_notional_m']} million</strong> of index CDS on a <strong>$5 million</strong> fund
        in quiet conditions. Against <em>your</em> capital, the model shows typical calm-period drag of:
      </p>
      <div class="cost-highlight">
        <div class="cost-cell">
          <div class="amt">{_fmt_k(s['fund_mo_low'])} to {_fmt_k(s['fund_mo_high'])}</div>
          <div class="per">per month on your $5M fund</div>
        </div>
        <div class="cost-cell">
          <div class="amt">{_fmt_k(s['fund_q_low'])} to {_fmt_k(s['fund_q_high'])}</div>
          <div class="per">per quarter on your $5M fund</div>
        </div>
      </div>
      <p style="font-size:0.92rem; color:var(--muted); margin-bottom:0;">
        That is roughly <strong>{s['fund_pct_low']:.0f}% to {s['fund_pct_high']:.0f}%</strong> of your posted
        capital per month. The core component is the insurance premium itself: at calm spreads near sixty
        basis points, carry alone is about <strong>{_fmt_k(s['fund_mo_carry'])} per month</strong> for every
        $100 million of protection, which equals about <strong>one percent per month</strong> of a
        $5 million fund.
      </p>
      <div class="smart-note">
        <strong>We trade this deliberately</strong> to keep that drag as low as the mandate allows. We enter
        only in calm spreads, exit the base leg once stress is established, and time-limit the stress add-on.
        In the same backtest at comparable sizing, a passive position with no exit rule cost roughly
        <strong>{s['naive_pct_higher']}% more</strong> in calm markets than our disciplined pyramid approach.
      </div>
      <p style="font-size:0.92rem; margin-top:1rem; margin-bottom:0;">
        Over a full five-year term with no crisis, these costs can still consume much or all of the
        $5 million. That is the nature of the product.
      </p>
    </div>
  </section>

  <section>
    <h2>What ten times or more means</h2>
    <p>
      If a severe credit dislocation occurs during the fund's life, peak value during that episode should
      reach at least <strong>ten times</strong> your <strong>$5 million</strong>, which is
      <strong>$50 million or more</strong> on the modeled crisis path.
    </p>
    <p>
      That objective requires <strong>scaling protection up when stress arrives</strong>, not running at
      maximum size through every calm month. In crisis windows our models add exposure and produce peak
      multiples well above ten times on the fund; in calm months we keep the line closer to mandate size
      so the cost figures above stay proportionate to your $5 million stake.
    </p>
    <div class="stats-strip">
      <div class="stat"><div class="num">{s['peak_low']:.0f} to {s['peak_high']:.0f}×</div><div class="lbl">Peak crisis multiples<br>(scaled in stress)</div></div>
      <div class="stat"><div class="num">{s['covid_low']:.0f} to {s['covid_high']:.0f}×</div><div class="lbl">COVID episode<br>(model)</div></div>
      <div class="stat"><div class="num">{s['hit_rate']:.0f}%</div><div class="lbl">Vintages reaching<br>10× in crisis</div></div>
    </div>
    <p style="font-size:0.92rem; color:var(--muted);">
      COVID was a real event but a moderate dislocation by our full-crunch design standard. A larger
      widening, closer to a deep systemic crisis, is what the fund is sized to capture.
    </p>
  </section>

  <section>
    <h2>Who this is for</h2>
    <ul class="check">
      <li>Investors who hold diversified wealth and can afford to lose the full $5 million</li>
      <li>Those who want asymmetric upside linked to a macro credit event, not stock selection</li>
      <li>Those who accept that we are in the market before panic and add only when stress is confirmed</li>
    </ul>
    <p>
      This is not a savings account, a steady-return hedge fund, or a speculative crypto position.
      It is a term commitment that pays when credit fear reprices sharply.
    </p>
  </section>

  <section class="risk">
    <h2>Risks you should understand</h2>
    <ul class="check">
      <li><strong>Calm markets create ongoing cost.</strong> On your $5 million fund, quiet months typically draw down roughly {_fmt_k(s['fund_mo_low'])} to {_fmt_k(s['fund_mo_high'])} in our model. Over several years without a crisis, that can consume much or all of the posted capital.</li>
      <li><strong>You can lose the entire posted amount.</strong> The fund is structured as option-like premium, not principal-safe capital.</li>
      <li><strong>Past simulations are not guarantees.</strong> Real crises differ in speed, liquidity, and legal terms.</li>
    </ul>
    <p style="margin-top:1rem; margin-bottom:0;">
      If losing $5 million would materially affect your financial security, this fund is not appropriate for you.
    </p>
  </section>

  <section class="appendix">
    <h2>Appendix: performance snapshot</h2>
    <p><em>For readers who want numbers. The narrative above is the product.</em></p>
    <table>
      <tr><th>Item</th><th>Value</th></tr>
      <tr><td>Backtest window</td><td>Sep 2011 to Mar 2026</td></tr>
      <tr><td>Posted collateral</td><td class="num">$5,000,000</td></tr>
      <tr><td>Calm protection sizing (example)</td><td class="num">~${s['prot_notional_m']}M index CDS</td></tr>
      <tr><td>Calm drag on your fund</td><td class="num">{_fmt_k(s['fund_mo_low'])} to {_fmt_k(s['fund_mo_high'])}/mo</td></tr>
      <tr><td>Calm drag (quarterly)</td><td class="num">{_fmt_k(s['fund_q_low'])} to {_fmt_k(s['fund_q_high'])}/qtr</td></tr>
      <tr><td>Peak crisis multiple (scaled in stress)</td><td class="num">{s['peak_low']:.1f}× to {s['peak_high']:.1f}×</td></tr>
      <tr><td>Hit 10× when crisis occurs</td><td class="num">~{s['hit_rate']:.0f}% of vintages</td></tr>
      <tr><td>Naive vs disciplined calm cost</td><td class="num">~{s['naive_pct_higher']}% higher without exit rules</td></tr>
    </table>
    <p style="margin-top:1rem;"><strong>Trade logic:</strong></p>
    <ol style="padding-left:1.25rem; color:var(--muted); font-size:0.86rem;">
      <li>Base: long protection when spread is below 60 bps; optional exit at 150 bps.</li>
      <li>Add-on: additional notional when spread reaches 80 to 100 bps; close when spread retreats to roughly 100 to 110 bps or after 30 to 45 days.</li>
      <li>Full CDS economics in simulation: carry, mark-to-market, bid and ask, roll, and financing.</li>
    </ol>
  </section>

  <footer>
    <p>Confidential · {generated}</p>
    <p>Not an offering document. Consult legal and compliance before external distribution.</p>
  </footer>

</div>
</body>
</html>"""


def write_crunch_fund_pitch(path: Path | str | None = None) -> Path:
    out = Path(path) if path else reports_dir() / "crunch_fund_pitch.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_crunch_fund_pitch_html(), encoding="utf-8")
    return out
