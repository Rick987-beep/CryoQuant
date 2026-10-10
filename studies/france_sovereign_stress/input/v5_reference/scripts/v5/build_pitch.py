"""Investor pitch for the France sovereign-stress spread trade (FOAT / FGBL), based on the v5 results.

Reads the same inputs as build_report.py and writes reports/france_sovereign_stress_v5_pitch_<date>.html plus a copy in
the job output/.

    .venv/bin/python jobs/france-sovereign-stress/scripts/v5/build_pitch.py [--stamp 2026-10-09T1456]
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import options
from build_report import (BUDGET, CSS, DATA, JOB, LEVELS, ROOT, boxes, chart, eur, pct, realized_vols,
                          spread_ladder, table, x)
from lib.chart_utils import ax_clean, set_style

FEE_SIDE = 2.35 + 5.0
NAVY, BLUE, GOLD, RED, GREY = "#0d1b2a", "#1e6fbf", "#c8a84b", "#b03a2e", "#8a9ab0"


def link(text, url):
    return f'<a href="{url}">{text}</a>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="2026-10-09T1456")
    args = ap.parse_args()
    R = json.loads((DATA / f"v5_{args.stamp}.json").read_text())
    RV = json.loads((DATA / f"v5_{args.stamp}_vol1.5.json").read_text())
    MT = json.loads((DATA / f"maintenance_{args.stamp}.json").read_text())["results"]["spread"]
    EX = json.loads((DATA / f"extras_{args.stamp}.json").read_text())
    chain = JOB / "data" / "chains" / f"eurex_{args.stamp}.json"
    snap = options.load_snapshot(chain)
    A = R["assumptions"]
    FC = A["futures"]
    fetched = datetime.fromisoformat(R["snapshot"]["fetched_at"])
    asof = fetched.strftime("%d %B %Y, %H:%M CEST").lstrip("0")
    s0 = R["snapshot"]["spread"]
    foat = snap.expiries[("OOAT", "20/11/2026")].fwd
    fgbl = snap.expiries[("OGBL", "20/11/2026")].fwd
    combo0 = round(fgbl - foat, 2)
    S = next(b for b in R["best"] if b["name"].startswith("Spread") and b["rule"].startswith("stop 40, add every +20"))
    SV = next(b for b in RV["best"] if b["name"].startswith("Spread") and b["rule"].startswith("stop 40, add every +20"))
    vols = realized_vols()
    put = EX["put"]
    ef = FC["eur_per_bp"]["FOAT"]
    carry_q = (FC["carry_bp_per_day"]["FOAT"] - FC["carry_bp_per_day"]["FGBL"]) * 63
    carry_day_eur = (FC["carry_bp_per_day"]["FOAT"] - FC["carry_bp_per_day"]["FGBL"]) * 3 * ef
    days = pd.bdate_range(fetched.date(), "2027-07-01")
    carry_total = carry_day_eur * len(days)

    s_rows, s_final, _ = spread_ladder(FC, combo0)
    sides = 6 + sum(abs(b[4] - a[4]) + abs(b[5] - a[5]) for a, b in zip(s_rows, s_rows[1:])) + 38 + 3 * 12
    fee_300 = sides * FEE_SIDE
    fee_wrong = (6 + 3 * 12 + 6) * FEE_SIDE

    # ── charts ──
    set_style()
    fred = pd.read_csv(JOB / "data" / "fred_10y_monthly.csv", index_col=0, parse_dates=True)
    fred.index = fred.index.tz_localize(None)
    fr = (fred["IRLTLT01FRM156N"] - fred["IRLTLT01DEM156N"]) * 100
    it = (fred["IRLTLT01ITM156N"] - fred["IRLTLT01DEM156N"]) * 100
    fig, ax = plt.subplots(figsize=(12, 4.6))
    ax.plot(it.index, it, color=GREY, lw=1.4, label="Italy − Germany")
    ax.plot(fr.index, fr, color=NAVY, lw=2, label="France − Germany")
    today = pd.Timestamp(fetched.date())
    ax.scatter([today], [s0], color=RED, zorder=5)
    ax.annotate(f"France today {s0:.0f} bp", (today, s0), xytext=(-150, 30), textcoords="offset points",
                fontsize=9, color=RED, arrowprops={"arrowstyle": "-", "color": RED, "lw": 0.8})
    for L, c in ((240, GOLD), (300, RED)):
        ax.axhline(L, color=c, lw=1, ls="--")
        ax.text(fr.index[0], L + 8, f"{L} bp", color=c, fontsize=9)
    ax.annotate("Italy 2018", (pd.Timestamp("2018-11-01"), 300), xytext=(-20, 40), textcoords="offset points",
                fontsize=9, color=GREY)
    ax.annotate("France 2011", (pd.Timestamp("2011-11-01"), 154), xytext=(-40, 40), textcoords="offset points",
                fontsize=9, color=NAVY)
    ax.set_ylabel("bp")
    ax.set_ylim(-20, 560)
    ax.legend(frameon=False, loc="upper right")
    ax_clean(ax)
    ch_long = chart("pitch_long", fig)

    y = pd.read_csv(DATA / "yields_daily.csv", index_col=0, parse_dates=True)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 5.6), sharex=True, gridspec_kw={"height_ratios": [1.1, 1]})
    a1.plot(y.index, y["oat10"], color=NAVY, lw=1.6, label="France 10Y (OAT)")
    a1.plot(y.index, y["bund10"], color=GREY, lw=1.6, label="Germany 10Y (Bund)")
    a1.set_ylabel("yield, %")
    a1.legend(frameon=False, loc="upper left")
    ax_clean(a1)
    a2.fill_between(y.index, y["spread_bp"], color=BLUE, alpha=0.18)
    a2.plot(y.index, y["spread_bp"], color=BLUE, lw=1.6, label="OAT − Bund spread")
    a2.set_ylabel("bp")
    a2.legend(frameon=False, loc="upper left")
    ax_clean(a2)
    ch_recent = chart("pitch_recent", fig)

    fig, ax = plt.subplots(figsize=(12, 4.2))
    xs = np.arange(len(LEVELS))
    sl = [s_final[L] / BUDGET for L in LEVELS]
    md = [S["levels"][str(L)] for L in LEVELS]
    b1 = ax.bar(xs - 0.18, sl, 0.36, color=GOLD, label="Clean move, no pull-back", zorder=3)
    b2 = ax.bar(xs + 0.18, md, 0.36, color=NAVY, label="Simulation average (10,000 paths)", zorder=3)
    for bars, vals in ((b1, sl), (b2, md)):
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.4, f"{v:.1f}×", ha="center", fontsize=9)
    ax.set_xticks(xs, [f"exit at {L} bp" for L in LEVELS])
    ax.set_ylabel("equity at exit ÷ stake")
    ax.legend(frameon=False, loc="upper left")
    ax_clean(ax)
    ch_pay = chart("pitch_pay", fig)

    grid = np.arange(int(s0), 401, 2)

    def eq_line(level):
        e, n, last = float(BUDGET), 3, 0
        for kk in range(1, 100):
            if 20 * kk > level - s0:
                break
            e += 20 * n * ef
            n = min(round(e / 40 / ef), 20)
            last = 20 * kk
        return e + (level - s0 - last) * n * ef

    fig, ax = plt.subplots(figsize=(12, 4.0))
    ax.plot(grid, [eq_line(g) / BUDGET for g in grid], color=NAVY, lw=2.2, label="Compounding spread trade")
    ax.plot(grid, [(BUDGET + (g - s0) * 3 * ef) / BUDGET for g in grid], color=GREY, lw=1.6, ls="--",
            label="Same entry, no reinvestment")
    for L in LEVELS:
        ax.axvline(L, color=GOLD, lw=0.8, ls=":")
    ax.set_xlabel("OAT–Bund spread (bp)")
    ax.set_ylabel("equity ÷ stake")
    ax.legend(frameon=False, loc="upper left")
    ax_clean(ax)
    ch_eq = chart("pitch_eq", fig)

    # ── tables ──
    kpis = [(f"{s0:.0f} bp", "OAT–Bund spread today", ""), ("300 bp", "Base-case exit", ""),
            (x(S["levels"]["300"], 1), "Average payout at 300 bp", ""), (x(S["median"], 1), "Median payout at 300 bp", ""),
            (x(S["levels"]["240"], 1), "Average payout at 240 bp", ""), (eur(BUDGET), "Risk per unit", "negative")]
    kpi_html = "".join(f'<div class="kpi"><div class="kpi-value {c}">{v}</div><div class="kpi-label">{lab}</div></div>'
                       for v, lab, c in kpis)

    mkt = boxes([(f"{snap.oat10:.2f}%", "France 10Y yield", ""), (f"{snap.bund10:.2f}%", "Germany 10Y yield", ""),
                 (f"{s0:.0f} bp", "OAT–Bund spread", "r"), ("+54 bp", "Spread change since 28 Aug", "r"),
                 ("~72–80 bp", "France 5Y CDS", "")])
    fiscal = table(["Indicator", "Level", "Comment"], [
        ["General government deficit", "5.1% (2025) · 5.4% (2026e)", "Overshoots the 5.0% target set for 2026"],
        ["2027 deficit, budget target", "5.0% of GDP", "Requires €54bn of consolidation, of which €43bn new measures"],
        ["2027 deficit, no measures", "about 6.5% of GDP", "Government's own estimate if the budget fails"],
        ["Public debt", "119% of GDP (mid-2026)", "121.7% projected for 2027; 98% in 2019"],
        ["Primary balance", "about −3% to −3.7% of GDP", "Debt rises before a single euro of interest is paid"],
        ["Debt service", "+€10bn in 2027", "Every new bond is issued near 5%, against an average cost near 2%"],
        ["Gross issuance 2027", "€340bn", "A record programme for the Agence France Trésor"],
        ["Growth", "0.5% (2026) · 1.0% (2027 assumption)", "The fiscal council (HCFP) calls 1.0% optimistic"],
    ], caption="Sources: government budget documents via ING THINK (1 Oct 2026), Deutsche Bank, Reuters, HCFP.")
    ratings = table(["Agency", "Rating", "Outlook", "Next step"], [
        ["Moody's", "Aa3", "Negative", "Review on 23 October 2026"],
        ["S&amp;P", "A+", "Stable", "Review on 27 November 2026"],
        ["Fitch", "A+", "Stable", "Last reviewed 28 August 2026"],
        ["Scope", "A+", "Stable", "Downgraded on 18 September 2026"],
    ])
    precedents = table(["Episode", "Spread move", "What decided it", "Bondholders"], [
        ["France 2011", "+119 bp, April to November", "Euro-area contagion; ECB long-term lending, then OMT in 2012",
         "Paid in full"],
        ["Italy 2011–12", "to above 500 bp", "Change of government, then Draghi's \"whatever it takes\" and OMT",
         "Paid in full"],
        ["Italy 2018", "129 → 307 bp in six months", "Populist budget clash with Brussels; compromise in December",
         "Paid in full"],
        ["Greece 2010–12", "to above 2,000 bp", "Official loans, IMF, then private-sector haircut", "About 53% haircut"],
        ["France June 2024", "48 → 81 bp in a week", "Snap legislative election", "Paid in full"],
    ], caption="Monthly averages (FRED / OECD) except June 2024 (daily). The trade pays on the spread and does not need a default.")
    calendar = table(["Date", "Event", "Why it matters"], [
        ["13 Oct 2026", "National Assembly opens the plenary debate on the 2027 budget",
         "The Finance Committee already rejected major savings on 7 October"],
        ["Late Oct", "First Assembly votes on the revenue part (expected around 20 and 27 Oct)",
         "First test of whether the Socialists or the RN tolerate the package"],
        ["23 Oct", "Moody's review (Aa3, negative outlook)", "A cut to A1 would align Moody's with the other agencies"],
        ["25 Nov (approx.)", "50-day deadline for the social security budget (PLFSS)", "Pensions and benefits freeze in play"],
        ["27 Nov", "S&amp;P review (A+, stable)", "Earlier downgrades moved yields little"],
        ["Mid-Nov to mid-Dec", "Article 49.3 and no-confidence motions",
         "The first binary event: the two previous prime ministers fell on their budgets"],
        ["15 Dec (approx.)", "70-day deadline for the state budget; ordinances possible",
         "The government can enact its own version by decree if parliament has not decided"],
        ["31 Dec", "Year-end: budget, ordinances or a stop-gap \"special law\"", "A stop-gap law means no 2027 savings"],
        ["18 Apr 2027", "Presidential election, first round", "Marine Le Pen leads every poll at 31–38%"],
        ["2 May 2027", "Presidential run-off", "Le Pen wins every tested run-off in current polling"],
        ["May–Jun 2027", "Likely dissolution and legislative elections", "The main stress window: months without a "
                                                                          "government able to legislate"],
        ["1 Jul 2027", "Trade horizon ends", "Any open position is closed"],
    ])
    scen = table(["Scenario", "What it looks like", "Spread by mid-2027", "Probability"], [
        ["Relief", "Budget passes, oil falls, positioning clears; spread back toward pre-summer levels", "about 85 bp",
         "15%"],
        ["Grind", "Budget passes with concessions or by 49.3; downgrades shrugged off", "140–170 bp", "50%"],
        ["<strong>Italy-2018 stress</strong>", "Budget fails or the government falls; contested election; French "
                                               "banks fall 30–40%", "<strong>200–300 bp</strong>", "<strong>30%</strong>"],
        ["<strong>Backstop contested</strong>", "New government clashes with Brussels; TPI eligibility openly in doubt",
         "<strong>above 300 bp</strong>", "<strong>5%</strong>"],
        ["Restructuring or euro exit", "Excluded: no clean instrument, and well below 1%", "–", "&lt;1%"],
    ], caption="Subjective probabilities, set in our 5 October proposal from the source research (France Tail Risk, "
               "28 September 2026), with five points moved from grind to relief. They are our judgement and are not derived from market prices.",
       row_classes=["", "", "total", "total", ""])
    res = table(["Exit level", "Clean move, no pull-back", "Simulation average", "What it takes"], [
        ["240 bp", f"{eur(s_final[240])} ({s_final[240] / BUDGET:.1f}×)", x(S["levels"]["240"]),
         "The lower half of an Italy-2018-style stress"],
        ["<strong>300 bp (base case)</strong>", f"<strong>{eur(s_final[300])} ({s_final[300] / BUDGET:.1f}×)</strong>",
         f"<strong>{x(S['levels']['300'])}</strong>", "Italy's 2018 peak"],
        ["340 bp", f"{eur(s_final[340])} ({s_final[340] / BUDGET:.1f}×)", x(S["levels"]["340"]),
         "Backstop contested"],
        ["400 bp", f"{eur(s_final[400])} ({s_final[400] / BUDGET:.1f}×)", x(S["levels"]["400"]),
         "Backstop contested, late ECB"],
    ], num_cols=(1, 2), row_classes=["", "total", "", ""],
        caption="Equity at exit for a €10,000 stake, net of commissions, bid-offer, carry and rolls. The simulation "
                "average is lower than the clean move because it includes paths stopped out by noise, late events "
                "and the cost of carry while waiting.")
    stats300 = table(["At 300 bp", "Value"], [
        ["Average payout", x(S["levels"]["300"])],
        ["Median payout", x(S["median"])],
        ["Paths returning 10× or more", pct(S["p_10x"])],
        ["Paths stopped out before the event", pct(S["p_lost"])],
        ["Best 5% of paths, threshold", x(S["p95"])],
        ["Average if no stress comes", x(S["wrong_mean"])],
    ], num_cols=(1,))
    sens = table(["Test", "Average payout at 300 bp", "Stopped out before the event"], [
        ["Base case", x(S["levels"]["300"]), pct(S["p_lost"])],
        ["Spread volatility 50% higher than the last six months", x(SV["levels"]["300"]), pct(SV["p_lost"])],
        ["Event in the first third of the horizon (Oct 2026 – Jan 2027)", x(S["by_timing"][0]), "–"],
        ["Event in the middle third (Jan – Apr 2027)", x(S["by_timing"][1]), "–"],
        ["Event in the last third (Apr – Jul 2027)", x(S["by_timing"][2]), "–"],
        ["Bunds rally strongly during the stress (flight to quality)", x(S["by_f"][2]), "–"],
        ["One check a day at the close instead of resting orders", x(MT["daily_close"]["300"]["mean"]),
         pct(MT["daily_close"]["300"]["p_lost"])],
        ["Weekly checks only", x(MT["weekly_all"]["300"]["mean"]), pct(MT["weekly_all"]["300"]["p_lost"])],
    ], num_cols=(1, 2))
    card = []
    for i, r in enumerate(s_rows[:7]):
        card.append([r[0], f"≈ {s0 + r[1]:.0f} bp", eur(r[3]), f"{r[4]} / {r[5]}", f"€{r[4] * ef:,.0f}"])
    ladder = table(["Step", "Spread", "Equity", "Short FOAT / long FGBL", "Gain per bp"], card, num_cols=(2, 4),
                   caption="Clean path for a €10,000 unit. Each step resizes the position to equity ÷ 40 bp, so a "
                           "40 bp pull-back from the latest step costs no more than the equity at risk at that step. "
                           "The position is capped at 20 Euro-OAT contracts per unit.")
    costs = table(["Cost", "Size", "Comment"], [
        ["Commissions and bid-offer", f"about €{FEE_SIDE:.2f} per contract per side",
         "Eurex futures via IBKR / LYNX; both contracts trade in one-tick markets"],
        ["Total trading costs, run to 300 bp", f"about {eur(fee_300)}",
         f"Entry, five resizings, three quarterly rolls and exit; under 1% of the {eur(s_final[300])} outcome"],
        ["Total trading costs, no stress", f"about {eur(fee_wrong)}", "Entry, three rolls and exit"],
        ["Carry (cost of holding)", f"about {carry_q:.1f} bp a quarter, €{carry_day_eur:.0f} a day at the starting size",
         f"French futures trade at a discount that erodes as they approach delivery. Over the full horizon about "
         f"{eur(carry_total)} at the starting size: the main cost if no stress comes"],
        ["Margin", "Posted from account cash, returned at exit",
         "Covers the starting position; at the 20-contract cap it is a multiple of the original unit and is funded "
         "from accrued profits. Not a cost, but the account needs liquidity beyond the risk budget"],
        ["Option premium", "None", "No time value is paid, which is why the trade outpays options on the same view"],
    ])

    # ── sections ──
    s1 = f"""
<p class="lead">France has become the fault line of the euro area. Its ten-year government bond, the OAT, yields
{snap.oat10:.2f}%, near the highest level since 2002. The premium over German Bunds has widened from 84 basis points
(bp) at the end of August to {s0:.0f} bp today, after touching about 150 bp on 5 October. France now borrows at a
higher rate than Italy, Spain and Greece.</p>
<p>The trigger is political. A minority government has to pass a €54bn consolidation budget through a fragmented
parliament before the end of the year, six months before a presidential election that the far-right candidate leads
in every poll. The two previous prime ministers fell on their budgets. Euro-area finance ministers told Paris on
8 October to pass the budget to calm markets. ECB President Christine Lagarde reminded them that the ECB's backstop,
the Transmission Protection Instrument (TPI), comes with eligibility conditions. France, under an EU excessive deficit
procedure, does not meet them today.</p>
<p>The cleanest way to express this view is the spread between French and German ten-year yields. It removes what
moves every bond market together (oil, inflation, the ECB's rate path) and leaves the price investors demand for
holding France instead of Germany. In 2018 Italy's spread rose from 129 bp to 307 bp in six months during a budget
clash with Brussels. We expect France to follow a similar path into the 2027 election.</p>
<div class="edge-box">
  <div class="edge-item"><h4>The trade</h4><p>Sell Euro-OAT futures and buy Euro-Bund futures in equal interest-rate
  sensitivity on Eurex. The position earns about €{3 * ef:.0f} for every basis point the spread widens, whether
  German yields rise or fall. Each time the spread widens by 20 bp, the profits are reinvested and the position grows
  with the move, while a trailing stop protects the gains. The risk is set at €10,000 per unit and the payout profile
  resembles a deep out-of-the-money option, without paying an option premium.</p></div>
  <div class="edge-item"><h4>The payout</h4><p>If the spread reaches 300 bp, the level of Italy's 2018 peak, before
  1 July 2027, our simulation turns €10,000 into {x(S['levels']['300'], 1)} on average and {x(S['median'], 1)} in the
  median case. At 240 bp the payout is {x(S['levels']['240'], 1)}; at 400 bp it is {x(S['levels']['400'], 1)}. If no
  stress comes, the average path returns about half the stake.</p></div>
</div>
{boxes([(x(S['levels']['240'], 1), 'Average payout at 240 bp', 'g'), (x(S['levels']['300'], 1), 'Average payout at 300 bp', 'g'),
        (x(S['median'], 1), 'Median payout at 300 bp', 'g'), (x(S['levels']['400'], 1), 'Average payout at 400 bp', 'g'),
        (x(S['wrong_mean'], 2), 'Average if no stress', 'r')])}
<h3 class="sub">Why now</h3>
<p>We put a 35% probability on the spread reaching 240 bp or more by mid-2027: 30% for an Italy-2018-style stress and
5% for a contested backstop. A standard pricing model at 65 bp of annual volatility put the same outcome at about 7%
on 5 October. Markets price French risk as a slow grind; we see a political sequence with a fixed timetable and no
backstop on hand. The spread has also eased about 10 bp from its 5 October level, which improves the entry.</p>
<div class="risk-box"><h4>What investors should know</h4><ul>
<li>The view can be right and still lose: a 40 bp pull-back before the main move stops the trade out. In the
simulation this happens on {pct(S['p_lost'])} of the paths that eventually reach 300 bp.</li>
<li>Without a stress, the carry and normal market noise cost about half the stake on average.</li>
<li>The stop is managed daily and a weekend headline can move the spread past it.</li></ul></div>
"""

    s2 = f"""
<p class="lead">France combines a persistent primary deficit, a parliament without a majority and an ECB that has
raised rates twice this year instead of cutting. Each of these could be managed on its own. Together they explain why
the spread has moved at crisis speed.</p>
<h3 class="sub">Where the market stands</h3>
{mkt}
<div class="chart-box">{ch_recent}</div>
<p class="note">Daily CNBC 10-year yields, October 2024 to 8 October 2026; last point {asof}.</p>
<p>The speed of the move matters as much as the level. The spread was 84 bp on 28 August. In the third quarter the
French ten-year yield rose by the most in a single quarter since 1987, and on 8 October it stood close to 5%.
Part of the rise is global: oil prices driven by the US–Iran conflict pushed euro-area inflation up, French inflation
reached 3.4% in September, and the ECB raised rates twice. The spread strips out that global component. What remains
is the price of France itself, which has risen by about 54 bp in six weeks.</p>
<div class="chart-box">{ch_long}</div>
<p class="note">Monthly averages from FRED / OECD long-term rates, January 2007 to August 2026, with today's live
spread. Monthly averages understate intra-month peaks.</p>
<h3 class="sub">The fiscal arithmetic</h3>
{fiscal}
<p>France has run primary deficits for most of the past two decades. With a primary deficit of about 3% of GDP, the
debt ratio keeps rising even if interest rates stop climbing, unless nominal growth outpaces the interest bill by a
wide margin. It does not. The average cost of the debt stock has risen from about 1.25% in 2020 to around 2%, and
each new bond is issued near 5%. With an average maturity of about eight and a half years, every year of record
issuance locks higher costs into the budget for a decade. Allianz Trade estimates that stabilising the debt would take
savings of more than €80bn, against the €54bn on the table.</p>
<h3 class="sub">The political sequence</h3>
<p>Prime Minister Sébastien Lecornu leads a minority government. His 2027 budget freezes public-sector pay and all but
the lowest pensions, tightens local-government spending and extends a corporate tax surcharge. On 7 October the
Assembly's Finance Committee rejected several of the savings measures before the plenary debate had begun. Finance
Minister Roland Lescure has said the government is prepared to use Article 49.3, which passes a bill without a vote
but exposes the government to a no-confidence motion. That is how the two previous prime ministers fell. If parliament
has not decided within 70 days of filing, the government can enact its budget by ordinance, a route that is legal but
politically explosive.</p>
<p>Behind the budget sits the presidential election of 18 April and 2 May 2027. Marine Le Pen of the Rassemblement
National polls 31–36% in the first round (Ifop, 30 September) and wins every run-off tested by Toluna Harris
Interactive, by 55–45 against Édouard Philippe and 68–32 against Jean-Luc Mélenchon. She is running while appealing a
conviction to the Court of Cassation. Her economic programme asks the ECB to bring down French borrowing costs once
France "takes back control". A run-off between Le Pen and Mélenchon, both opposed to fiscal consolidation, is the
most hostile outcome for bonds. A dissolution and new legislative elections are widely expected after the
presidential vote.</p>
<h3 class="sub">The ECB and Europe</h3>
<p>The TPI allows the ECB to buy a country's bonds without limit when spreads move in an "unwarranted, disorderly"
way. It has never been used. Eligibility rests on compliance with the EU fiscal framework, the absence of severe
imbalances, a sustainable debt path and sound policies, and the ECB alone decides. France has been under an excessive
deficit procedure since July 2024 and its fiscal path does not match the agreed consolidation. On 8 October officials
made clear that no euro-area institution was ready to step in and that the uncertainty was for French politicians to
resolve. Apollo's chief economist expects the ECB to wait until spreads threaten financial stability. A backstop that
is real but late and conditional is exactly the gap this trade is designed to capture.</p>
<h3 class="sub">Ratings</h3>
{ratings}
<h3 class="sub">What the precedents teach</h3>
{precedents}
<p>Every euro-area crisis has followed the same sequence: adverse fiscal or political news, wider spreads, pressure on
banks and politics, then a negotiation between the national government, the Eurogroup and the ECB over who pays.
Bondholders lost money only when the official sector diagnosed insolvency (Greece). They were paid in full when the
ECB treated the episode as a crisis of confidence (Italy). France sits closest to Italy. The spread trade does not
need a default; it needs the negotiation phase, when spreads widen before the backstop arrives.</p>
<h3 class="sub">Calendar of events</h3>
{calendar}
"""

    s3 = f"""
<p class="lead">We expect the spread to reach at least 240 bp before 1 July 2027 and take 300 bp as the base-case
exit. The trade is evaluated by simulating 10,000 paths of the spread for each level, with realistic noise, costs
and timing, and running the trading rules on every path.</p>
<h3 class="sub">Scenarios and probabilities</h3>
{scen}
<h3 class="sub">Why 240 to 300 bp</h3>
<p>Italy in 2018 is the template. A populist government clashed with Brussels over its budget, the ECB had no
instrument tailored to the situation, and the spread rose 2.4-fold in six months to just over 300 bp before a
December compromise. France starts from a weaker fiscal position than Italy did in 2018, with a deeper investor base.
A move of the full 2018 size, 178 bp, would take France from today's {s0:.0f} bp to about {s0 + 178:.0f} bp; half
that move already reaches about {s0 + 89:.0f} bp. We therefore expect 240–300 bp in a stress. We set the base-case exit at 300 bp, the level at
which pressure on the ECB is likely to become impossible to ignore. Above 300 bp the trade is in the contested-backstop
scenario, where the payout grows further but the risk of an abrupt ECB intervention rises. That is why we take profit
there rather than wait.</p>
<h3 class="sub">What the market prices</h3>
<p>On 5 October a standard normal-volatility pricing model at 65 bp a year assigned a 7% chance to a spread above 240 bp
in June 2027 and 0.5% to one above 300 bp. Eurex options on the OAT future price yield volatility of about
{put['atm_bp']:.0f} bp a year, while the spread itself has realised about {vols['spread'][1]:.0f} bp a year over the
last six months. Options are therefore expensive, and the market treats a 2018-style move as remote. The spread trade
uses that combination: it needs no option premium and only has to survive spread noise of around
{vols['spread'][1]:.0f} bp a year on the way to a move of about {300 - s0:.0f} bp.</p>
<h3 class="sub">How the simulation works</h3>
<div class="step-flow">
 <div class="step"><div class="step-num">1</div><div class="step-name">Choose the timing</div><div class="step-desc">the stress completes on a random day before 1 Jul 2027</div></div>
 <div class="step"><div class="step-num">2</div><div class="step-name">Market noise</div><div class="step-desc">daily spread and Bund moves with fat tails, calibrated on the last six months</div></div>
 <div class="step"><div class="step-num">3</div><div class="step-name">The stress</div><div class="step-desc">a 15-day move to the target level, with doubled volatility</div></div>
 <div class="step"><div class="step-num">4</div><div class="step-name">Trade the rules</div><div class="step-desc">stops, reinvestment, rolls, commissions and carry on every path</div></div>
 <div class="step"><div class="step-num">5</div><div class="step-name">Score</div><div class="step-desc">equity at exit divided by the €10,000 stake</div></div>
</div>
<p>Before the stress, the spread and the Bund yield follow random walks without drift, with daily volatility of
{A['sig_s_daily']:.2f} bp and {A['sig_b_daily']:.2f} bp and fat tails that allow for occasional large days. The stress
itself takes 15 trading days and bridges the spread to the target, with twice the normal noise. During the stress
Bunds rally by 10% to 70% of the widening, which covers both a 2018-style move and a flight to German safety. A second
set of paths has no stress at all and shows what happens if the view is wrong. About 190 alternative structures were
tested on the same paths, including outright futures, short French equities and Eurex options. The spread trade with
a 40 bp stop and reinvestment every 20 bp ranked first at every level.</p>
<h3 class="sub">Results</h3>
<div class="chart-box">{ch_pay}</div>
{stats300}
<p>The payout rises steeply with the exit level because the position grows with the move. At 300 bp three out of four
paths return ten times the stake or more. The paths that fail are those in which a pull-back of 40 bp hits the stop
before the main move. Without a stress the trade loses its carry and suffers normal market noise, and the average
outcome is {x(S['wrong_mean'])}: an investor recovers about half of the stake on average, with a wide range around
that figure.</p>
<h3 class="sub">Sensitivities</h3>
{sens}
<p>Timing is the main sensitivity. An early stress leaves less time for noise and carry to erode the position; a late
one leaves more. The share of the widening that comes from a Bund rally makes almost no difference, because the two
legs are matched in interest-rate sensitivity.</p>
"""

    s4 = f"""
<p class="lead">One position, two listed futures, one venue. The trade is executed on Eurex through Interactive
Brokers (LYNX) and needs no OTC documentation, no option premium and no counterparty other than the exchange
clearing house.</p>
<h3 class="sub">Structure</h3>
<div class="grid-2">
<div class="edge-item"><h4>Sell Euro-OAT futures (FOAT)</h4><p>Eurex future on French government bonds with 8.5 to
10.5 years to maturity, €100,000 nominal. Its price falls when French yields rise. One contract moves about
€{ef:.0f} per basis point of OAT yield. Indicative level today about {foat:.2f}.</p></div>
<div class="edge-item"><h4>Buy Euro-Bund futures (FGBL)</h4><p>Eurex future on German government bonds of the same
maturity, the most liquid bond future in Europe. One contract moves about €{FC['eur_per_bp']['FGBL']:.0f} per basis
point of Bund yield. Indicative level today about {fgbl:.2f}.</p></div>
</div>
<p>Selling three OAT futures and buying three Bund futures gives a position that gains about €{3 * ef:.0f} for every
basis point the spread widens. A parallel move in both yields barely changes its value. On real Eurex settlement
prices, this position would have made €11,490 between 11 September and 8 October 2026, when the spread widened by
45 bp.</p>
<h3 class="sub">How it compounds</h3>
<div class="chart-box">{ch_eq}</div>
<p>The trade starts with three contracts on each side. Each time the spread widens by a further 20 bp, the position is
resized so that a 40 bp pull-back would cost no more than the equity at risk at that point. In the early steps that
reinvests all profits, which is what turns a linear futures position into a convex one: the dashed line shows the
same entry without reinvestment. Once the position reaches 20 Euro-OAT contracts it stops growing, and the stop then
protects most of the accumulated profit. The stop is never moved down and there is no re-entry after it is hit.</p>
{ladder}
<h3 class="sub">Exit multiples</h3>
<p>The base-case exit is the first close at or above 300 bp. Investors who prefer to bank a stress earlier can exit at
240 bp. Those who expect the backstop to be contested can hold for 340 or 400 bp.</p>
{res}
<h3 class="sub">Costs</h3>
{costs}
<h3 class="sub">Operations</h3>
<p>The trade is checked once a day after the close. Eurex has no order book for an OAT–Bund spread, so the stop is
executed by closing both legs on the evening it is reached rather than by a resting order. The simulation shows that
this daily check gives the same result as a resting stop ({x(MT['daily_close']['300']['mean'])} against
{x(MT['daily_resting']['300']['mean'])}). Both futures are physically delivered, so the position is rolled to the
next quarterly contract three times, in early December, March and June, using Eurex calendar spreads. A typical
successful run needs about 15 to 20 orders over nine months, most of them during the stress itself.</p>
"""

    s5 = f"""
<p class="lead">The trade is designed to lose no more than the stake, and to lose it in a controlled way. The main
risks are that the stress does not come, that it comes in a way the stop cannot survive, or that it comes too late.</p>
<div class="risk-box"><h4>Material risks</h4><ul>
<li><strong>No stress by July 2027.</strong> The budget passes, the election produces a working majority or oil
prices fall, and the spread drifts between 120 and 170 bp. The trade then pays carry of about €{carry_day_eur:.0f} a day
and is exposed to noise; the average outcome is {x(S['wrong_mean'])} and many paths lose the full stake. This is the
most likely single outcome in our scenarios (65% for relief or grind combined).</li>
<li><strong>Right view, stopped out.</strong> A 40 bp pull-back before the main move, for example on a budget
compromise or an early ECB signal, ends the trade with no re-entry. This happens on {pct(S['p_lost'])} of the paths
that later reach 300 bp. It is the price of the convexity: a wider stop survives more noise but compounds more
slowly.</li>
<li><strong>Gap risk.</strong> The stop is executed by hand after the close. A weekend headline or an overnight ECB
announcement can move the spread well past the stop, and the loss can then exceed the €10,000 budget. Spread
volatility 50% above the recent level lowers the average payout at 300 bp to {x(SV['levels']['300'])} and raises the
stop-out rate to {pct(SV['p_lost'])}.</li>
<li><strong>ECB intervention.</strong> A credible TPI statement or a new purchase programme can compress the spread by
30–50 bp within days. In 2012 Italy's monthly spread fell from 475 bp in July to 349 bp in October after "whatever it
takes". The trailing stop and the 300 bp exit are designed to lock in profit before that point.</li>
<li><strong>Timing.</strong> A stress after July 2027, for example after a summer dissolution, falls outside the
horizon. A late stress inside the horizon pays less ({x(S['by_timing'][2])} at 300 bp) because carry and noise have had
longer to work.</li>
<li><strong>Margin and liquidity.</strong> Futures margin is posted from account cash and grows with the position. At the
20-contract cap it is a multiple of the original stake. Profits fund it, but the account needs liquidity beyond the
risk budget, and the broker can raise margin requirements in a crisis.</li>
<li><strong>Model risk.</strong> The probabilities are judgements and the simulation uses six months of calibration
data. Payouts are model estimates, not forecasts, and historical episodes do not repeat exactly.</li>
<li><strong>Operational risk.</strong> The trade needs a daily check, three rolls and disciplined execution of the
stop. Weekly monitoring lowers the average payout to {x(MT['weekly_all']['300']['mean'])}.</li>
</ul></div>
<h3 class="sub">What would make us close early</h3>
<p>We would exit before the target on a credible ECB statement that France qualifies for the TPI, on the start of TPI
purchases, or on a budget agreement backed by a stable majority. Each of these removes the gap between the market's
assumption of a cap and the ECB's actual reaction, which is where the trade earns its money.</p>
"""

    snap_tbl = table(["Market", "Level", "Source and time"], [
        ["France 10Y OAT yield", f"{snap.oat10:.3f}%", f"CNBC FR10Y, {asof}"],
        ["Germany 10Y Bund yield", f"{snap.bund10:.3f}%", f"CNBC DE10Y, {asof}"],
        ["OAT–Bund 10Y spread", f"{s0:.1f} bp", "Difference of the two"],
        ["Euro-OAT future, Dec 2026", f"≈ {foat:.2f}", "Put–call parity on the live Eurex OOAT chain"],
        ["Euro-Bund future, Dec 2026", f"≈ {fgbl:.2f}", "Put–call parity on the live Eurex OGBL chain"],
        ["OAT option implied volatility", f"{put['atm_iv'] * 100:.1f}% ≈ {put['atm_bp']:.0f} bp a year",
         "Eurex OOAT, 20 Nov 2026 at the money"],
        ["Spread realised volatility, 6 months", f"{vols['spread'][1]:.0f} bp a year", "Daily CNBC yields"],
    ])
    calib = table(["Input", "Value", "How measured"], [
        ["Euro-OAT € per bp", f"€{ef:.1f}", f"Regression of {FC['calib_days']} daily Eurex settlements on CNBC yields"],
        ["Euro-Bund € per bp", f"€{FC['eur_per_bp']['FGBL']:.1f}", "Same method"],
        ["Hedge ratio", f"{FC['hedge_ratio']:.3f} Bund per OAT future", "Equal € per bp on both legs"],
        ["Net carry", f"{carry_q:.1f} bp a quarter", "Average December–March calendar spread of each future"],
        ["Daily spread / Bund volatility", f"{A['sig_s_daily']:.2f} / {A['sig_b_daily']:.2f} bp, correlation "
                                           f"{A['rho']:.2f}", "Last six months of daily yields"],
        ["Fat tails", "Student-t, 4 degrees of freedom", "Allows for occasional large daily moves"],
        ["Trading costs", f"€{FEE_SIDE:.2f} per contract per side, 1 bp stop slippage", "Plus half the gap when a close "
                                                                                     "jumps through the stop"],
        ["Paths", "10,000 per level, same random seed for every structure", "Levels 240, 300, 340, 400 bp and no stress"],
    ])
    s6 = f"""
<h3 class="sub">Prices</h3>
{snap_tbl}
<h3 class="sub">Model inputs</h3>
{calib}
<h3 class="sub">Methodology</h3>
<p>The view and the scenario probabilities come from the source research (France Tail Risk, 28 September 2026) and our
5 October proposal. Market data were refreshed on {asof}: Eurex option chains and futures settlements, CNBC yields
(two years daily, ten years weekly) and FRED monthly yields for the historical episodes. The simulation draws daily
paths for the spread and the Bund yield to 1 July 2027, adds a 15-day stress on a random date, and applies the trading
rules, commissions, bid-offer, stop slippage, quarterly rolls and carry on each path. Payout multiples are equity at
exit divided by the stake. The option comparison prices Eurex OAT and Bund options at live bid and ask.</p>
<h3 class="sub">Sources</h3>
<div class="disclaimer">
<p>{link("ING THINK, France's budget offers no quick relief for bond markets, 1 Oct 2026", "https://think.ing.com/articles/frances-budget-offers-no-quick-relief-for-bond-markets/")} ·
{link("Reuters, Euro zone ministers tell France to pass 2027 budget to calm markets, 8 Oct 2026", "https://live.euronext.com/en/financial-news/euro-zone-ministers-tell-france-pass-2027-budget-calm-markets")} ·
{link("Wall Street Journal, French government is willing to bypass parliament, Oct 2026", "https://www.tovima.com/wsj/french-government-is-willing-to-bypass-parliament-to-pass-billions-in-cuts/")} ·
{link("France in English, Finance Committee rejects savings, 8 Oct 2026", "https://franceinenglish.com/p/french-government-faces-parliamentary-and-economic-criticism-over-2027-budget-proposal")} ·
{link("European Pulse, HCFP on the 2027 growth forecast", "https://europeanpulse.com/french-2027-growth-forecast-draws-scepticism-from-budget-watchdog")} ·
{link("Allianz Trade, Toasted, not burnt", "https://www.allianz-trade.com/en_global/news-insights/economic-insights/Toasted-not-burnt-France-bond-and-the-road-2027-election.html")} ·
{link("J.P. Morgan AM, An OAT-rageous autumn in France, 8 Oct 2026", "https://am.jpmorgan.com/us/en/asset-management/liq/insights/portfolio-insights/fixed-income/weekly-bond-bulletin/")} ·
{link("Apollo, French spreads, the ECB and the outlook for Europe, 8 Oct 2026", "https://www.apollo.com/content/dam/apolloaem/pdf/daily-spark/2026/oct/8/100826-FrenchDebtDynamics_v3.pdf")} ·
{link("EU Insider, France's bond rout meets Le Pen's budget pitch, 8 Oct 2026", "https://www.euinsider.eu/news/france-bond-rout-le-pen-budget-plan-eurogroup-2026")} ·
{link("Ifop poll via La Dépêche, 1 Oct 2026", "https://www.ladepeche.fr/2026/10/01/presidentielle-2027-sondage-marine-le-pen-caracole-en-tete-entre-31-et-36-edouard-philippe-qualifie-pour-le-second-tour-jean-luc-melenchon-elimine-13577982.php")} ·
{link("Toluna Harris Interactive, September 2026 voting intentions", "https://tolunacorporate.com/fr/intentions-de-vote-a-lelection-presidentielle-2027-septembre-2026-2/")} ·
{link("European Commission, Excessive deficit procedure: France", "https://economy-finance.ec.europa.eu/economic-governance-framework/stability-and-growth-pact/corrective-arm-excessive-deficit-procedure/excessive-deficit-procedures-overview/france_en")} ·
ECB, The Transmission Protection Instrument, 21 July 2022 · Eurex contract specifications (FOAT, FGBL, OOAT, OGBL) ·
FRED / OECD long-term interest rates · Euro Sovereign Crises: Greece, Cyprus, Italy and France under Stress
(29 September 2026) · France Tail Risk: Convex Trades on a French Sovereign Stress (28 September 2026).</p>
<p><strong>Disclaimer.</strong> This document is a trade idea for discussion among professional investors. It is not
investment advice and not an offer to buy or sell any instrument. Payouts are model estimates and probabilities are
subjective judgements. Futures positions can lose more than the stated risk budget in a market gap. Past episodes do
not predict future outcomes.</p>
</div>
"""

    extra_css = """
  .lead { font-size: 15px; color: #2a3a4c; }
  .note { font-size: 12px; color: var(--muted); }
  .sub { font-size: 13px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--muted);
         font-weight: 700; margin: 30px 0 12px; }
  .exec-table td.num, .exec-table th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .exec-table td.num { white-space: nowrap; }
  .exec-table tr.total td { background: #eef2f7 !important; font-weight: 700; color: var(--navy); }
  .exec-table caption { caption-side: bottom; text-align: left; font-size: 11.5px; color: var(--muted); padding-top: 8px; }
  .exec-table { font-size: 12.5px; margin-bottom: 8px; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: start; margin-bottom: 8px; }
  .chart-box { background: white; border: 1px solid #dde3ec; border-radius: 10px; padding: 14px; margin: 8px 0 12px; }
  .chart-img { width: 100%; display: block; }
  .edge-box { margin: 16px 0; }
  .step-flow { margin: 10px 0 22px; }
  .highlight-box .val { font-size: 22px; white-space: nowrap; }
  .kpi-value.negative { color: #ff8a7a; }
  .disclaimer a { color: var(--navy); }
"""
    sections = [
        ("summary", "01 / Executive Summary", "France is repricing. The spread trade compounds with it", s1),
        ("france", "02 / France", "Fiscal arithmetic, political deadlock and a conditional backstop", s2),
        ("model", "03 / Model and Assumptions", f"{x(S['levels']['300'], 1)} the stake if the spread reaches 300 bp", s3),
        ("trade", "04 / The Trade", "Short Euro-OAT, long Euro-Bund futures, with reinvested gains", s4),
        ("risks", "05 / Risks", "A defined budget, and the ways it can be lost", s5),
        ("sources", "06 / Sources, Methodology and Prices", "How the numbers were produced", s6),
    ]
    body = '<div class="divider"></div>'.join(
        f'<section id="{sid}"><div class="section-label">{lab}</div><h2>{h2}</h2>{html}</section>'
        for sid, lab, h2, html in sections)
    generated = datetime.now(ZoneInfo("Europe/Berlin"))
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>France Sovereign Stress · Trade Idea</title>
<style>
{CSS}
{extra_css}
</style>
</head>
<body>
<header class="report-header">
  <div class="header-eyebrow">Aureas GmbH · Trade Idea · {fetched:%d %B %Y}</div>
  <div class="header-title">France Sovereign Stress: Positioning for the Next Leg Wider</div>
  <div class="header-subtitle">A listed futures spread trade on the OAT–Bund spread that reinvests its gains as the
  stress unfolds. €10,000 at risk per unit; {x(S['levels']['300'], 1)} on average if the spread reaches 300 bp before
  July 2027.</div>
  <div class="kpi-strip">{kpi_html}</div>
</header>
<div class="content">
{body}
</div>
<footer>
  <strong>France Sovereign Stress · Trade Idea</strong><br>
  Prices as of {asof} · Generated {generated:%d %B %Y, %H:%M} CEST<br>
  Aureas GmbH · Confidential · For professional investors, for discussion only, not investment advice
</footer>
</body>
</html>
"""
    out = ROOT / "reports" / f"france_sovereign_stress_v5_pitch_{fetched:%Y-%m-%d}.html"
    out.write_text(html, encoding="utf-8")
    shutil.copy(out, JOB / "output" / out.name)
    print(out, f"{len(html) / 1024:.0f} KB", "fees", round(fee_300), round(fee_wrong), "carry/day", round(carry_day_eur),
          "carry total", round(carry_total), "sides", sides)


if __name__ == "__main__":
    main()
