"""v5 summary report: executive summary, models, the spread trade and the CAC 40 future (with tickets), options.

Reads data/v5/v5_<stamp>.json (+ _vol1.5, _beta0.6), extras_<stamp>.json, the Eurex chain snapshot and the history
CSVs. Writes reports/france_sovereign_stress_v5_trade_detail_<date>.html and a copy in the job output/.

    .venv/bin/python jobs/france-sovereign-stress/scripts/v5/build_report.py [--stamp 2026-10-09T1456]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

V5 = Path(__file__).resolve().parent
JOB = V5.parents[1]
ROOT = JOB.parents[1]
DATA = JOB / "data" / "v5"
sys.path.insert(0, str(V5))
sys.path.insert(0, str(V5.parent / "v4"))
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import options  # noqa: E402
from lib.chart_utils import ax_clean, save_b64, set_style  # noqa: E402
from lib.paths import TMP  # noqa: E402

CSS = (Path.home() / "agent-commons/agent_commons/templates/strategy_report.css").read_text()
BUDGET = 10_000
CAC_SPOT = 7802.8
CAC_TIME = "15:00 CEST (Yahoo ^FCHI)"
LEVELS = (240, 300, 340, 400)
STRESS = 300
EPISODES = [
    ["France 2011 (Apr→Nov, monthly)", "35 → 154 (+119)", "−23.2%", "−19.0%", "−22.6%", "−8.6%",
     "CAC −19.5% per 100 bp; CAC ≈ Euro Stoxx"],
    ["Italy 2018 (Apr→Oct, monthly)", "IT 129 → 307 (+178)", "−7.7%", "−9.2%", "−9.6%", "+2.4%",
     "FTSE MIB −20.6%: −11.6% per 100 bp, −6.2% vs Stoxx"],
    ["France snap election (7→14 Jun 2024)", "48 → 81 (+33)", "−6.2%", "−3.0%", "−4.2%", "+1.6%",
     "Eiffage −14.7%, Vinci −11.4%, AXA −11.3%"],
    ["France now (28 Aug→8 Oct 2026)", "84 → 139 (+55)", "−8.0%", "−6.6%", "−5.5%", "+0.7%",
     "Eiffage −9.8%, Vinci −6.5%, AXA −5.0%"],
]
STOCK_NAMES = {"^FCHI": "CAC 40 future (FCE)", "FGR.PA": "Eiffage", "DG.PA": "Vinci", "AMUN.PA": "Amundi",
               "AF.PA": "Air France-KLM", "URW.PA": "Unibail-Rodamco-Westfield", "CS.PA": "AXA", "ENGI.PA": "Engie",
               "ORA.PA": "Orange"}


def x(v, d=2):
    return f"{v:.{d}f}×"


def pct(v, d=0):
    return f"{v * 100:.{d}f}%"


def eur(v):
    return f"€{v:,.0f}"


def table(headers, rows, num_cols=(), caption="", row_classes=None):
    th = "".join(f'<th class="num">{h}</th>' if i in num_cols else f"<th>{h}</th>" for i, h in enumerate(headers))
    body = []
    for ri, r in enumerate(rows):
        tds = "".join(f'<td class="num">{c}</td>' if ci in num_cols else f"<td>{c}</td>" for ci, c in enumerate(r))
        rc = f' class="{row_classes[ri]}"' if row_classes and row_classes[ri] else ""
        body.append(f"<tr{rc}>{tds}</tr>")
    cap = f"<caption>{caption}</caption>" if caption else ""
    return f'<table class="exec-table">{cap}<thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def ticket(title, items):
    inner = "".join(f"<div class='k'>{a}</div><div class='v'>{b}</div>" for a, b in items)
    return f"<div class='ticket'><div class='ticket-title'>{title}</div><div class='ticket-kv'>{inner}</div></div>"


def boxes(items):
    return '<div class="highlight-row">' + "".join(
        f'<div class="highlight-box"><div class="val {c}">{v}</div><div class="lbl">{lab}</div></div>'
        for v, lab, c in items) + "</div>"


def chart(name, fig):
    path = TMP / f"chart_v5_{name}.b64"
    save_b64(fig, path)
    plt.close(fig)
    b64 = path.read_text()
    path.unlink()
    return f'<img class="chart-img" src="data:image/png;base64,{b64}" alt="{name}">'


def realized_vols():
    y = pd.read_csv(DATA / "yields_daily.csv", index_col=0, parse_dates=True)
    d = y[["oat10", "bund10"]].diff().dropna() * 100
    d["spread"] = d["oat10"] - d["bund10"]
    ann = lambda s: float(s.std() * np.sqrt(252))
    return {k: (ann(d[k]), ann(d[k].iloc[-126:])) for k in ("oat10", "bund10", "spread")}


def spread_ladder(fc, combo0):
    """Straight-line path for the spread trade: stop 40 bp, add every +20 bp, all-in, integer contracts."""
    ef, eg = fc["eur_per_bp"]["FOAT"], fc["eur_per_bp"]["FGBL"]
    pts = ef / 1000
    nf, ng, eq = 3, 3, float(BUDGET)
    stop0 = combo0 - BUDGET / (nf * 1000)
    rows = [("Entry", 0, combo0, eq, nf, ng, stop0, eq)]
    k = 0
    while True:
        k += 1
        lvl = 138.0 + 20 * k
        if lvl >= STRESS:
            break
        eq += 20 * nf * ef
        u = eq / 40
        nf = min(round(u / ef), 20)
        ng = min(round(u / eg), 18)
        c = combo0 + 20 * k * pts
        rows.append((f"Add {k}", 20 * k, c, eq, nf, ng, c - 40 * pts, min(eq, 40 * nf * ef)))
    finals = {}
    for L in LEVELS:
        e, n, last = float(BUDGET), 3, 0
        for kk in range(1, 100):
            if 20 * kk > L - 138.0:
                break
            e += 20 * n * ef
            n = min(round(e / 40 / ef), 20)
            last = 20 * kk
        finals[L] = e + (L - 138.0 - last) * n * ef
    return rows, finals, pts


def cac_ladder(st, p0):
    """Straight-line CAC path: stop 12%, add every 6% fall, all-in; minis (MFC, €1/pt), FCE = 10 minis."""
    unit = p0 / 100
    m, eq = 11, float(BUDGET)
    rows = [("Entry", p0, eq, m, p0 + BUDGET / m, eq)]
    for k in (1, 2, 3, 4):
        eq += 6 * unit * m
        m = min(round(eq / 12 / unit), 25)
        lvl = p0 * (1 - 0.06 * k)
        stop = p0 * (1 - 0.06 * k + 0.12)
        rows.append((f"Add {k}" if k < 4 else "Trail", lvl, eq, m, stop, min(eq, 12 * unit * m)))
    out = {}
    for L in LEVELS:
        ds = L - 138.0
        r = st["beta_s"] * ds + st["beta_b"] * (-0.4 * ds)
        fall = -(np.exp(r) - 1) * 100
        e, n, last = float(BUDGET), 11, 0.0
        for kk in range(1, 20):
            if 6 * kk > fall:
                break
            e += 6 * unit * n
            n = min(round(e / 12 / unit), 25)
            last = 6 * kk
        out[L] = (p0 * (1 - fall / 100), fall, e + (fall - last) * unit * n)
    return rows, out


def mini_split(m):
    f, r = divmod(m, 10)
    return " + ".join(s for s in ((f"{f} FCE" if f else ""), (f"{r} MFC" if r else "")) if s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="2026-10-09T1456")
    args = ap.parse_args()
    R = json.loads((DATA / f"v5_{args.stamp}.json").read_text())
    RV = json.loads((DATA / f"v5_{args.stamp}_vol1.5.json").read_text())
    RB = json.loads((DATA / f"v5_{args.stamp}_beta0.6.json").read_text())
    EX = json.loads((DATA / f"extras_{args.stamp}.json").read_text())
    chain = JOB / "data" / "chains" / f"eurex_{args.stamp}.json"
    snap = options.load_snapshot(chain)
    raw = json.loads(chain.read_text())
    A = R["assumptions"]
    FC = A["futures"]
    fetched = datetime.fromisoformat(R["snapshot"]["fetched_at"])
    asof = fetched.strftime("%d %B %Y, %H:%M CEST").lstrip("0")
    foat = snap.expiries[("OOAT", "20/11/2026")].fwd
    fgbl = snap.expiries[("OGBL", "20/11/2026")].fwd
    combo0 = round(fgbl - foat, 2)
    fut = {k: {m["expiry"]: m for m in v["months"]} for k, v in raw["futures"].items()}
    cal_o = fut["FOAT"]["20261208"]["settle"] - fut["FOAT"]["20270308"]["settle"]
    cal_b = fut["FGBL"]["20261208"]["settle"] - fut["FGBL"]["20270308"]["settle"]
    roll_shift = cal_o - cal_b
    spread_now = R["snapshot"]["spread"]
    vols = realized_vols()
    put = EX["put"]

    best = {(b["name"], b["rule"]): b for b in R["best"]}
    S = best[("Spread trade: short FOAT / long FGBL (DV01-neutral)", "stop 40, add every +20 (lock 0%)")]
    C = R["family_best"]["stocks"]
    OG, OO = R["family_best"]["OGBL options"], R["family_best"]["OOAT options"]
    SV = next(b for b in RV["best"] if b["rule"].startswith("stop 40, add every +20"))
    CV = RV["family_best"]["stocks"]
    CB = next(s for s in RB["stock_rank"] if s["tic"].startswith("Short CAC"))
    mix = EX["levels"]

    days = pd.bdate_range(fetched.date(), "2027-07-01")
    n_nov = int((days <= pd.Timestamp("2026-11-20")).sum())
    p_nov = max(n_nov - 15, 0) / (len(days) - 15)

    s_rows, s_final, pts = spread_ladder(FC, combo0)
    cst = A["stocks"]["^FCHI"]
    c_rows, c_final = cac_ladder(cst, round(CAC_SPOT / 10) * 10)
    p0 = round(CAC_SPOT / 10) * 10

    set_style()
    # chart 1: spread history
    w = pd.read_csv(DATA / "yields_weekly.csv", index_col=0, parse_dates=True)
    fig, ax = plt.subplots(figsize=(12, 4.6))
    ax.plot(w.index, w["spread_bp"], color="#1e6fbf", lw=1.6, label="OAT–Bund 10Y spread (weekly)")
    for L, c in zip(LEVELS, ("#c8a84b", "#e74c3c", "#b03a2e", "#7b241c")):
        ax.axhline(L, color=c, lw=1, ls="--")
        ax.text(w.index[0], L + 5, f"{L} bp", color=c, fontsize=9, va="bottom")
    ax.scatter([w.index[-1]], [spread_now], color="#0d1b2a", zorder=5)
    ax.annotate(f"today {spread_now:.0f} bp", (w.index[-1], spread_now), xytext=(-90, 18),
                textcoords="offset points", fontsize=9, color="#0d1b2a")
    ax.set_ylabel("bp")
    ax.set_ylim(0, 430)
    ax.legend(loc="upper left", frameon=False)
    ax_clean(ax)
    ch_hist = chart("history", fig)

    # chart 2: payout by level, four families
    fams = [("Spread trade (stop 40, +20)", S["levels"], "#0d1b2a"),
            ("Short CAC 40 future", C["levels"], "#1e6fbf"),
            ("OGBL 124 call (20 Nov)", OG["levels"], "#c8a84b"),
            (f"{OO['name']} (rolled)", OO["levels"], "#8a9ab0")]
    fig, ax = plt.subplots(figsize=(12, 4.6))
    wd = 0.2
    xs = np.arange(len(LEVELS))
    for i, (lab, lv, col) in enumerate(fams):
        vals = [lv[str(L)] for L in LEVELS]
        bars = ax.bar(xs + (i - 1.5) * wd, vals, wd, label=lab, color=col, zorder=3)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.3, f"{v:.1f}×", ha="center", fontsize=8)
    ax.axhline(1, color="#8a9ab0", lw=1, ls=":")
    ax.set_xticks(xs, [f"{L} bp" for L in LEVELS])
    ax.set_ylabel("mean payout (× budget)")
    ax.legend(frameon=False, ncol=4, loc="upper left")
    ax_clean(ax)
    ch_levels = chart("levels", fig)

    # chart 3: straight-line equity paths
    fig, ax = plt.subplots(figsize=(12, 4.4))
    grid = np.arange(138, 401, 2)
    ef = FC["eur_per_bp"]["FOAT"]

    def eq_spread(level):
        e, n, last = float(BUDGET), 3, 0
        for kk in range(1, 100):
            if 20 * kk > level - 138:
                break
            e += 20 * n * ef
            n = min(round(e / 40 / ef), 20)
            last = 20 * kk
        return e + (level - 138 - last) * n * ef

    def eq_cac(level):
        ds = level - 138
        fall = -(np.exp(cst["beta_s"] * ds + cst["beta_b"] * (-0.4 * ds)) - 1) * 100
        unit = p0 / 100
        e, n, last = float(BUDGET), 11, 0.0
        for kk in range(1, 20):
            if 6 * kk > fall:
                break
            e += 6 * unit * n
            n = min(round(e / 12 / unit), 25)
            last = 6 * kk
        return e + (fall - last) * unit * n

    ax.plot(grid, [eq_spread(g) / BUDGET for g in grid], color="#0d1b2a", lw=2, label="Spread trade")
    ax.plot(grid, [eq_cac(g) / BUDGET for g in grid], color="#1e6fbf", lw=2, label="Short CAC 40 future")
    for L in LEVELS:
        ax.axvline(L, color="#c8a84b", lw=0.8, ls="--")
    ax.set_xlabel("OAT–Bund spread reached (bp), no pull-back on the way")
    ax.set_ylabel("equity (× budget)")
    ax.legend(frameon=False, loc="upper left")
    ax_clean(ax)
    ch_paths = chart("paths", fig)

    # chart 4: volatility, implied vs realized
    vrows = [("OOAT implied (20 Nov ATM)", put["atm_bp"], "#e74c3c"),
             ("OAT 10Y realized, 2 years", vols["oat10"][0], "#1e6fbf"),
             ("OAT 10Y realized, 6 months", vols["oat10"][1], "#1e6fbf"),
             ("Bund 10Y realized, 6 months", vols["bund10"][1], "#8a9ab0"),
             ("OAT–Bund spread realized, 2 years", vols["spread"][0], "#0d1b2a"),
             ("OAT–Bund spread realized, 6 months", vols["spread"][1], "#0d1b2a")]
    fig, ax = plt.subplots(figsize=(12, 3.6))
    ax.barh([r[0] for r in vrows][::-1], [r[1] for r in vrows][::-1], color=[r[2] for r in vrows][::-1], zorder=3)
    for i, r in enumerate(vrows[::-1]):
        ax.text(r[1] + 2, i, f"{r[1]:.0f} bp", va="center", fontsize=9)
    ax.set_xlabel("annualised yield volatility (bp a year)")
    ax_clean(ax, "x")
    ch_vols = chart("vols", fig)

    # ── sections ──
    kpis = [(f"{spread_now:.0f} bp", "OAT–Bund 10Y today", ""), (x(S["levels"]["300"], 1), "Spread trade, mean at 300 bp", ""),
            (x(S["median"], 1), "Spread trade, median at 300 bp", ""), (pct(S["p_lost"]), "Right, but stopped out", "negative"),
            (x(C["levels"]["300"], 1), "CAC 40 short, mean at 300 bp", ""), (eur(BUDGET), "Budget at risk", "negative")]
    kpi_html = "".join(f'<div class="kpi"><div class="kpi-value {c}">{v}</div><div class="kpi-label">{lab}</div></div>'
                       for v, lab, c in kpis)

    fam_rows = [
        ["<strong>Spread trade</strong>: short FOAT / long FGBL (IBKR)", "stop 40 bp, add every +20 bp",
         x(S["levels"]["240"]), x(S["levels"]["300"]), x(S["levels"]["340"]), x(S["levels"]["400"]), x(S["median"]),
         pct(S["p_lost"]), x(S["wrong_mean"])],
        ["<strong>Short CAC 40 future</strong> (IBKR)", "stop 12%, add every 6%",
         x(C["levels"]["240"]), x(C["levels"]["300"]), x(C["levels"]["340"]), x(C["levels"]["400"]), x(C["median"]),
         pct(C["p_lost"]), x(C["wrong_mean"])],
        ["75% spread trade + 25% CAC 40 short", "both rules above",
         x(mix["240"]["0.75"]["mean"]), x(mix["300"]["0.75"]["mean"]), x(mix["340"]["0.75"]["mean"]),
         x(mix["400"]["0.75"]["mean"]), x(mix["300"]["0.75"]["median"]), pct(mix["300"]["0.75"]["p_lost"]),
         x(mix["None"]["0.75"]["mean"])],
        ["OGBL 124 call (Swissquote)", "20 Nov expiry only",
         x(OG["levels"]["240"]), x(OG["levels"]["300"]), x(OG["levels"]["340"]), x(OG["levels"]["400"]), x(OG["median"]),
         pct(OG["p_lost"]), x(OG["wrong_mean"])],
        [f"{OO['name']} (Swissquote)", "rolled ladder to Jul 2027",
         x(OO["levels"]["240"]), x(OO["levels"]["300"]), x(OO["levels"]["340"]), x(OO["levels"]["400"]), x(OO["median"]),
         pct(OO["p_lost"]), x(OO["wrong_mean"])],
    ]
    fam_tbl = table(["Book (€10k)", "Rule", "Mean 240", "Mean 300", "Mean 340", "Mean 400", "Median 300",
                     "Lost if right", "Mean if wrong"], fam_rows, num_cols=range(2, 9),
                    caption="Payout multiple = equity at exit ÷ €10k, 10,000 simulated paths per level. ‘Lost if "
                            "right’ = share of 300 bp paths ending at ≤ 0.1× (stopped out before the event). ‘If "
                            "wrong’ = no event by 1 Jul 2027.", row_classes=["total", "", "", "", ""])

    s1 = f"""
<p class="lead">The view: the OAT–Bund 10-year spread, {spread_now:.0f} bp today, widens to at least 240 bp by
1 July 2027. The base case is 300 bp, a 2018-style stress or worse. The book is built to be super-convex: lose the
€10k if the view is wrong, and compound hard if it is right. Two trades on IBKR / LYNX do this best.</p>
{boxes([(x(S['levels']['300'], 1), 'Spread trade, mean at 300 bp', 'g'), (x(S['median'], 1), 'Spread trade, median', 'g'),
        (x(C['levels']['300'], 1), 'CAC 40 short, mean at 300 bp', 'g'), (pct(S['p_lost']), 'Spread trade: right but stopped', 'r'),
        (x(S['wrong_mean'], 2), 'Spread trade if wrong', 'r')])}
<div class="edge-box">
  <div class="edge-item"><h4>Trade 1 · FOAT / FGBL spread (core)</h4><p>Sell 3 Euro-OAT Dec 2026 futures and buy 3
  Euro-Bund Dec 2026 futures. This is long the yield spread: it earns about €263 for every basis point the spread
  widens, whatever Bunds do. Stop at −€10k (about 38 bp of narrowing). Each +20 bp of widening, the size is reset
  to equity ÷ 40 bp and the stop trails. Mean {x(S['levels']['300'], 1)} at 300 bp, {x(S['levels']['400'], 1)} at 400 bp.</p></div>
  <div class="edge-item"><h4>Trade 2 · Short CAC 40 future (satellite)</h4><p>Sell 1 CAC 40 future plus 1 mini
  future (about €86k notional). French equities fall when the spread widens, about 17% per 100 bp in the last two
  years, partly because of global risk-off. Stop at −€10k (11.7% above entry). Add each 6% fall. Mean
  {x(C['levels']['300'], 1)} at 300 bp; lower payout, but its stop-outs happen on different paths.</p></div>
</div>
<h3 class="sub">Results at a glance</h3>
{fam_tbl}
<h3 class="sub">How to combine them</h3>
<p>Run the spread trade alone for the highest payout ({x(S['levels']['300'])} mean, {x(S['median'])} median at
300 bp, {pct(S['p_lost'])} of right-world paths stopped out). Or put 75% of the budget in the spread trade and 25% in
the CAC short: the mean falls to {x(mix['300']['0.75']['mean'])}, but the share of right-world paths that end with
nothing almost halves to {pct(mix['300']['0.75']['p_lost'])}. The two payouts correlate only
{mix['300']['corr']:.2f}, because noise stops them out on different days.</p>
<div class="risk-box"><h4>What can go wrong</h4><ul>
<li>No stress by 1 July 2027: both trades bleed carry and noise. The spread trade returns on average
{x(S['wrong_mean'])} of the budget, but {pct(mix['None']['1']['p_lost'])} of no-event paths end with nothing.</li>
<li>Right but too early or too noisy: a 40 bp pull-back before the event wipes the position out, and there is no
re-entry. This is the price of the convexity.</li>
<li>Gaps: IBKR cannot hold a stop on the OAT–Bund spread, so the spread trade is checked once a day after the close
and closed by hand. A weekend or overnight headline can move it well past the stop before you act.</li>
<li>Workload: one five-minute check a day, an order on the days an add or stop is due (a burst of a few during the
event), and seven roll days over nine months. Weekly checks are possible but cost about a fifth of the payout.</li>
<li>Margin: at the 20-contract cap the futures need far more margin than €10k. Profits fund it, but check IBKR’s
requirement before each add.</li>
<li>The CAC short is partly a global risk-off bet and overlaps with the existing French bank trade (BNP Paribas,
Crédit Agricole and Société Générale are CAC members).</li></ul></div>
<p class="note">No orders have been placed. Prices are indicative ({asof}); check live quotes before entering.</p>
"""

    calib = table(["Input", "Value", "How measured"], [
        ["FOAT € per bp of OAT yield", f"€{FC['eur_per_bp']['FOAT']:.1f}",
         f"duration {FC['duration']['FOAT']:.2f}; regression of 20 daily Eurex settlements on CNBC yields "
         f"(corr {FC['corr_price_yield']['FOAT']:.3f})"],
        ["FGBL € per bp of Bund yield", f"€{FC['eur_per_bp']['FGBL']:.1f}",
         f"duration {FC['duration']['FGBL']:.2f} (corr {FC['corr_price_yield']['FGBL']:.3f})"],
        ["Hedge ratio", f"{FC['hedge_ratio']:.3f} FGBL per FOAT", "equal € per bp on both legs"],
        ["FOAT carry", f"{FC['carry_bp_per_day']['FOAT']:.3f} bp/day",
         "mean Dec−Mar settlement calendar over 20 days (0.63 points a quarter)"],
        ["FGBL carry", f"{FC['carry_bp_per_day']['FGBL']:.3f} bp/day", "same (0.09 points a quarter)"],
        ["Net carry against the spread trade",
         f"{(FC['carry_bp_per_day']['FOAT'] - FC['carry_bp_per_day']['FGBL']) * 63:.1f} bp a quarter",
         "a short future converges up toward cash bonds; the curve is downward-sloping"],
    ])
    sign = table(["Item", "Meaning", "Consequence"], [
        ["FOAT / FGBL quote", "Price per 100 nominal of a notional 6% bond, not a yield", "Price falls when the yield rises"],
        ["Spread", f"OAT 10Y yield − Bund 10Y yield ({spread_now:.1f} bp)", "Target 240–400 bp"],
        ["Spread widens", "OAT prices fall relative to Bund prices", "FGBL − FOAT (in price) goes up"],
        ["Short FOAT / long FGBL", "Long the yield spread", "Makes money when the spread widens"],
        ["Long FOAT / short FGBL", "Short the yield spread", "Makes money only if the spread narrows"],
    ])
    snap_tbl = table(["Market", "Level", "Source"], [
        ["OAT 10Y / Bund 10Y", f"{snap.oat10:.3f}% / {snap.bund10:.3f}%", f"CNBC, {asof}"],
        ["OAT–Bund 10Y spread", f"{spread_now:.1f} bp", "CNBC"],
        ["FOAT Dec 2026", f"≈ {foat:.2f}", f"put–call parity on the live 20 Nov OOAT chain (8 Oct settle "
                                            f"{fut['FOAT']['20261208']['settle']:.2f})"],
        ["FGBL Dec 2026", f"≈ {fgbl:.2f}", f"parity on the 20 Nov OGBL chain (8 Oct settle {fut['FGBL']['20261208']['settle']:.2f})"],
        ["FGBL − FOAT (price spread)", f"{combo0:.2f}", "the number the spread-trade tickets refer to"],
        ["OOAT 20 Nov ATM implied vol", f"{put['atm_iv'] * 100:.1f}% ≈ {put['atm_bp']:.0f} bp/yr", "Eurex chain"],
        ["CAC 40 index", f"{CAC_SPOT:,.1f}", CAC_TIME],
    ])
    assum = table(["Item", "Assumption"], [
        ["Horizon", f"{fetched:%d %b %Y} → 1 Jul 2027, {len(days)} business days"],
        ["Right world", "The spread reaches 240 / 300 / 340 / 400 bp. The completion day is uniform over the horizon; "
                        "the last 15 days are an event that bridges the spread exactly to the level"],
        ["Before the event", f"Driftless random walks with fat tails (Student-t, 4 df): spread {A['sig_s_daily']:.2f} "
                             f"bp/day, Bund {A['sig_b_daily']:.2f} bp/day, correlation {A['rho']:.2f} (last 6 months)"],
        ["During the event", "Spread noise doubled. Bunds move −f × the remaining jump, f uniform 0.10–0.70 "
                             "(2018-like flight to Bunds at the low end, break-up at the high end)"],
        ["Wrong world", "Same random walks without an event; everything closed on 1 Jul 2027"],
        ["Exit", "Everything closed on the day the stress level is reached"],
        ["Futures costs", "€2.35 per contract plus half a tick per side; 1 bp stop slippage, half the gap if a close "
                          "gaps through; quarterly rolls; cap 20 FOAT contracts"],
        ["Stocks", "Daily regression of log returns on spread and Bund changes (Oct 2024–Oct 2026), residual "
                   "t-noise; CAC future carry 1% a year, single stocks 3.5%; 0.10% per side, 0.5% stop slippage"],
        ["Options", "Live 20 Nov OOAT / OGBL chains at bid/ask; later rolls priced at today's skew with ATM vol "
                    "rising with the spread; marked at model value on exit"],
        ["Paths", "10,000 per level, same random seed for every candidate"],
    ])
    sens = table(["Test", "Spread trade (mean / lost if right)", "CAC 40 short (mean / lost if right)"], [
        ["Base case at 300 bp", f"{x(S['levels']['300'])} / {pct(S['p_lost'])}", f"{x(C['levels']['300'])} / {pct(C['p_lost'])}"],
        ["Realized vol × 1.5", f"{x(SV['levels']['300'])} / {pct(SV['p_lost'])}", f"{x(CV['levels']['300'])} / {pct(CV['p_lost'])}"],
        ["Stock sensitivity × 0.6", "unchanged", f"{x(CB['mean'])} / {pct(CB['p_lost'], 0)} (stop 8%, add 4%)"],
        ["Bund flight f 0.10–0.30 / 0.30–0.50 / 0.50–0.70",
         " / ".join(x(v) for v in S["by_f"]), " / ".join(x(v) for v in C["by_f"])],
        ["Event in first / middle / last third", " / ".join(x(v) for v in S["by_timing"]),
         " / ".join(x(v) for v in C["by_timing"])],
    ], caption="Ranking holds in every test. Late events cost the most: more carry and more time for noise to hit the stop.")
    vol_rows = [[r[0], f"{r[1]:.0f} bp"] for r in vrows]

    s2 = f"""
<p>Everything below was refreshed at {asof}: Eurex option chains, futures statistics, CNBC yields, two years of
daily yields, ten years of weekly yields, Yahoo closes for 18 French non-bank stocks and the CAC 40.</p>
<h3 class="sub">Market snapshot</h3>
{snap_tbl}
<h3 class="sub">The spread: ten years of history and the stress levels</h3>
<div class="chart-box">{ch_hist}</div>
<p class="note">Weekly CNBC FR10Y − DE10Y. The 2018 Italian stress took BTP–Bund from 129 to 307 bp in six months;
France 2011 went from 35 to 154 bp.</p>
<h3 class="sub">How the futures are priced, and which way the trade points</h3>
{sign}
<p>Live check: from 11 September to 8 October 2026 the spread widened 44.8 bp, and short 3 FOAT / long 3 FGBL
made +€11,490 on Eurex settlements (about €256 per bp). The direction is confirmed on real prices.</p>
<h3 class="sub">Calibration</h3>
{calib}
<h3 class="sub">Scenario model and assumptions</h3>
<div class="step-flow">
 <div class="step"><div class="step-num">1</div><div class="step-name">Draw the event day</div><div class="step-desc">uniform to 1 Jul 2027</div></div>
 <div class="step"><div class="step-num">2</div><div class="step-name">Noise until then</div><div class="step-desc">spread and Bund random walks, fat tails</div></div>
 <div class="step"><div class="step-num">3</div><div class="step-name">15-day event</div><div class="step-desc">spread to the level; Bunds rally by f</div></div>
 <div class="step"><div class="step-num">4</div><div class="step-name">Run the rules</div><div class="step-desc">stops, adds, rolls, costs per path</div></div>
 <div class="step"><div class="step-num">5</div><div class="step-name">Score</div><div class="step-desc">equity ÷ €10k at exit</div></div>
</div>
{assum}
<h3 class="sub">Payout by stress level: best candidate per family</h3>
<div class="chart-box">{ch_levels}</div>
<p>About 190 candidates were tested: the spread trade, outright short FOAT, outright long FGBL, 17 French non-bank
stocks and the CAC 40 future, each with 6 stop widths and pyramid variants, plus OOAT puts, put spreads,
backspreads and OGBL calls, front-only or rolled. The spread trade wins every level; the next best family is the CAC
40 short at about a third of the payout.</p>
<h3 class="sub">Sensitivities</h3>
{sens}
<h3 class="sub">Volatility: what the noise costs and what options charge</h3>
{table(["Measure", "Annualised"], vol_rows, num_cols=(1,))}
<p class="note">Realized vols from daily CNBC yield changes. The spread trade only has to survive spread noise
(about {vols['spread'][1]:.0f} bp a year recently); OAT options charge about {put['atm_bp']:.0f} bp a year.</p>
"""

    rules = sorted([b for b in R["best"] if b["family"] == "futures"], key=lambda b: -b["mean"])[:6]
    rule_tbl = table(["Rule", "Mean 300", "Median 300", "Lost if right", "240 / 300 / 340 / 400 bp", "Initial size"],
                     [[b["rule"].replace(" (lock 0%)", ""), x(b["mean"]), x(b["median"]), pct(b["p_lost"]),
                       " / ".join(x(b["levels"][str(L)], 1) for L in LEVELS), b["order"][-1]] for b in rules],
                     num_cols=(1, 2, 3), row_classes=["total" if b["rule"] == S["rule"] else "" for b in rules],
                     caption="Stop 30 / +15 has a marginally higher mean, but it is stopped out in 41% of right-world "
                             f"paths and falls to 7.68× at 1.5× vol, where stop 40 / +20 is best ({x(SV['levels']['300'])}).")
    ef = FC["eur_per_bp"]["FOAT"]
    card = []
    for i, r in enumerate(s_rows):
        nxt = s_rows[i + 1] if i + 1 < len(s_rows) else None
        stop_eq = max(0.0, r[3] - 40 * r[4] * ef) if i else 0.0
        card.append([r[0], f"≈ {138 + r[1]:.0f} bp", eur(r[3]), f"short {r[4]} FOAT / long {r[5]} FGBL",
                     eur(stop_eq) if stop_eq else "€0 (the whole trade)",
                     f"{eur(r[3] + 20 * r[4] * ef)} → go to the next row" if nxt else
                     "no more adds; take profit at 300 bp"])
    lad = table(["Row", "Spread, roughly", "Trade equity at this row", "Position to hold",
                 "Stop: close everything if equity closes at or below", "Next add: when equity closes at or above"],
                card, num_cols=(2, 4),
                caption="Trade equity = €10,000 plus all realised and unrealised profit and loss of the two legs, "
                        "including rolls and commissions. The rows assume a clean move; in practice you simply move "
                        "to the next row when the equity crosses the ‘next add’ number, whatever the date. From "
                        "Add 5 the size is capped at 20 FOAT contracts, so the stop no longer sits at €0: it sits "
                        "about €70k below the equity of the last add.")
    MT = json.loads((DATA / f"maintenance_{args.stamp}.json").read_text())["results"]

    def mt_rows(key):
        lab = {"daily_resting": "Resting stop in the market, adds checked daily (the model)",
               "daily_close": "One check a day after the close, act at the close",
               "weekly_adds": "Resting stop, adds checked on Fridays only",
               "weekly_all": "Everything checked on Fridays only",
               "stop_only": "Stop only, no ladder"}
        out = []
        for vk, nm in lab.items():
            a, w_ = MT[key][vk]["300"], MT[key][vk]["None"]
            out.append([nm, x(a["mean"]), x(a["median"]), pct(a["p_lost"]),
                        f"{a['adds_mean']:.1f}" if vk != "stop_only" else "0", x(w_["mean"])])
        return out

    mt_spread = table(["How you run it", "Mean 300", "Median 300", "Lost if right", "Adds, average", "Mean if wrong"],
                      mt_rows("spread"), num_cols=(1, 2, 3, 4, 5), row_classes=["", "total", "", "", ""],
                      caption="Same 10,000 paths for every row. ‘Adds, average’ counts the resizing trades over the "
                              "life of the trade on 300 bp paths; paths that survive to the event make about "
                              f"{MT['spread']['daily_resting']['300']['adds_alive_mean']:.1f}. In the wrong world "
                              f"there are only {MT['spread']['daily_resting']['None']['adds_mean']:.1f} on average.")
    mt_cac = table(["How you run it", "Mean 300", "Median 300", "Lost if right", "Adds, average", "Mean if wrong"],
                   mt_rows("^FCHI"), num_cols=(1, 2, 3, 4, 5), row_classes=["total", "", "", "", ""],
                   caption="For the CAC the resting stop is real, so the first row is how you run it. Checking the "
                           "adds only on Fridays costs little here, because CAC adds are 6% apart.")
    sfin = table(["Exit at", "Equity, straight line", "Model mean", "Model median"],
                 [[f"{L} bp", f"{eur(s_final[L])} ({s_final[L] / BUDGET:.1f}×)", x(S['levels'][str(L)]),
                   x(S['median']) if L == 300 else "–"] for L in LEVELS], num_cols=(1, 2, 3),
                 caption="The model mean is lower than the straight line: it includes stop-outs on noisy paths, "
                         "carry, rolls, costs and late events.")

    t1 = ticket("Ticket 1A · Entry (IBKR / LYNX, Eurex)", [
        ("Instrument", "Euro-OAT future Dec 2026 (FOAT Z6) and Euro-Bund future Dec 2026 (FGBL Z6), Eurex, "
                       "€100,000 nominal, tick 0.01 = €10, last trading day 8 Dec 2026"),
        ("Order", "<strong>SELL 3 FOAT Dec 2026 · BUY 3 FGBL Dec 2026</strong>, as two separate limit orders"),
        ("How", "Enter the FOAT sell first, at the bid. As soon as it fills, enter the FGBL buy at the ask. "
                "Both are among the most liquid contracts in Europe, so the gap between the two fills is "
                "seconds. Do not use market orders"),
        ("Reference prices", f"FOAT ≈ {foat:.2f}, FGBL ≈ {fgbl:.2f} (parity at {asof}); 8 Oct settlements "
                             f"{fut['FOAT']['20261208']['settle']:.2f} / {fut['FGBL']['20261208']['settle']:.2f}"),
        ("Exposure", f"€{3 * FC['eur_per_bp']['FOAT']:.0f} per bp of spread widening; residual €"
                     f"{3 * (FC['eur_per_bp']['FGBL'] - FC['eur_per_bp']['FOAT']):.0f} per bp long Bunds "
                     f"(3/3 versus the neutral 3/{3 * FC['hedge_ratio']:.1f})"),
        ("Time in force", "DAY; Eurex hours 08:00–22:00 CET, best liquidity 09:00–17:30"),
    ])
    t3 = ticket("Ticket 1C · Roll (repeat three times: early Dec 2026, early Mar 2027, early Jun 2027)", [
        ("Tool", "TWS Portfolio window → right-click the FOAT position → <strong>Roll</strong>. The Futures Roll "
                 "Builder opens"),
        ("Choose", "the next quarterly contract (Dec → Mar 2027, Mar → Jun 2027, Jun → Sep 2027) and click OK"),
        ("Order", "TWS fills in a two-leg calendar order for the full size: for the short FOAT it buys back the old "
                  "month and sells the new month. Set a <strong>limit at the mid of the calendar</strong> (FOAT Dec−Mar "
                  f"traded about {cal_o:.2f} points on 8 Oct), time in force DAY, and submit"),
        ("Then", "Do the same for the FGBL position (sells the old month, buys the new month; FGBL Dec−Mar was "
                 f"about {cal_b:.2f})"),
        ("Afterwards", "Write the realised profit or loss of the closed old-month contracts in your log, so the trade "
                       "equity stays complete. Re-create any price alerts on the new month. The rule card does not "
                       "change"),
    ])
    t4 = ticket("Ticket 1D · Exit", [
        ("Take profit", "<strong>Close both legs when the OAT–Bund 10Y spread reaches 300 bp</strong> (base case; "
                        "240, 340 or 400 bp pay as shown below). Buy back the FOAT and sell the FGBL with limit orders"),
        ("Stop", "Close both legs on the first day the trade equity closes at or below the stop number on the rule "
                 "card. No re-entry after a stop"),
        ("Deadline", "Close whatever is open by 1 Jul 2027"),
    ])
    roll_cal = table(["Date (target)", "Trade", "What to do"], [
        ["Any day, 5 minutes after 17:30 CET", "Both", "The daily check (below)"],
        ["Tue 1 – Thu 3 Dec 2026", "Spread trade", "Roll FOAT and FGBL Dec → Mar 2027 (last trading day 8 Dec)"],
        ["Mon 14 Dec 2026", "CAC short", "Roll FCE and MFC Dec → Feb 2027 (expiry 18 Dec); move the stop"],
        ["Tue 16 Feb 2027", "CAC short", "Roll Feb → Apr 2027 (expiry 19 Feb); move the stop"],
        ["Mon 1 – Wed 3 Mar 2027", "Spread trade", "Roll Mar → Jun 2027 (last trading day 8 Mar)"],
        ["Tue 13 Apr 2027", "CAC short", "Roll Apr → Jun 2027 (expiry 16 Apr); move the stop"],
        ["Tue 1 – Thu 3 Jun 2027", "Spread trade", "Roll Jun → Sep 2027 (last trading day 8 Jun)"],
        ["Tue 15 Jun 2027", "CAC short", "Roll Jun → Jul 2027 (expiry 18 Jun); move the stop"],
        ["Thu 1 Jul 2027", "Both", "Close anything still open"],
    ], caption="Seven roll days in nine months. The dates are a few days before each expiry, when liquidity has "
               "moved to the next contract.")
    s3 = f"""
<p class="lead">Short FOAT / long FGBL pays the spread itself. Bunds rallying or selling off barely matter, because
the two legs carry the same € per bp. The only noise the stop has to survive is spread noise: about
{vols['spread'][1]:.0f} bp a year, against roughly 160 bp of move to the base case.</p>
<div class="grid-2">
<div class="edge-item"><h4>Why it is the best candidate</h4><p>It pays the exact variable of the view, it is cheap to
hold (about {(FC['carry_bp_per_day']['FOAT'] - FC['carry_bp_per_day']['FGBL']) * 63:.1f} bp a quarter of carry, no
option premium), and futures can be resized as gains come in. That compounding with a trailing stop turns a
linear spread bet into a convex one.</p></div>
<div class="edge-item"><h4>What it gives up</h4><p>A stop instead of a premium: a 40 bp pull-back before the event wipes
out the position, which happens on {pct(S['p_lost'])} of the right-world paths. After the cap, a 40 bp pull-back
costs about €70k of profit.</p></div>
</div>
<h3 class="sub">Stop and pyramid rule: top variants at 300 bp</h3>
{rule_tbl}

<h3 class="sub">How the trade is run: the short version</h3>
<p>You place two orders on day one and nothing else. There is no ladder of resting orders to enter in advance, and
nothing to cancel and re-enter when you roll. Instead, you keep a one-page rule card and look at one number, the
trade equity, once a day after the close. On most days the answer is "do nothing". You act only when the equity
crosses one of two numbers on the card: the stop number (close everything) or the next-add number (make the
position bigger). Three times in nine months you roll the futures to the next contract, which takes two orders
each time.</p>
<p>This is not a simplification of the model. It is how the model works: it looks at daily closes, and it sizes
every step from the equity at that moment. The simulation below shows that a once-a-day check at the close gives
{x(MT['spread']['daily_close']['300']['mean'])} at 300 bp, against {x(MT['spread']['daily_resting']['300']['mean'])}
with a stop resting in the market. The difference is noise.</p>

<h3 class="sub">Why there are no resting stop or ladder orders</h3>
<p>There are three reasons. First, IBKR cannot hold a stop on the spread. A stop has to be attached to one tradable
price, and the price we care about is the difference between two contracts. Eurex runs single order books for some
bond spreads (Bund–Buxl, BTP–Bund, Schatz–BTS) but not for OAT–Bund, and IBKR's own "Smart" combos that would
simulate one only work on US exchanges. Separate stops on each leg would be worse than none: a general bond rally
could trigger the FOAT stop alone and leave you with an outright Bund position.</p>
<p>Second, the size of each add depends on the equity at the moment of the add, so it cannot be fixed in advance.
Third, every order is tied to a specific contract month. A ladder of orders on the December contracts would have to
be cancelled and rebuilt at each roll. Rules written in euros of equity avoid all three problems: they do not depend
on which month you hold, and they never need re-entering.</p>

<h3 class="sub">Day one</h3>
{t1}
<p>After the two fills, write three numbers into your log: the equity (€10,000), the stop number (€0) and the
next-add number ({eur(BUDGET + 20 * 3 * ef)}). That is the first row of the rule card. If you want a reminder for
days when you do not look, set two IBKR Mobile price alerts (Alerts → +, condition Price): one if FOAT Dec rises
2.0 points above your fill, and one if it falls 1.7 points below. They are only reminders to look; they do not
trade, because FOAT alone is not the spread.</p>

<h3 class="sub">The rule card (this replaces the ladder of orders)</h3>
<p>Each row is a state of the trade. You start in the first row. When the trade equity closes at or above the
"next add" number, you resize to the position in the next row, and from then on that row's stop and next-add
numbers apply. When the equity closes at or below the row's stop number, you close everything and the trade is
over. The rows are spaced 20 bp of spread apart and every stop sits 40 bp below the last add, but you never need to
look up the spread itself: the equity tells you.</p>
{lad}
<p>The stop number stays at or near €0 from the entry up to Add 4 because the trade is "all-in": after each add
the position is large enough that a 40 bp pull-back would take the equity back to roughly zero (the small amounts
left in some rows come from rounding to whole contracts). That is what makes the payout convex,
and it is also why a quarter of the right-world paths end with nothing. From Add 5 the position is capped at 20 FOAT, and a
pull-back costs about €70k of profit instead of everything.</p>

<h3 class="sub">The daily check, step by step</h3>
<ol class="steps">
<li>After 17:30 CET, when Eurex has published the day's settlement prices, open the TWS Portfolio window. It shows
the unrealised profit and loss of the FOAT and FGBL positions.</li>
<li>Compute the trade equity: €10,000, plus the realised profit and loss already in your log (from rolls, closed
contracts and commissions), plus today's unrealised profit and loss of both legs.</li>
<li>If the equity is at or below the stop number on your current row, close both legs the same evening (Eurex
trades until 22:00 CET): buy back the FOAT, then sell the FGBL, both with limit orders. The trade is over.</li>
<li>If the equity is at or above the next-add number, move to the next row. Sell the extra FOAT contracts and buy
the extra FGBL contracts shown in that row, then write the new row's numbers in your log. Check the margin first
with the TWS what-if preview (in the order ticket, click "Check margin"); at the larger sizes the requirement is a
multiple of the original €10k.</li>
<li>If neither, do nothing. Check whether the OAT–Bund spread has reached 300 bp; if it has, take profit.</li>
</ol>

<h3 class="sub">How often you will actually act</h3>
<p>On the simulated 300 bp paths the trade is resized {MT['spread']['daily_resting']['300']['adds_mean']:.1f} times
on average over its whole life, and about {MT['spread']['daily_resting']['300']['adds_alive_mean']:.0f} times on the
paths that survive to the event. Most of those adds come in a burst. The model's event moves the spread roughly
160 bp in three weeks, which means an add every two or three days. Outside the event the spread drifts about
{vols['spread'][1]:.0f} bp a year, so a 20 bp step is a matter of months. In the wrong world there are
{MT['spread']['daily_resting']['None']['adds_mean']:.1f} adds on average. Including the entry, the rolls and the
exit, a typical right-world trade needs about 15–20 orders in nine months, and a wrong-world trade about 10.</p>
<p>If a daily check is too much, the simulation prices the alternatives. A Friday-only check costs about a fifth of
the payout, because in a fast event the adds come too late. Dropping the ladder altogether keeps the stop but
loses most of the convexity:</p>
{mt_spread}
<p>A practical middle way: check weekly while nothing happens, and switch to daily as soon as the spread is moving,
for example once the equity is more than 25% above the last add or the spread has moved 10 bp in a week. The fast
part of the trade is exactly when it pays to look.</p>

<h3 class="sub">Rolling the futures</h3>
<p>Euro-OAT and Euro-Bund futures are physically delivered. If you are short FOAT at expiry, you must deliver
French government bonds, and IBKR does not let retail accounts go into delivery: it closes such positions itself
shortly before expiry. So every quarter the position has to move to the next contract. This is called rolling. The
model assumes a roll in the first three business days of December, March and June. By then most of the market has
moved to the next contract, and the old one stops trading on the 8th.</p>
<p>A roll is one calendar-spread order per leg. A calendar spread buys one month and sells the other in a single
trade, so you are never without a position in between. Eurex has its own order book for these calendar spreads,
which keeps the price fair. In TWS the easiest tool is the Futures Roll Builder. An alternative is SpreadTrader
(right-click a contract → Tools → SpreadTrader, then click the price where the Dec row meets the Mar column).</p>
{t3}
<p>The roll does not change the position size or the rule card. The new contract trades at a slightly different
price (FOAT March is about 0.6–0.8 points below December, FGBL about 0.1), but that difference is a price level,
not a gain or a loss. Your equity carries straight across. The only bookkeeping is to note the realised result of
the old contracts, because IBKR shows the new contracts with a fresh unrealised profit and loss.</p>
{t4}
<h3 class="sub">The calendar for both trades</h3>
{roll_cal}

<h3 class="sub">What it pays</h3>
<div class="chart-box">{ch_paths}</div>
{sfin}
"""

    st_rows = []
    for tic, nm in STOCK_NAMES.items():
        s = A["stocks"][tic]
        rk = next(r for r in R["stock_rank"] if r["tic"].endswith(nm.replace(" future (FCE)", "")) or
                  (tic == "^FCHI" and r["tic"].startswith("Short CAC")))
        sens_ = s["beta_s"] * 100 * 100
        noise = s["idio"] * np.sqrt(252) * 100
        st_rows.append([nm, f"{sens_:.1f}%", f"{noise:.1f}%", f"{abs(sens_) / noise:.2f}",
                        "1.0%" if tic == "^FCHI" else "3.5%", x(rk["mean"]), pct(rk["p_lost"])])
    st_tbl = table(["Short", "Return per +100 bp", "Own noise a year", "Signal ÷ noise", "Carry cost", "Mean 300",
                    "Lost if right"], st_rows, num_cols=range(1, 7), row_classes=["total"] + [""] * (len(st_rows) - 1))
    ep_tbl = table(["Episode", "Spread (bp)", "CAC 40", "DAX", "Euro Stoxx 50", "S&amp;P 500", "Note"], EPISODES,
                   num_cols=(2, 3, 4, 5))
    clad = table(["Step", "CAC level", "Equity", "Position after", "New stop (buy stop)", "At risk"],
                 [[r[0], f"{r[1]:,.0f}", eur(r[2]), f"{mini_split(r[3])} ({r[3] * r[1]:,.0f} € notional)".replace(
                     f"({r[3] * r[1]:,.0f} €", f"(€{r[3] * r[1]:,.0f}"), f"{r[4]:,.0f}", eur(r[5])] for r in c_rows],
                 num_cols=(1, 2, 4, 5),
                 caption=f"Entry at {p0:,} for illustration; recompute from the actual fill. Size in minis (MFC = €1 "
                         "per point; FCE = 10 minis). The cap of €2,000 per 1% of entry (25 minis) is reached at the "
                         "third add; after that only the stop trails.")
    cfin = table(["Spread at exit", "CAC level (model, f = 0.4)", "CAC fall", "Equity, straight line", "Model mean"],
                 [[f"{L} bp", f"{c_final[L][0]:,.0f}", f"−{c_final[L][1]:.1f}%",
                   f"{eur(c_final[L][2])} ({c_final[L][2] / BUDGET:.1f}×)", x(C['levels'][str(L)])] for L in LEVELS],
                 num_cols=(1, 2, 3, 4),
                 caption="CAC level from the regression betas (−17.2% per 100 bp of spread, a 40% Bund rally share). "
                         "The model mean includes stop-outs, carry and timing.")
    c1 = ticket("Ticket 2A · Entry (IBKR / LYNX, Euronext Paris)", [
        ("Instrument", "CAC 40 index future Dec 2026 (FCE Z6, €10 per point, tick 0.5 = €5) and CAC 40 mini "
                       "future Dec 2026 (MFC Z6, €1 per point); last trading day 18 Dec 2026, cash-settled"),
        ("Order", "<strong>SELL 1 FCE Dec 2026 · SELL 1 MFC Dec 2026</strong>"),
        ("Price", f"Limit at the bid of each contract; index at {CAC_SPOT:,.1f} ({CAC_TIME}). The future trades "
                  "close to the index (dividends and rates are priced in)"),
        ("Exposure", f"≈ €{11 * CAC_SPOT:,.0f} notional, €{11 * CAC_SPOT / 100:,.0f} per 1% move of the CAC"),
        ("Time in force", "DAY; Euronext 08:00–22:00 CET"),
    ])
    c2 = ticket("Ticket 2B · Protective stop (attach it to the entry orders)", [
        ("How", "In the TWS order ticket of each entry order, click <strong>Attach → Stop Loss</strong> before you "
                "submit. TWS then places the stop automatically the moment the entry fills"),
        ("Order", "<strong>BUY 1 FCE and BUY 1 MFC, STOP at fill + 909 points</strong> (≈ "
                  f"{p0 + 909:,} for a {p0:,} fill), time in force GTC"),
        ("Why this level", "909 points × €11 per point = €10,000, an 11.7% rally. That is the whole budget"),
        ("Trigger", "Leave the TWS default trigger method. When the stop triggers it becomes a market order, so "
                    "in a gap it can fill worse than the stop level"),
    ])
    c3 = ticket("Ticket 2C · Roll (four times: 14 Dec 2026, 16 Feb, 13 Apr, 15 Jun 2027)", [
        ("Tool", "TWS Portfolio window → right-click the FCE position → <strong>Roll</strong> → choose the furthest "
                 "listed month (Feb 2027 in December, then Apr, Jun and Jul 2027). Set a limit at the mid of the "
                 "calendar and submit. Repeat for the MFC position, into the same month"),
        ("Why the same month", "MFC is only listed one to three months ahead. Keeping both contracts in the same "
                               "month means one stop level and one roll date for the whole position"),
        ("Then move the stop", "<strong>The old stop does not follow the roll.</strong> It stays on the expiring "
                               "contract, and if it triggered it would open a new long position. Cancel it, and "
                               "enter a new buy stop on the new month for the full size, at the old stop level plus "
                               "the price difference between the new and the old month (usually a few points)"),
    ])
    c4 = ticket("Ticket 2D · Exit", [
        ("Take profit", "<strong>Same trigger as Trade 1: buy back everything when the OAT–Bund spread reaches "
                        "300 bp</strong>, not on a CAC level. Cancel the resting stop afterwards"),
        ("Deadline", "Close by 1 Jul 2027"),
    ])
    combo_tbl = table(["Sleeve", "Budget", "Entry", "Stop"], [
        ["Spread trade (75%)", "€7,500", "SELL 2 FOAT Dec / BUY 2 FGBL Dec (€175 per bp)",
         "Daily check: close both legs if the sleeve equity closes at or below €0"],
        ["CAC 40 short (25%)", "€2,500", "SELL 3 MFC Dec (≈ €23k notional)", "fill + 833 points (3 × €833 ≈ €2,500)"],
    ], caption="Same rules, scaled. Adds and stops follow the ladders at 75% and 25% size.")

    s4 = f"""
<p class="lead">A short CAC 40 future is the best equity way to hold the view. It ranks first among 18 shorts on
mean payout and is stopped out far less often than single stocks, because it is less noisy and cheaper to hold.</p>
<h3 class="sub">Why French stocks fall when the spread widens</h3>
<div class="grid-2">
<div class="edge-item"><h4>Channels</h4><p><strong>Discount rate:</strong> the OAT is France's risk-free rate, so
long-duration and concession businesses (Vinci, Eiffage, ADP, property) suffer. <strong>Balance sheets:</strong>
insurers and asset managers hold OATs. <strong>Fiscal risk:</strong> a deficit crisis brings surtaxes and contract
cuts. <strong>Credit:</strong> banks and corporate spreads reprice with the sovereign. <strong>Risk-off:</strong> spreads
widen when global appetite falls.</p></div>
<div class="edge-item"><h4>How much is French?</h4><p>On the same days the S&amp;P 500 also falls about 8.7% per 100
bp of French spread, against about 17–19% for the CAC. In 2011 the CAC fell no more than the Euro Stoxx; in Italy
2018 the local index fell only about 6% per 100 bp more than Europe. In a France-only stress the CAC probably falls
less than modelled. With all stock sensitivities scaled to 60%, the CAC short drops to {x(CB['mean'])}.</p></div>
</div>
<h3 class="sub">Stock ranking at 300 bp (best rule per stock)</h3>
{st_tbl}
<p class="note">Regression of daily log returns on spread and Bund changes, Oct 2024–Oct 2026. Signal ÷ noise =
sensitivity ÷ residual vol over the last 6 months. The CAC wins on signal ÷ noise and on carry.</p>
<h3 class="sub">Episodes</h3>
{ep_tbl}
<h3 class="sub">How the trade is run</h3>
<p>The CAC short is easier to run than the spread trade, because it is a single contract. IBKR can hold a real stop
order on it, so the stop protects you even on days when you do not look. Only the adds and the rolls need you.</p>
{c1}{c2}

<h3 class="sub">The ladder: when to sell more</h3>
<p>Every time the CAC falls another 6% from the entry level, you sell more futures, sized from the equity at that
moment, and you move the stop down to 12% above the new level. As with the spread trade, the adds are not entered
in advance. Each one is decided at the daily check, after Euronext closes at 17:30 CET. Look at the CAC 40 index
close. If it has crossed the next level in the table, sell the extra contracts that evening. Then change the
resting stop: modify its quantity to the new total and its price to the new stop level (in TWS, double-click the
stop in the Orders window, change both fields and click Transmit). That is one sell order and one stop
modification per add, and there are only three adds before the cap.</p>
{clad}
<p>If you prefer to be away, you can pre-place the next add as a sell stop order at the next level, for example
SELL {c_rows[1][3] - c_rows[0][3]} MFC STOP {c_rows[1][1]:,.0f}. It costs little, because the size of the next add is known from the table.
Only pre-place the next one, never the whole ladder, and remember that after it fills the protective stop still has
to be moved by hand.</p>
{mt_cac}

<h3 class="sub">Rolling the futures</h3>
<p>CAC futures are cash-settled, so nothing is delivered, but an expiring contract closes your position at the
settlement price on the third Friday. To keep the trade on you roll a few days earlier into a later month. Because
the mini future (MFC) is listed only one to three months ahead, the simplest scheme is to roll both contracts
together into the furthest month the mini offers. That gives four roll dates: 14 Dec 2026, 16 Feb, 13 Apr and
15 Jun 2027. The Futures Roll Builder in TWS does each roll as a single calendar-spread order.</p>
{c3}
<p>The one thing to remember is the stop. A roll closes the old contract, but the stop order you placed on it stays
alive. Cancel it immediately after the roll and place the new stop on the new month. The rule card is in index
points, so nothing else changes: the add levels stay where they are.</p>
{c4}
<h3 class="sub">What it pays</h3>
{cfin}
<h3 class="sub">Combined book: 75% spread trade, 25% CAC 40 short</h3>
{combo_tbl}
<p>At 300 bp the combined book pays {x(mix['300']['0.75']['mean'])} mean and {x(mix['300']['0.75']['median'])} median,
and ends with nothing on {pct(mix['300']['0.75']['p_lost'])} of right-world paths, against
{pct(mix['300']['1']['p_lost'])} for the spread trade alone.</p>
"""

    put_ask = put["ask"]
    pay = {f: put[f"intrinsic_f{f}"] / put_ask for f in ("0", "0.3", "0.6")}
    opt_tbl = table(["Option book (€10k)", "Mean 240", "Mean 300", "Mean 400", "Median 300", "Lost if right"], [
        [f"{OO['name']}, rolled to Jul 2027", x(OO["levels"]["240"]), x(OO["levels"]["300"]), x(OO["levels"]["400"]),
         x(OO["median"]), pct(OO["p_lost"])],
        ["OGBL 124 call, 20 Nov only", x(OG["levels"]["240"]), x(OG["levels"]["300"]), x(OG["levels"]["400"]),
         x(OG["median"]), pct(OG["p_lost"])],
        ["Spread trade (reference)", x(S["levels"]["240"]), x(S["levels"]["300"]), x(S["levels"]["400"]),
         x(S["median"]), pct(S["p_lost"])],
    ], num_cols=(1, 2, 3, 4, 5), row_classes=["", "", "total"])
    why = table(["Reason", "Numbers"], [
        ["Volatility is priced high", f"OOAT ATM implied {put['atm_iv'] * 100:.1f}% price vol ≈ {put['atm_bp']:.0f} bp "
                                      f"a year of OAT yield, against {vols['oat10'][0]:.0f}–{vols['oat10'][1]:.0f} bp "
                                      "realized. The market already charges for a stress"],
        ["The skew makes our strike dearer", f"The {put['k']:g} put trades at {put['iv'] * 100:.1f}% implied. At a flat "
                                             f"85 bp realized vol it would be worth {put['realized_85']['price']:.2f}; "
                                             f"the market asks {put_ask:.2f}"],
        ["Time is short", f"The 20 Nov expiry covers {n_nov} of {len(days)} business days. In the model the event "
                          f"finishes before it on only {pct(p_nov)} of paths. The front-only OGBL call loses "
                          f"everything on {pct(OG['p_lost'])}"],
        ["Rolling pays time value again", "A ladder to Jul 2027 needs four rolls (20 Nov → 22 Jan → 25 Mar → 21 May → "
                                          "23 Jul); each one buys new premium at implied vol"],
        ["OAT puts pay on the OAT yield, not the spread", f"A Bund rally offsets part of the move: the rolled put pays "
                                                         f"{' / '.join(x(v) for v in OO['by_f'])} for f low / mid / high"],
        ["Wide quotes", f"{put['k']:g} put {put['bid']:.2f} / {put_ask:.2f}: the spread is "
                        f"{(put_ask - put['bid']) / put['mid'] * 100:.0f}% of the mid"],
        ["No compounding", "A put's notional is fixed at purchase. Futures resize with gains, which is where the "
                           "spread trade's convexity comes from"],
    ])
    s5 = f"""
<p class="lead">Options would give the same bet with no stop and a known maximum loss. In theory they work: the
payoff is convex by construction, and noise cannot stop you out. In practice they pay a fraction of the futures at
today's prices.</p>
<h3 class="sub">In theory: an OAT put if the stress comes early</h3>
<p>The 20 Nov OOAT {put['k']:g} put costs {put_ask:.2f} at the ask (FOAT ≈ {put['fwd']:.2f}). If the spread reaches 300 bp
by 20 November, the put is worth its intrinsic value at expiry:</p>
{boxes([(x(pay['0'], 1), 'Bunds unchanged (f = 0)', 'g'), (x(pay['0.3'], 1), 'Bunds rally 30% of the move', 'g'),
        (x(pay['0.6'], 1), 'Bunds rally 60% of the move', '')])}
<p>That is comparable to the spread trade's {x(S['by_timing'][0], 1)} for an early event. But it only works if the event
completes in the next six weeks, and only when Bunds do not rally too much.</p>
<h3 class="sub">In practice: why options pay less</h3>
{why}
<h3 class="sub">Model results</h3>
{opt_tbl}
<p>The v4 study tested 15,747 option-only books (rolled OOAT puts, spreads and Bund call helpers). All had negative
expected value under the scenario odds; the best lost about €6.1k on €8.6k spent. In v5, where only the right world
is scored, the best option book reaches {x(OG['levels']['300'])} at 300 bp, against {x(S['levels']['300'])} for
the spread trade.</p>
<div class="edge-box">
<div class="edge-item"><h4>When options would win</h4><p>If OAT implied vol fell toward the realized
{vols['oat10'][1]:.0f} bp, if the event were expected before a specific expiry, or if a stop-out on noise is
unacceptable: the rolled OOAT ladder was never wiped out ({pct(OO['p_lost'])} lost), against
{pct(S['p_lost'])} for the spread trade.</p></div>
<div class="edge-item"><h4>A role at the margin</h4><p>25% in the rolled OOAT ladder next to 75% spread trade
cuts the right-but-lost share to about 7%, but lowers the mean by about 2.5 points. Swissquote holds the options;
IBKR holds the futures.</p></div>
</div>
<div class="chart-box">{ch_vols}</div>
"""

    s6 = f"""
<div class="disclaimer">
<p><strong>Data.</strong> Eurex OOAT / OGBL chains (product pages, {asof}); Eurex statistics API for FOAT / FGBL
settlements (last full day 8 Oct 2026; live futures levels from put–call parity on the 20 Nov chains); CNBC FR10Y /
DE10Y yields (quote and daily/weekly history); Yahoo Finance closes for 18 French stocks and ^FCHI; Euronext contract
specifications for FCE / MFC; FRED monthly 10Y yields for 2011 / 2018 episodes.</p>
<p><strong>Files.</strong> jobs/france-sovereign-stress/scripts/v5/ (history.py, model.py, linear.py, options.py,
run.py, extras.py, build_report.py); data/v5/v5_{args.stamp}.json and _vol1.5 / _beta0.6; extras_{args.stamp}.json;
data/chains/eurex_{args.stamp}.json. Canvas: france-sovereign-v5.</p>
<p><strong>Limits.</strong> Pre-event paths have no drift; the DV01 calibration uses 20 settlement days; the stop on
the spread is synthetic and can gap; the stock sensitivity is partly global; France may restrict short selling in a
crisis, as the AMF did for financials in 2011; event timing is uniform.</p>
<p><strong>Disclaimer.</strong> Working document for the France sovereign-stress proposal. Model output, not
investment advice. No orders have been placed.</p>
</div>
"""

    extra_css = """
  .ticket { background: #f6f8fb; border: 1px solid #dde3ec; border-left: 3px solid var(--gold); border-radius: 8px;
            padding: 14px 18px; margin: 4px 0 20px; }
  .ticket-title { font-size: 11px; font-weight: 700; letter-spacing: 1.4px; text-transform: uppercase; color: var(--navy); margin-bottom: 8px; }
  .ticket-kv { display: grid; grid-template-columns: 190px 1fr; gap: 6px 14px; font-size: 12.5px; }
  .ticket-kv .k { color: var(--muted); font-weight: 600; }
  .ticket-kv .v { color: #2a3a4c; }
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
"""
    sections = [
        ("summary", "01 / Executive Summary", "Two IBKR futures trades for a 240 bp+ OAT–Bund stress", s1),
        ("models", "02 / Models, Scenarios and Assumptions", "What was measured, simulated and scored", s2),
        ("spread", "03 / Trade 1 · FOAT / FGBL Spread",
         f"Short OAT futures, long Bund futures: {x(S['levels']['300'], 1)} mean at 300 bp", s3),
        ("cac", "04 / Trade 2 · Short CAC 40 Future",
         f"The best equity expression: {x(C['levels']['300'], 1)} mean at 300 bp", s4),
        ("options", "05 / Why Options Work in Theory but Pay Less", "Same view, bounded loss, a fraction of the payout", s5),
        ("notes", "06 / Data and Limits", "Sources, files and caveats", s6),
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
<title>France Sovereign Stress v5 · Super-Convex Book</title>
<style>
{CSS}
{extra_css}
</style>
</head>
<body>
<header class="report-header">
  <div class="header-eyebrow">Aureas GmbH · Trade Proposal · {fetched:%d %B %Y}</div>
  <div class="header-title">France Sovereign Stress v5: a Super-Convex Book</div>
  <div class="header-subtitle">Base case: the OAT–Bund 10Y spread reaches 240 bp or more by 1 July 2027 (optimised
  at 300 bp). €10k at risk. Trade 1: short FOAT / long FGBL with a trailing stop and pyramiding. Trade 2: short CAC 40
  future. Options compared.</div>
  <div class="kpi-strip">{kpi_html}</div>
</header>
<div class="content">
{body}
</div>
<footer>
  <strong>France Sovereign Stress v5 · Summary and Order Tickets</strong><br>
  Prices as of {asof} · Generated {generated:%d %B %Y, %H:%M} CEST · Model output; no orders placed<br>
  Aureas GmbH · Confidential · For discussion only, not investment advice
</footer>
</body>
</html>
"""
    out = ROOT / "reports" / f"france_sovereign_stress_v5_trade_detail_{fetched:%Y-%m-%d}.html"
    out.write_text(html, encoding="utf-8")
    shutil.copy(out, JOB / "output" / out.name)
    print(out, f"{len(html) / 1024:.0f} KB")
    print("spread ladder", [(r[0], round(r[3]), r[4], r[5], round(r[6], 2)) for r in s_rows])
    print("spread finals", {k: round(v) for k, v in s_final.items()})
    print("cac ladder", [(r[0], round(r[1]), round(r[2]), r[3], round(r[4])) for r in c_rows])
    print("cac finals", {k: tuple(round(v, 1) for v in t) for k, t in c_final.items()})
    print("p_nov", round(p_nov, 3), n_nov, len(days), "roll shift", round(roll_shift, 2), "combo0", combo0)


if __name__ == "__main__":
    main()
