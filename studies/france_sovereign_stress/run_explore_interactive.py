#!/usr/bin/env python3
"""Build a self-contained interactive HTML explorer (Chart.js + embedded JSON).

Writes ``explore_interactive.html`` at the study root. Data comes from
``data/canvas_explore.json`` and ``data/exit_level_grid.json`` (regenerate those
first if missing via ``run_explore_report.py --force``).

Usage:
    python studies/france_sovereign_stress/run_explore_interactive.py [--check]

``--check`` runs the agent_commons writing quality scan over the prose and
prints findings.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

from agent_commons.brand import load_brand
from agent_commons.brand.css import render as render_brand_css
from agent_commons.writing import contains_em_dash

from src.data.reference import load_eurex_snapshot
from src.paths import data_dir, load_config
from src.scenarios import ScenarioConfig

EYEBROW = "CryoQuant research · France sovereign stress · market snapshot {{date_short}}"
TITLE = "Trading a French spread blowout: an interactive scenario book"

LEDE = (
    "On {{date_long}} French 10-year government bonds yielded {{s0}} bp more than German "
    "ones. This book prices one way to trade a widening to 240 bp or more before 1 July "
    "2027: sell Euro-OAT futures, buy Euro-Bund futures in duration-matched size, risk a "
    "fixed €10,000, and add to the position as the spread moves your way. Below you find "
    "the thesis, the exact trading rules, the inputs, how the simulation works and what "
    "the results mean. The interactive section at the end lets you change the rule, the "
    "volatility and the costs and see what happens to the payout."
)

SUMMARY_FIGURES = [
    ("{{mean300}}", "Mean ending equity if the spread reaches 300 bp", "{{eq_mean300}} on a €{{budget}} stake"),
    ("{{median300}}", "Median in the same case", "half the paths end above {{eq_median300}}"),
    ("{{lost300}}", "Stopped out on the way to 300 bp", "stress arrives, but too late for the stop"),
    ("{{wrong_lost}}", "Stopped out if no stress comes", "median outcome: the stake is gone"),
]

TERM_SHEET = [
    ("Position", "Short Euro-OAT (FOAT), long Euro-Bund (FGBL) on Eurex, {{hedge}} FGBL per FOAT"),
    ("Profits when", "French 10-year yields rise relative to German 10-year yields"),
    ("Entry", "{{date_long}}, spread {{s0}} bp"),
    ("Risk budget", "€{{budget}}, the full amount at risk"),
    ("Initial size", "Equity ÷ 40 bp = €{{entry_ebp}} per bp, about {{entry_foat}} FOAT against {{entry_fgbl}} FGBL"),
    ("Adds", "Each further +20 bp, net of carry: resize to equity ÷ 40 bp, all profit reinvested"),
    ("Stop", "40 bp below the last add, checked on the daily close, filled at the close less 1 bp, no re-entry"),
    ("Size cap", "20 FOAT against 18 FGBL, about {{cap_ebp}} per bp"),
    ("Exit with stress", "Close both legs on the day the spread reaches the exit level (default 300 bp)"),
    ("Exit without stress", "Close at the settlement of 1 July 2027"),
    ("Rolls", "First business day of December, March and June"),
    ("Costs", "€2.00 commission and €5 bid–ask per contract per fill; carry about 0.1 bp a day against"),
]

PRESET_TABLE = [
    ("Base case", "Stop 40, add +20, daily-close stop", "{{mean300}}", "{{lost300}}"),
    ("Tighter rule", "Stop 30, add +15", "{{tight_mean}}", "{{tight_lost}}"),
    ("Resting stop", "Base rule, filled as if the stop sat on the exchange", "{{resting_mean}}", "{{resting_lost}}"),
    ("Volatility × 1.5", "Base rule, daily spread and Bund moves 50% larger", "{{vol15_mean}}", "{{vol15_lost}}"),
    ("Calmer volatility", "Base rule, volatility from before September ({{sig_calm}} bp a day)", "{{calm_mean}}", "{{calm_lost}}"),
    ("Short CAC 40", "CAC 40 index futures, stop 12%, add every 6% decline", "{{cac_mean}}", "{{cac_lost}}"),
]

GLOSSARY = [
    ("Multiple", "Ending equity divided by the risk budget (here €{{budget}}). 15× means fifteen times that stake. 0× means the stake is gone. Slightly negative means a stop filled past its level after a gap."),
    ("Stress world", "Paths in which the spread reaches the chosen exit level before July 2027. All headline payouts are conditional on this."),
    ("No-event world", "Paths with no stress. The spread wanders without drift and the trade runs to 1 July 2027 unless stopped."),
    ("Exit level", "The spread at which the stress completes and the trade closes, from 200 to 400 bp."),
    ("Stopped out", "Paths that end with €1,000 or less (0.1× or below). Almost all are stop-outs."),
    ("p10, p50, p90", "Percentiles across paths. 10% of paths end below p10, half below p50 (the median), 90% below p90."),
    ("Net move (X)", "The spread change since entry minus accrued carry. Adds and stops are measured on this number."),
    ("€ per bp", "Profit or loss of the position for a one basis point change in the spread. One FOAT is worth {{foat}} per bp."),
    ("Completion day", "The business day on which the stress reaches its exit level, drawn at random for each path."),
    ("Bund share (f)", "The part of the spread jump that comes from Bund yields falling rather than OAT yields rising."),
]

PRESET_INFO = {
    "base": (
        "Base case",
        "The primary book: stop 40 bp under the last add, add every +20 bp, all checked on the daily close.",
    ),
    "tight": (
        "Tighter rule: stop 30, add +15",
        "Adds sooner and stops sooner. It builds size faster in a clean move and gets shaken out more often by noise.",
    ),
    "resting": (
        "Resting-stop fills",
        "Same rule as the base case, but fills the stop as if it rested on the exchange: at the stop level less 1 bp, plus half of any gap. Shows how little the daily-close assumption costs.",
    ),
    "vol15": (
        "Volatility × 1.5",
        "Same rule, with daily spread and Bund moves 50% larger. Tests a noisier tape before the stress arrives.",
    ),
    "calm": (
        "Calmer volatility",
        "Same rule, with spread volatility from a window that ends before the September widening ({{sig_calm}} bp a day instead of {{sig_s}}).",
    ),
    "cac": (
        "Short CAC 40 futures",
        "A different instrument: short CAC 40 index futures, stop 12%, add every 6% of decline. The index falls with the spread through its measured sensitivity. Only the 300 bp exit is simulated.",
    ),
}

SECTIONS: list[tuple[str, str, str]] = [
    (
        "summary",
        "Summary",
        """
<p>The trade is long the French-German spread: short Euro-OAT futures against long
Euro-Bund futures on Eurex, in equal euros per basis point. It makes money when
French yields rise relative to German ones, and it is close to flat when both move
together. A stop 40 bp below the last add caps the loss at the €10,000 budget, and
every further 20 bp of widening is reinvested into a larger position.</p>
<div class="figures">%%FIGURES%%</div>
<p>The payout depends on two things: the stress has to arrive, and the stop must
survive the noise before it does. If the spread reaches 300 bp at some point before
July 2027, a 10,000-path simulation gives a mean of {{mean300}} the stake. A quarter of
those paths still lose: the spread first moves 40 bp against the last add, the stop
closes the book, and the later blowout comes too late.</p>
<p>If no stress comes, the trade is a bet on drift. Of those paths, {{wrong_lost}} are
stopped out and the median result is the loss of the full stake. The mean of {{wrong_mean}}
comes from a minority of paths that widen far enough without a defined event. Size the
trade on the assumption that the €10,000 can go to zero.</p>
""",
    ),
    (
        "idea",
        "The trade idea",
        """
<p>The view is that the OAT-Bund spread reprices from {{s0}} bp into a 200 to 300 bp
range over the 2026 budget fight and the run-up to the 2027 presidential election,
with a smaller chance of a move beyond 300 bp. Four facts support it.</p>
<ul>
<li><strong>Budget.</strong> A minority government has to close a gap of about
€54 billion by year-end. A failed vote or a confidence motion can force a new
government or early elections.</li>
<li><strong>Election.</strong> The presidential election falls in April and May 2027,
inside the trade horizon. Polls put Marine Le Pen first with 31 to 38% of the
first-round vote. Analysts see a runoff against Jean-Luc Mélenchon as the worst case
for bonds, because both oppose fiscal tightening.</li>
<li><strong>No easy backstop.</strong> France is in the EU excessive deficit procedure.
That makes it harder for the ECB to use its Transmission Protection Instrument, the
tool it created in 2022 to buy the bonds of a country whose spread widens without
fundamental cause.</li>
<li><strong>Price action.</strong> The spread widened about 45 bp between 11 September
and 8 October 2026. The market has started to price the risk but sits well below
the levels Italy reached in 2011 and 2018.</li>
</ul>
<p>The model prices a market repricing and leaves out default or a euro exit. In
each stress path the spread reaches a target level on some day before July 2027,
Bund yields fall by part of the move as money looks for safety, and the position
closes at the target.</p>
<p>Futures are the most practical vehicle for a private account. FOAT and FGBL are
the most liquid listed contracts on French and German 10-year debt, they trade one
tick wide through most of the European session, and retail brokers such as IBKR and
Lynx offer them. A duration-matched pair isolates the spread and stays close to flat
when euro rates move in parallel.</p>
""",
    ),
    (
        "trade",
        "The trade: entries, exits and conditions",
        """
<p>The rules below fix every decision in advance. The simulation applies them to
each path mechanically, and a trader could run them by hand from a daily close
sheet.</p>
<table class="terms"><tbody>%%TERMS%%</tbody></table>
<p><strong>Entry and size.</strong> On {{date_long}} you sell FOAT and buy FGBL in a
ratio of {{hedge}} FGBL per FOAT. At that ratio both legs move by the same euro amount for
a one basis point change in their yields: {{foat}} for one FOAT, {{fgbl}} for one FGBL.
The stop sets the size. The book risks all of its equity over 40 bp, so €10,000
buys €250 per bp, which is about 3 FOAT against 3 FGBL.</p>
<p><strong>Adds.</strong> Each time the spread has widened another 20 bp since the last
add, net of carry, you resize the position to current equity ÷ 40 bp and move the
stop to 40 bp below the new level. All profit goes back into the trade. Each add
lifts equity by about half. After the first 20 bp the account holds about {{add1_equity}}
and carries {{add1_ebp}} per bp. On a straight move the position reaches its cap of 20 FOAT
against 18 FGBL near {{cap_level}} bp, with {{cap_equity}} of equity. Beyond the cap each further
20 bp adds about {{per20_at_cap}}.</p>
<p><strong>Stop.</strong> The stop is hard and there is no re-entry. Until the cap
binds, the book always risks its full equity over 40 bp, so a stop-out after any add
loses almost everything built so far. Once the cap binds, the risk stays at about
{{cap_risk}} while equity keeps growing, and the stop starts to lock in profit.</p>
<p><strong>Execution.</strong> Eurex lists no order book for the OAT-Bund pair, so a
broker cannot hold a resting stop on the spread. The simulation checks the spread
once a day at the close. If the close is at or through the stop, it exits at the
close less 1 bp. A close that gaps far through the stop loses more than the stake,
which shows up in the results as a multiple just below zero, typically −0.1×. Adds
are taken on the same daily close.</p>
<p><strong>Exit.</strong> In a stress path you close both legs on the day the spread
reaches the exit level. The default is 300 bp, and the fine grid in the interactive
section tests every level from 200 to 400 bp in 10 bp steps. Without a stress the
position runs to the close of 1 July 2027, unless the stop has triggered first.</p>
<p><strong>Rolls, costs and carry.</strong> Both legs roll on the first business day of
December, March and June, ahead of each delivery month. Every fill pays €2.00
commission and €5 of bid–ask, half the €10 tick, per contract. Opening 3 against 3
costs about €42, and a roll at the 20 against 18 cap costs about €560. Carry works
against the position at about {{carry_net}} bp per business day, close to {{carry_total}} bp over the full
horizon. In the no-event world the spread has to widen by about that much before the
trade breaks even.</p>
""",
    ),
    (
        "sizing",
        "Sizing and margin",
        """
<p>The risk budget is the euros you allow the stop to consume. Size is equity ÷ 40 bp
at entry and after each add. Multiples in this book are for a €{{budget}} stake; they
scale almost one-for-one with a larger unit because the rule is proportional. Absolute
euro P&amp;L and initial margin both rise with the number of contracts.</p>
<p><strong>Risk budget versus margin.</strong> The stop is a P&amp;L limit. Initial margin is
cash the clearing house locks while the futures are open. They are not the same. At a
€10,000 budget the entry book is about 3 FOAT against 3 FGBL and the stop can consume
roughly that €10,000 over 40 bp. Overnight initial margin for that book is about
€{{entry_im_10k}} under current IBKR Europe (Eurex Prisma) rates, additive across the two
legs. A live portfolio may show a little less if the house credits the offset between
short OAT and long Bund.</p>
<p><strong>Scaling the unit.</strong> The table compares three risk budgets. Entry contracts
are rounded to whole FOAT and FGBL. The contract cap stays 20 FOAT against 18 FGBL, so a
larger unit reaches the cap earlier in the spread and then runs with more euros per bp
already on.</p>
<table class="terms presets"><thead><tr>
<th>Risk budget</th><th>Entry size</th><th>Entry IM</th><th>At the cap</th><th>Cap IM</th>
</tr></thead><tbody>%%MARGIN_COMPARE%%</tbody></table>
<p>Per contract (as of {{margin_asof}}): FOAT about €{{im_foat}}, FGBL about €{{im_fgbl}},
from IBKR Europe overnight initial previews. There is no listed OAT–Bund spread on Eurex,
so the legs are two separate orders. Calendar spreads in SpreadTrader are a different
product and post far less margin.</p>
<p><strong>Ladder for the primary €{{budget}} unit.</strong> Margin rises with each add.</p>
<table class="terms presets"><thead><tr>
<th>Step</th><th>Spread</th><th>FOAT / FGBL</th><th>€ / bp</th><th>Additive IM</th>
</tr></thead><tbody>%%MARGIN_LADDER%%</tbody></table>
<p>Choose the risk budget so that entry IM and especially cap IM sit comfortably inside
account excess liquidity after other positions. Raises of the unit to €15,000 or €20,000
multiply contracts and margin roughly in proportion until the cap binds.</p>
""",
    ),
    (
        "inputs",
        "Inputs and calibration",
        """
<p><strong>Market levels.</strong> A live quote taken at {{quote_clock}} on {{date_long}}:
OAT 10-year at {{oat}}, Bund 10-year at {{bund}}, spread {{s0}} bp, all from CNBC. This
sets the entry. Eurex settlement prices for the front two FOAT and FGBL contracts and
two years of daily CAC 40 closes complete the data. Every estimate below uses closes
up to {{history_end_long}}, the last full session before the quote.</p>
<p><strong>Contract risk.</strong> A 20-day regression of each future's settlement price
on its cash yield gives the euro value of one basis point: {{foat}} for FOAT and {{fgbl}}
for FGBL. Their ratio, {{hedge}}, sets the hedge. Carry comes from the price gap between
the front and the next contract: {{carry_foat}} bp a day on FOAT and {{carry_fgbl}} bp on FGBL, so the
spread position pays about {{carry_net}} bp a day.</p>
<p><strong>Volatility.</strong> The last 126 business days of closes give a daily
standard deviation of {{sig_s}} bp for the spread and {{sig_b}} bp for the Bund yield, with a
correlation of {{rho}} between them. The window includes the September and October
widening, so the estimate leans high. A window that ends before September gives
{{sig_calm}} bp a day for the spread and runs as the "calmer volatility" preset.</p>
<p><strong>Costs.</strong> Lynx charges €2.00 per Eurex futures contract, confirmed on a
live OAT round trip on 12 October 2026 (commission €2.00 each side; the market was one
tick wide). The model uses that €2.00 fee and a €5 half-tick. Swissquote Luxembourg also
charges €2.00 per contract, with a €9.95 minimum per order. FGBL usually trades one tick
wide in European hours and two to three ticks overnight. Neither contract trades at
weekends.</p>
<p><strong>Check against the live position.</strong> Three FOAT against three FGBL held
from 11 September to 8 October 2026 marks to {{live_pnl}} on Eurex settlements, a {{live_bp}} bp
widening. The model's contract values reproduce that figure.</p>
""",
    ),
    (
        "engine",
        "How the simulation works",
        """
<p>Each run draws daily paths from {{date_long}} to 1 July 2027. Daily moves come
from a fat-tailed distribution (Student-t with 4 degrees of freedom) scaled to the
measured volatility, with no drift. Every exit level and every preset reuses the same
random draws, so a difference between two results comes from the rule or the level
and not from sampling luck. The headline figures use 10,000 paths. The interactive
charts use 1,500 to 2,000 paths to keep this file small, and their numbers differ
from the headline by a few hundredths.</p>
<p>The same draws feed two worlds.</p>
<ul>
<li><strong>No-event world.</strong> The driftless paths run to the horizon and the
trade closes on 1 July 2027 if the stop has not triggered.</li>
<li><strong>Stress world.</strong> For each path the model picks a completion day at
random, anywhere from the 15th business day to the horizon. Over the 15 business days
before it, the spread follows a bridge that lands exactly on the exit level, with
twice the usual daily noise along the way. Bund yields fall by a share f of the jump,
drawn between 10% and 70%, to reflect money moving into Bunds. The trade exits on the
completion day.</li>
</ul>
<p>Because the two legs are duration-matched, the Bund share barely matters: split
into thirds by f, the mean payouts at 300 bp are {{f_t1}}, {{f_t2}} and {{f_t3}}. Timing matters
far more. Paths whose stress completes in the first third of the horizon average
{{tc_t1}}, and those in the last third {{tc_t3}}. A late stress leaves more noisy days during
which the stop can trigger, and more days of carry.</p>
""",
    ),
    (
        "reading",
        "What the numbers mean",
        """
<p>Every result is ending equity divided by the €10,000 budget. A multiple of 15×
means the account ends at €150,000. 0× means the stake is gone. −0.1× means a stop
filled through its level after a gap and the loss ran about €1,000 past the stake.</p>
<p>Outcomes fall into two groups with almost nothing in between. Paths that survive
until the stress end high, and paths that hit the stop before it end near zero. That
split puts the median above the mean: at 300 bp the median is {{median300}} and the mean
{{mean300}}. "Stopped out" counts paths that end at 0.1× or below, that is, with €1,000 or
less.</p>
<p>The stress-world figures are conditional. They assume the spread reaches the exit
level before July 2027 and say nothing about how likely that is. For an unconditional
figure, weight the two worlds with your own odds. With a 35% chance of a stress that
reaches 300 bp and 65% of no event, the blended mean is 0.35 × {{mean300_n}} + 0.65 × {{wrong_mean_n}},
about {{blend}}. The study's own scenario odds (relief 15%, grind 50%, stress 30%,
contested 5%) are recorded in the configuration and feed none of the charts.</p>
<p>The pyramid produces most of the payout. The same entry with a stop and no adds
averages {{stop_only}} at 300 bp, against {{mean300}} with adds.</p>
""",
    ),
    (
        "presets",
        "Variants of the rule",
        """
<p>The interactive section offers six presets. The table gives their full-run
results for a stress that reaches 300 bp.</p>
<table class="terms presets"><thead><tr><th>Preset</th><th>What changes</th>
<th>Mean at 300 bp</th><th>Stopped out</th></tr></thead><tbody>%%PRESETS%%</tbody></table>
<p>The tighter rule earns about the same mean with far more stop-outs, so it is a
worse trade for the same thesis. Volatility matters most: daily moves 50% larger cut
the mean from {{mean300}} to {{vol15_mean}} and nearly double the share of paths stopped out. A
resting exchange stop would change almost nothing, so the daily-close assumption is
not driving the results.</p>
<p>The CAC 40 short pays far less in the stress world but holds up better without
one, with a mean of {{cac_wrong}}. A book of 75% spread trade and 25% CAC short averages {{mix_mean}}
at 300 bp, with a median of {{mix_median}} and {{mix_lost}} of paths stopped out. The payouts of the
two sleeves have a correlation of only {{mix_corr}} across paths, so one often survives where
the other is stopped out.</p>
""",
    ),
    (
        "risks",
        "Risks, in order of importance",
        """
<ol>
<li><strong>Stop-out before the stress.</strong> A quarter of the stress paths lose the
stake on the way to 300 bp. With daily moves 50% larger, close to half do.</li>
<li><strong>No stress at all.</strong> Without an event, {{wrong_lost}} of paths are stopped out and
the median result is the loss of the stake.</li>
<li><strong>Margin.</strong> At the 20 against 18 cap, additive overnight IM is about
€{{cap_im_10k}} for a €10,000 unit (see Sizing and margin). The simulation funds adds from
open profit; a broker may not credit all of it in time. Keep excess liquidity for the
cap, not only for entry.</li>
<li><strong>Execution in a sell-off.</strong> The model charges a constant half tick. In a
disorderly French sell-off FOAT will trade wider, and size at the close may not be
available. Weekend news arrives as a Monday gap.</li>
<li><strong>Shape of the stress.</strong> Each stress path lands exactly on the exit level
and the trade exits there. Real spreads overshoot and retrace and seldom stop at a
round number. The model has no overshoot-and-retrace path.</li>
<li><strong>Contract values.</strong> The euro value per basis point comes from a 20-day
regression, without cheapest-to-deliver analytics, and drifts as yields move. The hedge
ratio needs checking at each roll.</li>
</ol>
""",
    ),
    (
        "watch",
        "What to watch",
        """
<p>The French budget has to pass by the end of 2026, and a failed vote or a confidence
motion is the nearest catalyst. The December contracts stop trading on 8 December
2026, so the first roll falls on 1 December. The presidential election in April and
May 2027 is the largest scheduled event inside the horizon, which ends on
1 July 2027.</p>
""",
    ),
]


def _x(v: float) -> str:
    return f"{v:.1f}×"


def _pct(v: float) -> str:
    return f"{100 * v:.0f}%"


def _eur(v: float, step: int = 100) -> str:
    return f"€{round(v / step) * step:,.0f}"


def _long_date(d: str) -> str:
    dt = date.fromisoformat(d)
    return f"{dt.day} {dt:%B %Y}"


def prose_values(explore: dict, p5: dict) -> dict[str, str]:
    """Numbers quoted in the prose, all from the active run's outputs."""
    meta, cal, sens = explore["meta"], p5["calibration"], p5["sensitivities"]
    a300, wrong = p5["primary"]["at_300"], p5["primary"]["wrong"]
    ladder = explore["straight_line"]["ladder"]
    capped = [r for r in ladder if r["foat"] == 20]
    foat = cal["eur_per_bp"]["FOAT"]
    carry_net = cal["carry_bp_per_day"]["FOAT"] - cal["hedge_ratio"] * cal["carry_bp_per_day"]["FGBL"]
    horizon = ScenarioConfig.from_study_config(load_config()).end
    bdays = int(np.busday_count(meta["start"], horizon))
    quote = datetime.fromisoformat(meta["quote_time"]) if meta.get("quote_time") else None
    y = load_eurex_snapshot(meta["stamp"]).get("yields", {})
    f_t, tc_t = sens["bund_flight_terciles"]["means"], sens["timing_terciles"]["means"]
    mix = sens["mix_75_25"]
    margin = explore.get("margin") or {}
    b10 = (margin.get("budgets") or {}).get("10000", {})
    primary_m = (margin.get("budgets") or {}).get(str(int(meta["budget"])), b10)
    return {
        "date_long": _long_date(meta["start"]),
        "date_short": f"{date.fromisoformat(meta['start']):%-d %b %Y}",
        "history_end_long": _long_date(meta["history_end"]),
        "quote_clock": f"{quote:%H:%M} CEST" if quote else "the reference stamp",
        "s0": f"{meta['s0_report']:g}",
        "oat": f"{y['oat10']:.3f}%" if y else "n/a",
        "bund": f"{y['bund10']:.3f}%" if y else "n/a",
        "mean300": _x(a300["mean"]),
        "mean300_n": f"{a300['mean']:.1f}",
        "median300": _x(a300["median"]),
        "lost300": _pct(a300["p_lost"]),
        "eq_mean300": _eur(meta["budget"] * a300["mean"], 1000),
        "eq_median300": _eur(meta["budget"] * a300["median"], 1000),
        "wrong_lost": _pct(wrong["p_lost"]),
        "wrong_mean": _x(wrong["mean"]),
        "wrong_mean_n": f"{wrong['mean']:.1f}",
        "blend": _x(0.35 * a300["mean"] + 0.65 * wrong["mean"]),
        "hedge": f"{cal['hedge_ratio']:.3f}",
        "foat": f"€{foat:.2f}",
        "fgbl": f"€{cal['eur_per_bp']['FGBL']:.2f}",
        "carry_foat": f"{cal['carry_bp_per_day']['FOAT']:.3f}",
        "carry_fgbl": f"{cal['carry_bp_per_day']['FGBL']:.3f}",
        "carry_net": f"{carry_net:.1f}",
        "carry_total": f"{carry_net * bdays:.0f}",
        "sig_s": f"{cal['vol']['sig_s']:.2f}",
        "sig_b": f"{cal['vol']['sig_b']:.2f}",
        "rho": f"{cal['vol']['rho']:.2f}",
        "sig_calm": f"{cal['vol_calm']['sig_s']:.2f}",
        "live_pnl": f"+€{p5['live_pnl']['pnl_eur']:,.0f}",
        "live_bp": f"{p5['live_pnl']['spread_change_bp']:.1f}",
        "add1_equity": _eur(ladder[1]["equity"]),
        "add1_ebp": _eur(ladder[1]["equity"] / 40, 10),
        "cap_level": f"{capped[0]['spread_bp']:.0f}",
        "cap_equity": _eur(capped[0]["equity"], 1000),
        "per20_at_cap": _eur(capped[1]["equity"] - capped[0]["equity"], 1000),
        "cap_risk": _eur(20 * foat * 40, 1000),
        "cap_ebp": _eur(20 * foat, 10),
        "f_t1": _x(f_t[0]), "f_t2": _x(f_t[1]), "f_t3": _x(f_t[2]),
        "tc_t1": _x(tc_t[0]), "tc_t3": _x(tc_t[2]),
        "stop_only": _x(sens["stop_only"]["at_300"]["mean"]),
        "tight_mean": _x(sens["stop_30_15"]["at_300"]["mean"]),
        "tight_lost": _pct(sens["stop_30_15"]["at_300"]["p_lost"]),
        "resting_mean": _x(sens["resting_stop"]["at_300"]["mean"]),
        "resting_lost": _pct(sens["resting_stop"]["at_300"]["p_lost"]),
        "vol15_mean": _x(sens["vol_x1.5"]["at_300"]["mean"]),
        "vol15_lost": _pct(sens["vol_x1.5"]["at_300"]["p_lost"]),
        "calm_mean": _x(sens["calmer_vol"]["at_300"]["mean"]),
        "calm_lost": _pct(sens["calmer_vol"]["at_300"]["p_lost"]),
        "cac_mean": _x(sens["cac"]["right"]["mean"]),
        "cac_lost": _pct(sens["cac"]["right"]["p_lost"]),
        "cac_wrong": _x(sens["cac"]["wrong"]["mean"]),
        "mix_mean": _x(mix["stats"]["mean"]),
        "mix_median": _x(mix["stats"]["median"]),
        "mix_lost": _pct(mix["stats"]["p_lost"]),
        "mix_corr": f"{mix['corr']:.2f}",
        "budget": f"{meta['budget']:,.0f}",
        "entry_foat": str(primary_m.get("entry_foat", meta.get("entry_foat", 3))),
        "entry_fgbl": str(primary_m.get("entry_fgbl", meta.get("entry_fgbl", 3))),
        "entry_ebp": _eur(meta["budget"] / 40, 10),
        "margin_asof": margin.get("asof", "n/a"),
        "im_foat": f"{margin.get('im_foat_eur', 0):,.0f}",
        "im_fgbl": f"{margin.get('im_fgbl_eur', 0):,.0f}",
        "entry_im_10k": f"{b10.get('entry_im_eur', 0):,.0f}",
        "cap_im_10k": f"{b10.get('cap_im_eur', 0):,.0f}",
    }


def fill(text: str, values: dict[str, str]) -> str:
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values[m.group(1)], text)


def _load_json(name: str) -> dict:
    path = data_dir() / name
    if not path.exists():
        raise SystemExit(
            f"Missing {path}. Run phase runners / run_explore_report.py --force first."
        )
    return json.loads(path.read_text())


def _chart_colors(pal: dict) -> dict[str, str]:
    return {
        "text": pal.get("text", "#edf2f9"),
        "muted": pal.get("muted", "#8fa3bc"),
        "grid": pal.get("grid", "#1e2d45"),
        "info": pal.get("equity", "#3b9eff"),
        "danger": pal.get("drawdown", "#ff5c6c"),
        "success": "#3d7a6a",
        "warning": pal.get("gold", "#c9a84c"),
        "neutral": pal.get("muted", "#8fa3bc"),
        "panel": pal.get("panel", "#0f1a2b"),
        "bg": pal.get("bg", "#070d18"),
    }


def _esc(text: str) -> str:
    return html_lib.escape(text, quote=False)


def _prose_html(values: dict[str, str], explore: dict) -> str:
    figures = "".join(
        f'<div class="stat"><strong>{_esc(v)}</strong><span>{_esc(lab)}</span>'
        f'<em>{_esc(sub)}</em></div>'
        for v, lab, sub in SUMMARY_FIGURES
    )
    terms = "".join(f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in TERM_SHEET)
    presets = "".join(
        f"<tr><td>{_esc(a)}</td><td>{_esc(b)}</td><td>{c}</td><td>{d}</td></tr>"
        for a, b, c, d in PRESET_TABLE
    )
    margin = explore.get("margin") or {}
    compare_rows = []
    for b, block in (margin.get("budgets") or {}).items():
        compare_rows.append(
            "<tr>"
            f"<td>€{int(b):,}</td>"
            f"<td>{block['entry_foat']} / {block['entry_fgbl']}</td>"
            f"<td>€{block['entry_im_eur']:,.0f}</td>"
            f"<td>{block['cap_foat']} / {block['cap_fgbl']} near {block['cap_spread_bp']:.0f} bp</td>"
            f"<td>€{block['cap_im_eur']:,.0f}</td>"
            "</tr>"
        )
    primary = (margin.get("budgets") or {}).get(str(int(float(explore["meta"]["budget"]))), {})
    ladder_rows = []
    for r in primary.get("rows") or []:
        ladder_rows.append(
            "<tr>"
            f"<td>{_esc(r['step'])}</td>"
            f"<td>{r['spread_bp']:.1f} bp</td>"
            f"<td>{r['foat']} / {r['fgbl']}</td>"
            f"<td>€{r['eur_per_bp']:,.0f}</td>"
            f"<td>€{r['im_eur']:,.0f}</td>"
            "</tr>"
        )
    out = []
    for sid, head, body in SECTIONS:
        body = (
            body.replace("%%FIGURES%%", figures)
            .replace("%%TERMS%%", terms)
            .replace("%%PRESETS%%", presets)
            .replace("%%MARGIN_COMPARE%%", "\n".join(compare_rows))
            .replace("%%MARGIN_LADDER%%", "\n".join(ladder_rows))
        )
        out.append(f'<section class="prose" id="{sid}"><h2>{_esc(head)}</h2>{body}</section>')
    return "\n".join(out)



def _glossary_html() -> str:
    return "".join(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>" for k, v in GLOSSARY)


def _toc_html() -> str:
    items = [(sid, head) for sid, head, _ in SECTIONS] + [("explorer", "Interactive book")]
    return "".join(f'<a href="#{sid}">{_esc(h)}</a>' for sid, h in items)


def prose_plain_text(values: dict[str, str]) -> str:
    """All reader-facing copy as plain text, for quality and em-dash checks."""
    parts = [LEDE]
    parts += [f"{v} {lab} {sub}" for v, lab, sub in SUMMARY_FIGURES]
    parts += [f"{k}: {v}" for k, v in TERM_SHEET]
    parts += [" ".join(r) for r in PRESET_TABLE]
    parts += [f"{k}: {v}" for k, v in GLOSSARY]
    parts += [f"{a}. {b}" for a, b in PRESET_INFO.values()]
    for _, head, body in SECTIONS:
        text = re.sub(r"%%\w+%%", "", body)
        text = re.sub(r"<[^>]+>", " ", text)
        parts.append(head + ". " + re.sub(r"\s+", " ", text).strip())
    return fill("\n\n".join(parts), values)


def _prepare_explore(explore: dict, values: dict[str, str]) -> dict:
    out = json.loads(json.dumps(explore))
    for pid, preset in out["presets"].items():
        label, note = PRESET_INFO.get(pid, (preset["label"], ""))
        preset["label"] = label
        preset["note"] = fill(note, values)
    cac = out["presets"].get("cac")
    if cac is not None:
        cac.pop("sample_paths_300", None)
        cac.pop("path0_events", None)
    return out


def build_html(explore: dict, grid: dict, p5: dict) -> str:
    values = prose_values(explore, p5)
    plain = prose_plain_text(values)
    if contains_em_dash(plain):
        raise SystemExit("em dash in prose")

    brand = load_brand("cryo-dark")
    css = render_brand_css(brand)
    colors = _chart_colors(brand.palette)

    payload = {
        "explore": _prepare_explore(explore, values),
        "grid": grid,
        "colors": colors,
        "full": {
            "n_paths": p5["n_paths"],
            "mean_300": p5["primary"]["at_300"]["mean"],
            "median_300": p5["primary"]["at_300"]["median"],
            "lost_300": p5["primary"]["at_300"]["p_lost"],
            "wrong_mean": p5["primary"]["wrong"]["mean"],
        },
    }
    data_js = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")

    replacements = {
        "%%BRAND_CSS%%": css,
        "%%BG%%": colors["bg"],
        "%%PANEL%%": colors["panel"],
        "%%TEXT%%": colors["text"],
        "%%MUTED%%": colors["muted"],
        "%%GRID%%": colors["grid"],
        "%%INFO%%": colors["info"],
        "%%DANGER%%": colors["danger"],
        "%%SUCCESS%%": colors["success"],
        "%%WARNING%%": colors["warning"],
        "%%EYEBROW%%": _esc(EYEBROW),
        "%%TITLE%%": _esc(TITLE),
        "%%LEDE%%": _esc(LEDE),
        "%%TOC%%": _toc_html(),
        "%%PROSE%%": _prose_html(values, explore),
        "%%GLOSSARY%%": _glossary_html(),
    }
    page = TEMPLATE
    for key, val in replacements.items():
        page = page.replace(key, val)
    return fill(page, values).replace("%%DATA%%", data_js)


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>France sovereign stress: interactive scenario book</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.6/dist/chart.umd.min.js"></script>
<style>
%%BRAND_CSS%%
:root {
  --bg: %%BG%%; --panel: %%PANEL%%; --text: %%TEXT%%; --muted: %%MUTED%%;
  --grid: %%GRID%%; --info: %%INFO%%; --danger: %%DANGER%%;
  --success: %%SUCCESS%%; --warning: %%WARNING%%;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: "IBM Plex Sans", "Segoe UI", sans-serif; line-height: 1.6;
}
.wrap { max-width: 1080px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }
.eyebrow { text-transform: uppercase; letter-spacing: 0.08em; font-size: 0.72rem; color: var(--muted); margin: 0 0 0.5rem; }
h1 { font-size: 1.9rem; font-weight: 600; margin: 0 0 0.75rem; line-height: 1.25; }
h2 { font-size: 1.25rem; font-weight: 600; margin: 0 0 0.75rem; }
h3 { font-size: 1.05rem; font-weight: 600; margin: 2rem 0 0.4rem; }
.lede { font-size: 1.07rem; max-width: 48rem; }
.toc { display: flex; flex-wrap: wrap; gap: 0.4rem 1rem; margin: 1.2rem 0 0.5rem; font-size: 0.85rem; }
.toc a { color: var(--muted); text-decoration: none; border-bottom: 1px dotted rgba(143,163,188,0.5); }
.toc a:hover { color: var(--text); }
.prose { margin: 2.2rem 0; }
.prose p, .prose li { max-width: 48rem; color: rgba(237,242,249,0.92); }
.prose p { margin: 0 0 0.9rem; }
.prose ul, .prose ol { margin: 0 0 0.9rem; padding-left: 1.3rem; max-width: 48rem; }
.prose li { margin-bottom: 0.45rem; }
.panel { background: var(--panel); border: 1px solid rgba(143,163,188,0.18); padding: 1.1rem 1.2rem 1.3rem; margin: 1.25rem 0; }
.controls { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 0.85rem 1rem; align-items: start; }
label { display: block; font-size: 0.78rem; color: var(--text); margin-bottom: 0.25rem; font-weight: 500; }
.hint { display: block; font-size: 0.72rem; color: var(--muted); margin-top: 0.25rem; line-height: 1.4; }
select { width: 100%; background: var(--bg); color: var(--text); border: 1px solid rgba(143,163,188,0.35); padding: 0.45rem 0.55rem; font: inherit; }
.stats, .figures { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.75rem; margin: 1rem 0; }
.stat { border: 1px solid rgba(143,163,188,0.2); padding: 0.75rem 0.85rem; background: rgba(7,13,24,0.35); }
.stat strong { display: block; font-size: 1.4rem; font-weight: 600; }
.stat span { display: block; font-size: 0.8rem; color: var(--text); margin-top: 0.15rem; }
.stat em { display: block; font-style: normal; font-size: 0.74rem; color: var(--muted); margin-top: 0.2rem; }
.note { font-size: 0.86rem; color: var(--muted); margin: 0.4rem 0 0; max-width: 48rem; }
.explain { border-left: 3px solid var(--info); background: rgba(59,158,255,0.07); padding: 0.7rem 0.95rem; margin: 0.6rem 0 0.8rem; font-size: 0.9rem; max-width: 52rem; }
.explain p { margin: 0 0 0.45rem; }
.explain p:last-child { margin-bottom: 0; }
.explain .ex { color: var(--text); }
.explain .ex::before { content: "Example: "; font-weight: 600; color: var(--info); }
.preset-note { border-left: 3px solid var(--warning); background: rgba(201,168,76,0.08); padding: 0.6rem 0.9rem; margin: 1rem 0 0; font-size: 0.9rem; }
.chart-box { position: relative; height: 330px; margin: 0.5rem 0 0.25rem; }
.chart-box.tall { height: 380px; }
table { width: 100%; border-collapse: collapse; font-size: 0.88rem; margin-top: 0.75rem; }
th, td { text-align: right; padding: 0.42rem 0.55rem; border-bottom: 1px solid rgba(143,163,188,0.18); }
th:first-child, td:first-child { text-align: left; }
thead th { color: var(--muted); font-weight: 500; font-size: 0.8rem; }
table.terms { max-width: 52rem; margin: 0.5rem 0 1.2rem; }
table.terms th, table.terms td { text-align: left; vertical-align: top; }
table.terms tbody th { width: 11rem; color: var(--muted); font-weight: 500; }
table.presets td:nth-child(3), table.presets td:nth-child(4), table.presets th:nth-child(3), table.presets th:nth-child(4) { text-align: right; }
caption { caption-side: top; text-align: left; color: var(--muted); font-size: 0.8rem; padding-bottom: 0.3rem; }
.pill { display: inline-block; font-size: 0.72rem; padding: 0.15rem 0.45rem; border: 1px solid rgba(143,163,188,0.35); color: var(--muted); margin-left: 0.4rem; vertical-align: middle; font-weight: 400; }
.callout { border-left: 3px solid var(--warning); padding: 0.65rem 0.9rem; background: rgba(201,168,76,0.08); margin: 1rem 0; font-size: 0.9rem; }
dl.gloss { display: grid; grid-template-columns: 10rem 1fr; gap: 0.35rem 1rem; font-size: 0.87rem; margin: 0.6rem 0 0; }
dl.gloss dt { color: var(--text); font-weight: 600; }
dl.gloss dd { margin: 0; color: rgba(237,242,249,0.85); }
details summary { cursor: pointer; color: var(--muted); font-size: 0.9rem; }
tr.cap td { color: var(--warning); }
footer { margin-top: 2.5rem; font-size: 0.8rem; color: var(--muted); }
@media (max-width: 760px) {
  .stats, .figures { grid-template-columns: repeat(2, 1fr); }
  .chart-box, .chart-box.tall { height: 290px; }
  dl.gloss { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="wrap">
  <p class="eyebrow">%%EYEBROW%%</p>
  <h1>%%TITLE%%</h1>
  <p class="lede">%%LEDE%%</p>
  <nav class="toc">%%TOC%%</nav>

  %%PROSE%%

  <section class="panel" id="explorer">
    <h2>Interactive book <span class="pill" id="rulePill"></span></h2>
    <p class="note">
      Every chart below reads from simulated paths computed in Python and embedded in this
      file. Changing a control switches between those stored results; nothing is
      recalculated in the browser. Open the glossary if a term is unfamiliar.
    </p>
    <details style="margin-top:0.7rem">
      <summary>Glossary</summary>
      <dl class="gloss">%%GLOSSARY%%</dl>
    </details>

    <div class="controls" style="margin-top:1.1rem">
      <div>
        <label for="preset">Trading rule and market</label>
        <select id="preset"></select>
        <span class="hint">Changes the summary figures and every chart except the first.</span>
      </div>
      <div>
        <label for="fee">Commission per contract per fill</label>
        <select id="fee"></select>
        <span class="hint">Base case €2.00. Affects the exit-level chart only.</span>
      </div>
      <div>
        <label for="halfTick">Bid–ask cost per contract per fill</label>
        <select id="halfTick"></select>
        <span class="hint">Base case €5, half of one €10 tick. Exit-level chart only.</span>
      </div>
      <div>
        <label for="equityMode">Equity chart shows</label>
        <select id="equityMode">
          <option value="bands">Spread of outcomes (percentiles)</option>
          <option value="low">One losing path</option>
          <option value="median">One typical winning path</option>
          <option value="high">One early, strong winner</option>
        </select>
        <span class="hint">Single paths are available for the bond-spread presets.</span>
      </div>
    </div>
    <div class="preset-note" id="presetNote"></div>

    <h3>Headline figures for this preset</h3>
    <div class="stats" id="stats"></div>
    <div class="callout" id="fullRun"></div>

    <h3>1. Payout by exit level</h3>
    <div class="explain">
      <p>Each point on the horizontal axis is a separate stress scenario: the spread climbs
      to that level, and the trade closes there. The lines show how the ending multiples are
      distributed across all paths for that scenario. Read them vertically: at any exit
      level, 10% of paths end below the red line, half below the green line and 90% below
      the grey line. The blue line is the average. This chart always uses the base rule and
      responds to the two cost controls.</p>
      <p class="ex" id="gridExample"></p>
    </div>
    <div class="chart-box tall"><canvas id="gridChart"></canvas></div>
    <p class="note" id="gridCaption"></p>
    <table id="gridTable"></table>

    <h3>2. Account equity over time, stress to 300 bp</h3>
    <div class="explain">
      <p id="equityWhat"></p>
      <p class="ex" id="equityExample"></p>
    </div>
    <div class="chart-box"><canvas id="equityChart"></canvas></div>

    <h3>3. Where the stress paths finish, exit at 300 bp</h3>
    <div class="explain">
      <p>Each bar counts the paths whose ending multiple falls in that range. The bar on the
      left holds paths that lost slightly more than the stake after a gap through the stop.</p>
      <p class="ex" id="histExample"></p>
    </div>
    <div class="chart-box"><canvas id="histChart"></canvas></div>

    <h3>4. Results at four exit levels</h3>
    <div class="explain">
      <p>The same preset at four exit levels. "Ends at 10× or more" is the share of stress
      paths that finish with at least €100,000. The no-event row shows the outcome if the
      stress never comes.</p>
      <p class="ex" id="levelExample"></p>
    </div>
    <table id="levelTable"></table>

    <div id="eventsBlock">
      <h3>5. One trade, step by step</h3>
      <div class="explain">
        <p>The first simulated path, from entry to exit, with the stress completing at 300 bp.
        The net move is the spread change since entry less accrued carry, and adds and stops
        are measured on it. Exposure is the position's profit or loss per basis point. Divide
        it by {{foat}} for the number of FOAT contracts; the FGBL leg is {{hedge}} times that.</p>
        <p class="ex" id="eventExample"></p>
      </div>
      <table id="eventTable"></table>
    </div>

    <h3>6. The rule on a straight line</h3>
    <div class="explain">
      <p>A path without noise: the spread rises steadily from {{s0}} bp, and the rule runs on whole
      contracts. It shows the sizing logic on its own. Rows in gold have reached the
      20 against 18 contract cap.</p>
      <p class="ex" id="straightExample"></p>
    </div>
    <div class="chart-box"><canvas id="straightChart"></canvas></div>
    <table id="ladderTable"></table>
  </section>

  <footer>
    Research only. No orders and no broker connections. Rebuild with
    <code>python studies/france_sovereign_stress/run_explore_interactive.py</code>.
    Chart.js loads from a CDN; all market and simulation data are embedded in this file.
  </footer>
</div>

<script id="DATA" type="application/json">%%DATA%%</script>
<script>
(function () {
  const DATA = JSON.parse(document.getElementById("DATA").textContent);
  const E = DATA.explore, G = DATA.grid, C = DATA.colors, FULL = DATA.full;
  const BUDGET = E.meta.budget, S0 = E.meta.s0, FOAT = E.meta.foat_eur_bp;

  const presetSel = document.getElementById("preset");
  const feeSel = document.getElementById("fee");
  const htSel = document.getElementById("halfTick");
  const equityMode = document.getElementById("equityMode");

  Object.values(E.presets).forEach((p) => {
    const o = document.createElement("option");
    o.value = p.id; o.textContent = p.label;
    presetSel.appendChild(o);
  });
  function fillCost(sel, opts, def) {
    (opts || []).forEach((o) => {
      const el = document.createElement("option");
      el.value = o.value;
      el.textContent = "€" + Number(o.value).toFixed(2) + (String(o.value) === String(def) ? " (base case)" : "");
      if (String(o.value) === String(def)) el.selected = true;
      sel.appendChild(el);
    });
  }
  fillCost(feeSel, G.fee_options, G.meta.default_fee);
  fillCost(htSel, G.half_tick_options, G.meta.default_half_tick);

  const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const x = (v, d) => Number(v).toFixed(d === undefined ? 1 : d).replace(/^-/, "−") + "×";
  const binText = (l) => (l.indexOf("–") > 0 ? l.replace("×", "").replace("–", "× and ") + "×" : l);
  const pct = (v) => Math.round(100 * v) + "%";
  const eur = (v) => (v < 0 ? "−€" : "€") + Math.round(Math.abs(v)).toLocaleString("en-GB");
  const eurX = (m) => eur(m * BUDGET);
  function fmtDate(iso) {
    const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
    return d + " " + MONTHS[m - 1] + " " + y;
  }
  function shortDate(iso) {
    const [, m, d] = iso.slice(0, 10).split("-").map(Number);
    return d + " " + MONTHS[m - 1];
  }
  function bizDate(n) {
    const dt = new Date(Date.UTC(2026, 9, 9));
    let left = n;
    while (left > 0) {
      dt.setUTCDate(dt.getUTCDate() + 1);
      const wd = dt.getUTCDay();
      if (wd !== 0 && wd !== 6) left -= 1;
    }
    return dt.getUTCDate() + " " + MONTHS[dt.getUTCMonth()] + " " + dt.getUTCFullYear();
  }
  const costKey = (fee, ht) => fee + "|" + ht;

  const axis = (title, fmt) => {
    const ticks = { color: C.muted, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 };
    if (fmt) ticks.callback = fmt;
    return { title: { display: true, text: title, color: C.muted, font: { size: 11 } },
      ticks, grid: { color: "rgba(30,45,69,0.55)" } };
  };
  function lineOpts(xTitle, yTitle, xFmt) {
    return {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: C.muted, boxWidth: 12, font: { size: 11 } } },
        tooltip: { callbacks: { label: (ctx) => ctx.dataset.label + ": " + x(ctx.parsed.y, 2) + " (" + eurX(ctx.parsed.y) + ")" } },
      },
      scales: {
        x: axis(xTitle, xFmt ? function (v) { return xFmt(this.getLabelForValue(v)); } : undefined),
        y: axis(yTitle, (v) => v + "×"),
      },
    };
  }
  function line(label, data, color, dashed) {
    return { label, data, borderColor: color, backgroundColor: color + "33",
      borderWidth: dashed ? 1.5 : 2.2, borderDash: dashed ? [5, 4] : [], pointRadius: 0, tension: 0.15, fill: false };
  }
  const charts = {};
  function draw(id, cfg) {
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart(document.getElementById(id), cfg);
  }

  function renderHeader(preset) {
    const at = preset.levels["300"] || Object.values(preset.levels)[0];
    const w = preset.wrong;
    document.getElementById("rulePill").textContent = preset.rule.replace(/\s*\(lock 0%\)/, "");
    document.getElementById("presetNote").innerHTML = "<strong>" + preset.label + ".</strong> " + preset.note;
    const tiles = [
      [x(at.mean), "Mean if the spread reaches 300 bp", "average ending equity " + eurX(at.mean)],
      [x(at.median), "Median in the same case", "half the paths end above " + eurX(at.median)],
      [pct(at.p_lost), "Stopped out on the way", "stress arrives, but these paths end with €1,000 or less"],
      [x(w.mean), "Mean if no stress comes", "median " + x(w.median) + ", " + pct(w.p_lost) + " of paths stopped out"],
    ];
    document.getElementById("stats").innerHTML = tiles.map(([v, l, s]) =>
      `<div class="stat"><strong>${v}</strong><span>${l}</span><em>${s}</em></div>`).join("");
    const full = document.getElementById("fullRun");
    if (preset.id === "base") {
      full.style.display = "block";
      full.innerHTML = `These figures come from ${E.meta.n_paths.toLocaleString("en-GB")} paths. ` +
        `The full ${FULL.n_paths.toLocaleString("en-GB")}-path run gives a mean of ${x(FULL.mean_300, 2)}, ` +
        `a median of ${x(FULL.median_300, 2)}, ${pct(FULL.lost_300)} stopped out, and ${x(FULL.wrong_mean, 2)} ` +
        `without a stress. The small gaps are sampling noise.`;
    } else {
      full.style.display = "none";
    }
  }

  function renderGrid(g, base) {
    const c = g.curve;
    draw("gridChart", {
      type: "line",
      data: {
        labels: c.map((r) => String(r.level_bp)),
        datasets: [
          line("p90 (best 10% start here)", c.map((r) => r.p90), C.neutral),
          line("p75", c.map((r) => r.p75), C.warning, true),
          line("Median (p50)", c.map((r) => r.p50), C.success),
          line("Mean", c.map((r) => r.mean), C.info),
          line("p25", c.map((r) => r.p25), C.warning, true),
          line("p10 (worst 10% end below)", c.map((r) => r.p10), C.danger),
        ],
      },
      options: lineOpts("Exit level: spread at which the stress completes (bp)", "Ending equity (multiple of €10,000)"),
    });
    const at = (lv, src) => src.curve.find((r) => r.level_bp === lv);
    const r300 = at(300, g), r240 = at(240, g), r340 = at(340, g), b300 = at(300, base);
    const lowLines = [["p10", r300.p10], ["p25", r300.p25]].filter(([, v]) => v < 0).map(([k]) => k);
    let txt = `At a 300 bp exit the median path turns €10,000 into ${eurX(r300.p50)} and the p90 path into ${eurX(r300.p90)}. `;
    if (lowLines.length) {
      txt += `The ${lowLines.join(" and ")} line${lowLines.length > 1 ? "s sit" : " sits"} below zero: ` +
        `those are the ${pct(r300.p_lost)} of paths stopped out before the stress arrived. `;
    }
    txt += `Moving the exit from 240 to 340 bp lifts the median from ${x(r240.p50)} to ${x(r340.p50)}, because each 20 bp past the contract cap adds about €35,000. `;
    const fee = Number(g.fee_per_side), ht = Number(g.half_tick_eur);
    if (g === base) {
      txt += `Costs are at the base case (€${fee.toFixed(2)} commission plus €${ht.toFixed(2)} bid–ask per contract per fill).`;
    } else {
      const d = r300.mean - b300.mean;
      txt += `With €${fee.toFixed(2)} commission and €${ht.toFixed(2)} bid–ask, the 300 bp mean is ${x(r300.mean, 2)}, ` +
        `${d >= 0 ? "+" : "−"}${Math.abs(d).toFixed(2)}× against the base case: costs move the result far less than the exit level does.`;
    }
    document.getElementById("gridExample").textContent = txt;
    document.getElementById("gridCaption").textContent =
      `Base rule, ${G.meta.n_paths.toLocaleString("en-GB")} paths per exit level, same random draws at every level. ` +
      `All-in cost €${(fee + ht).toFixed(2)} per contract per fill on both legs.`;
    const rows = c.filter((r) => r.level_bp % 20 === 0);
    document.getElementById("gridTable").innerHTML =
      "<caption>Every second level from the chart. Mean in euros is the average ending equity on a €10,000 stake.</caption>" +
      "<thead><tr><th>Exit level</th><th>Mean</th><th>Mean in €</th><th>p10</th><th>p25</th><th>Median</th><th>p75</th><th>p90</th><th>Stopped out</th></tr></thead><tbody>" +
      rows.map((r) => `<tr><td>${r.level_bp} bp</td><td>${x(r.mean, 2)}</td><td>${eurX(r.mean)}</td><td>${x(r.p10, 2)}</td>` +
        `<td>${x(r.p25, 2)}</td><td>${x(r.p50, 2)}</td><td>${x(r.p75, 2)}</td><td>${x(r.p90, 2)}</td><td>${pct(r.p_lost)}</td></tr>`).join("") +
      "</tbody>";
  }

  function renderEquity(preset) {
    const hasSamples = Boolean(preset.sample_paths_300);
    [...equityMode.options].forEach((o) => { if (o.value !== "bands") o.disabled = !hasSamples; });
    if (!hasSamples) equityMode.value = "bands";
    const b = preset.equity_bands_300;
    const what = document.getElementById("equityWhat"), ex = document.getElementById("equityExample");
    let datasets, opts = lineOpts("Date", "Equity (multiple of €10,000)", (v) => shortDate(v));

    if (equityMode.value === "bands") {
      datasets = [
        line("p90: 10% of paths are above this line", b.p90, C.success),
        line("Median: half above, half below", b.p50, C.info),
        line("p10: 10% of paths are below this line", b.p10, C.danger),
      ];
      what.textContent = "For every date, the lines show the spread of account equity across all stress paths with a 300 bp exit. " +
        "A line goes flat once the paths it represents are closed: the top line once those paths have reached 300 bp, " +
        "the bottom line once they have been stopped out.";
      const iLow = b.p10.findIndex((v) => v < 0.1);
      const iMed = b.p50.findIndex((v) => v >= 5);
      const iTop = b.p90.findIndex((v) => v >= 5);
      const parts = [];
      if (iTop > 0) parts.push(`The p90 line passes 5× by ${fmtDate(b.dates[iTop])}: the earliest tenth of the stresses have completed by then.`);
      if (iMed > 0) parts.push(`The median line passes 5× by ${fmtDate(b.dates[iMed])}, so roughly half the paths have reached 300 bp by that date.`);
      if (iLow > 0) parts.push(`The p10 line falls below 0.1× by ${fmtDate(b.dates[iLow])}: by then at least one path in ten has been stopped out, and those paths do not come back.`);
      ex.textContent = parts.join(" ") || "Read the gap between the lines as the uncertainty of the outcome on that date.";
    } else {
      const s = preset.sample_paths_300[equityMode.value];
      datasets = [line("Equity, path " + s.path_i, s.equity_x, C.info)];
      opts.scales.y2 = { position: "right", title: { display: true, text: "Spread (bp)", color: C.muted, font: { size: 11 } },
        ticks: { color: C.muted }, grid: { display: false } };
      datasets.push({ ...line("Spread (bp, right axis)", s.spread_bp, C.warning, true), yAxisID: "y2" });
      opts.plugins.tooltip = { callbacks: { label: (ctx) => ctx.dataset.yAxisID === "y2"
        ? "Spread: " + Number(ctx.parsed.y).toFixed(0) + " bp" : "Equity: " + x(ctx.parsed.y, 2) + " (" + eurX(ctx.parsed.y) + ")" } };
      what.textContent = "One simulated path. The blue line is account equity, the dashed gold line the spread on the right axis. " +
        "Equity goes flat when the trade closes, whether at the stop or at 300 bp.";
      const when = bizDate(s.tc);
      let t = `Path ${s.path_i} completes its stress on business day ${s.tc}, around ${when}, with Bund yields supplying ${Math.round(100 * s.f)}% of the jump. `;
      if (s.terminal_x < 0.1) {
        t += `The stop hit first: the spread moved against the position early, the stop closed the book at ${x(s.terminal_x, 2)} (${eurX(s.terminal_x)}), ` +
          `and the later climb to 300 bp no longer helped. In this preset ${pct(preset.levels["300"].p_lost)} of stress paths end like this.`;
      } else {
        t += `The stop held through the noise, the adds built the position to its cap, and the trade closed at 300 bp with ` +
          `${x(s.terminal_x, 2)}, or ${eurX(s.terminal_x)}.`;
        if (equityMode.value === "high") t += " An early stress leaves fewer days for the stop to trigger.";
      }
      ex.textContent = t;
    }
    draw("equityChart", { type: "line", data: { labels: b.dates, datasets }, options: opts });
  }

  function renderHist(preset) {
    const h = preset.hist_300;
    const n = E.meta.n_paths;
    const inBins = h.counts.reduce((a, b) => a + b, 0);
    const below = Math.max(n - inBins, 0);
    const labels = ["below 0×"].concat(h.labels.map((l) => l + "×"));
    const counts = [below].concat(h.counts);
    draw("histChart", {
      type: "bar",
      data: { labels, datasets: [{ label: "Number of paths", data: counts,
        backgroundColor: counts.map((_, i) => (i <= 1 ? C.danger + "99" : C.info + "99")),
        borderColor: counts.map((_, i) => (i <= 1 ? C.danger : C.info)), borderWidth: 1 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false },
          tooltip: { callbacks: { label: (ctx) => ctx.parsed.y + " paths (" + pct(ctx.parsed.y / n) + ")" } } },
        scales: {
          x: { ...axis("Ending multiple of the €10,000 stake"), grid: { display: false } },
          y: { ...axis("Number of paths, out of " + n.toLocaleString("en-GB")), beginAtZero: true },
        },
      },
    });
    const lost = below + h.counts[0];
    let iMax = 0;
    counts.forEach((v, i) => { if (v > counts[iMax]) iMax = i; });
    const middle = counts.slice(2, 7).reduce((a, b) => a + b, 0);
    let t = `${lost.toLocaleString("en-GB")} of ${n.toLocaleString("en-GB")} paths (${pct(lost / n)}) end at 0.1× or below, shown in red. ` +
      `The largest group, ${counts[iMax].toLocaleString("en-GB")} paths (${pct(counts[iMax] / n)}), ends ${iMax === 0 ? labels[0] : "between " + binText(labels[iMax])}. `;
    if (middle / n < 0.05) {
      t += "Almost no path ends between 0.1× and 10×: a stop before the stress takes nearly all the equity, and a path that survives reaches the cap.";
    } else {
      t += `${pct(middle / n)} of paths end between 0.1× and 10×, so this preset has more middle outcomes than the base case.`;
    }
    document.getElementById("histExample").textContent = t;
  }

  function renderLevels(preset) {
    const lv = Object.entries(preset.levels);
    const w = preset.wrong;
    document.getElementById("levelTable").innerHTML =
      "<thead><tr><th>Scenario</th><th>Mean</th><th>Mean in €</th><th>Median</th><th>Stopped out</th><th>Ends at 10× or more</th></tr></thead><tbody>" +
      lv.map(([k, s]) => `<tr><td>Stress to ${k} bp</td><td>${x(s.mean, 2)}</td><td>${eurX(s.mean)}</td><td>${x(s.median, 2)}</td>` +
        `<td>${pct(s.p_lost)}</td><td>${pct(s.p_10x)}</td></tr>`).join("") +
      `<tr><td>No stress, close 1 Jul 2027</td><td>${x(w.mean, 2)}</td><td>${eurX(w.mean)}</td><td>${x(w.median, 2)}</td>` +
      `<td>${pct(w.p_lost)}</td><td>${pct(w.p_10x)}</td></tr></tbody>`;
    const ex = document.getElementById("levelExample");
    if (preset.levels["240"] && preset.levels["340"]) {
      const a = preset.levels["240"], c = preset.levels["340"];
      ex.textContent = `A stress that stops at 240 bp pays a mean of ${x(a.mean)}; one that runs to 340 bp pays ${x(c.mean)}. ` +
        `The share of paths stopped out barely changes, because the stop decides before the stress whether a path survives. ` +
        `The exit level only decides how much the survivors make.`;
    } else {
      ex.textContent = `This preset was simulated at 300 bp only. Without a stress it averages ${x(w.mean, 2)}.`;
    }
  }

  function renderEvents(preset) {
    const block = document.getElementById("eventsBlock");
    const ev = preset.path0_events || [];
    if (!ev.length) { block.style.display = "none"; return; }
    block.style.display = "block";
    const names = { entry: "Entry", add: "Add", exit: "Exit at 300 bp", stop: "Stopped out", horizon: "Horizon close" };
    const m = /stop (\d+), add every \+(\d+)/.exec(preset.rule) || [null, "40", "20"];
    const stopBp = m[1], addBp = m[2];
    const bp = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(1) + " bp";
    document.getElementById("eventTable").innerHTML =
      "<thead><tr><th>Date</th><th>Action</th><th>Net move since entry</th><th>Exposure</th><th>≈ FOAT contracts</th><th>Equity</th><th>Stop at net move</th></tr></thead><tbody>" +
      ev.map((e) => `<tr><td>${fmtDate(e.date)}</td><td>${names[e.type] || e.type}</td><td>${bp(e.x)}</td>` +
        `<td>€${Math.round(e.units).toLocaleString("en-GB")} per bp</td><td>${(e.units / FOAT).toFixed(1)}</td>` +
        `<td>${eur(e.equity)}</td><td>${bp(e.stop)}</td></tr>`).join("") + "</tbody>";
    const entry = ev[0], add = ev.find((e) => e.type === "add"), last = ev[ev.length - 1];
    let t = `The trade opens on ${fmtDate(entry.date)} at €${Math.round(entry.units)} per bp, about ${(entry.units / FOAT).toFixed(1)} FOAT. ` +
      `Equity starts at ${eur(entry.equity)} because opening costs come off at once. `;
    if (add) {
      t += `On ${fmtDate(add.date)} the close shows a net move of ${bp(add.x)}, past the +${addBp} bp trigger, so the rule adds: ` +
        `exposure rises to €${Math.round(add.units)} per bp (about ${(add.units / FOAT).toFixed(1)} FOAT) and the stop moves to ${bp(add.stop)}, ${stopBp} bp below the add. `;
    }
    if (last.type === "exit") {
      const carry = 300 - S0 - last.x;
      t += `The path exits on ${fmtDate(last.date)} with ${eur(last.equity)}. Its final net move of ${last.x.toFixed(1)} bp is the ${(300 - S0).toFixed(0)} bp widening ` +
        `from ${S0.toFixed(0)} to 300 bp less ${carry.toFixed(1)} bp of carry.`;
    }
    document.getElementById("eventExample").textContent = t;
  }

  function renderStraight() {
    const sl = E.straight_line, c = sl.curve;
    draw("straightChart", {
      type: "line",
      data: { labels: c.map((r) => String(r.spread_bp)),
        datasets: [line("Equity on a straight-line path", c.map((r) => r.equity_x), C.warning)] },
      options: lineOpts("Spread (bp)", "Equity (multiple of €10,000)"),
    });
    const lad = sl.ladder;
    const capRow = lad.find((r) => r.foat === 20);
    const capIdx = lad.indexOf(capRow);
    document.getElementById("ladderTable").innerHTML =
      "<thead><tr><th>Step</th><th>Spread</th><th>Move since entry</th><th>FOAT sold</th><th>FGBL bought</th><th>Equity</th><th>Gain on the step</th></tr></thead><tbody>" +
      lad.map((r, i) => `<tr class="${i >= capIdx ? "cap" : ""}"><td>${r.step}</td><td>${r.spread_bp.toFixed(0)} bp</td>` +
        `<td>+${r.delta_bp.toFixed(0)} bp</td><td>${r.foat}</td><td>${r.fgbl}</td><td>${eur(r.equity)}</td>` +
        `<td>${i ? "+" + eur(r.equity - lad[i - 1].equity) : ""}</td></tr>`).join("") + "</tbody>";
    const after = lad[capIdx + 1];
    const f300 = sl.finals["300.0"];
    document.getElementById("straightExample").textContent =
      `Each add before the cap lifts equity by about half, from ${eur(lad[0].equity)} to ${eur(capRow.equity)} at ${capRow.spread_bp.toFixed(0)} bp. ` +
      (after ? `From there the size stays at 20 against 18 and each 20 bp adds ${eur(after.equity - capRow.equity)}. ` : "") +
      `At 300 bp the straight path holds ${eur(f300)} (${x(f300 / BUDGET)}). The simulated median at 300 bp is lower, ${x(FULL.median_300)}, ` +
      `because noisy paths trigger adds at uneven levels and pay carry along the way.`;
  }

  function refresh() {
    const preset = E.presets[presetSel.value] || E.presets.base;
    const base = G.grids[costKey(String(G.meta.default_fee), String(G.meta.default_half_tick))] || Object.values(G.grids)[0];
    const g = G.grids[costKey(feeSel.value, htSel.value)] || base;
    renderHeader(preset);
    renderGrid(g, base);
    renderEquity(preset);
    renderHist(preset);
    renderLevels(preset);
    renderEvents(preset);
  }

  [presetSel, feeSel, htSel, equityMode].forEach((el) => el.addEventListener("change", refresh));
  renderStraight();
  refresh();
})();
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="run the writing quality scan")
    args = ap.parse_args()

    if args.check:
        from agent_commons.writing.quality import scan_quality

        values = prose_values(_load_json("canvas_explore.json"), _load_json("phase5_evaluate.json"))
        report = scan_quality(prose_plain_text(values), style="investor")
        print(report.summary, f"score={report.score}", f"words={report.word_count}")
        for f in report.findings:
            print(" -", f)

    html = build_html(
        _load_json("canvas_explore.json"),
        _load_json("exit_level_grid.json"),
        _load_json("phase5_evaluate.json"),
    )
    out = STUDY_DIR / "explore_interactive.html"
    out.write_text(html)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
