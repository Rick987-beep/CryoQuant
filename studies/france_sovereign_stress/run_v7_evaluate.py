#!/usr/bin/env python3
"""v7 evaluation: low-ops / convex structures on the active snapshot.

Writes ``data/v7_evaluate.json`` and ``RESULTS_V7.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

import numpy as np
import pandas as pd

from src.bank_rank import rank_banks, suggest_bank_put_spread
from src.calibrate import stock_betas
from src.data.reference import load_eurex_snapshot, load_fred_monthly, load_stocks_daily, load_yields_daily
from src.evaluate import evaluate_spread_levels, payout_stats, run_sleeve_multiples, tercile_means
from src.inputs import load_market_inputs
from src.options import load_option_snapshot, single, vertical
from src.paths import data_dir, load_config
from src.rules import Rule, build_spread_sleeve
from src.scenarios import ScenarioConfig, simulate_worlds
from src.v7_sleeves import (
    bank_put_spread_multiples,
    bank_short_stock_multiples,
    fixed_spread_multiples,
    naked_foat_multiples,
    option_front_only_multiples,
    option_roll_multiples,
    pick_option_structures,
)
from src.vol_fit import fit_vol_vs_spread, flat_vol_fit


# Scorecard exit levels; 300 bp remains the primary / base case.
LEVELS = [200.0, 250.0, 300.0, 350.0, 400.0]
BASE_LEVEL = 300.0
BUDGET = 10_000.0


def _fmt_x(x: float) -> str:
    return f"{x:.2f}×"


def _fmt_pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _scorecard(multiples: dict, levels: list[float] = LEVELS) -> dict:
    out = {"by_level": {}, "wrong": None}
    for lv in levels:
        m = multiples[lv]
        st = payout_stats(m)
        d = st.to_dict()
        d["p10"] = float(np.percentile(m, 10))
        d["p90"] = float(np.percentile(m, 90))
        out["by_level"][str(int(lv))] = d
    w = multiples[None]
    wst = payout_stats(w)
    wd = wst.to_dict()
    wd["p10"] = float(np.percentile(w, 10))
    wd["p90"] = float(np.percentile(w, 90))
    out["wrong"] = wd
    # Convexity
    m200 = multiples[200.0].mean()
    m400 = multiples[400.0].mean()
    out["convexity_400_over_200"] = float(m400 / m200) if m200 > 0.05 else None
    mean_right = float(np.mean([multiples[lv].mean() for lv in levels]))
    wrong_loss = max(1.0 - wd["mean"], 0.01)
    out["right_over_wrong_loss"] = float(mean_right / wrong_loss)
    out["means_by_level"] = {
        str(int(lv)): float(multiples[lv].mean()) for lv in levels
    }
    return out


def _odds_ev(score: dict, odds: dict) -> float:
    """Subjective EV from config scenario odds.

    relief+grind → wrong world; stress (200–300) → mean(200,250,300);
    contested (>300) → mean(350,400).
    """
    wrong = score["wrong"]["mean"]
    by = score["by_level"]
    stress = float(np.mean([by["200"]["mean"], by["250"]["mean"], by["300"]["mean"]]))
    contested = float(np.mean([by["350"]["mean"], by["400"]["mean"]]))
    relief = float(odds.get("relief", 0.15))
    grind = float(odds.get("grind", 0.50))
    st = float(odds.get("stress", 0.30))
    ct = float(odds.get("contested", 0.05))
    return float((relief + grind) * wrong + st * stress + ct * contested)


def _timing(multiples_300: np.ndarray, tc: np.ndarray) -> list[float]:
    return tercile_means(multiples_300, tc.astype(float))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n-paths", type=int, default=None, help="override simulation.n_paths")
    ap.add_argument("--quick", action="store_true", help="n=2000 for a fast probe")
    args = ap.parse_args()

    cfg = load_config()
    mi = load_market_inputs(cfg)
    scfg = ScenarioConfig.from_study_config(cfg)
    if args.quick or args.n_paths:
        n = 2000 if args.quick else int(args.n_paths)
        scfg = ScenarioConfig(
            n_paths=n,
            seed=scfg.seed,
            event_bdays=scfg.event_bdays,
            event_vol_mult=scfg.event_vol_mult,
            bund_flight_share=scfg.bund_flight_share,
            dof=scfg.dof,
            end=scfg.end,
        )

    raw = load_eurex_snapshot(mi.stamp)
    opt = load_option_snapshot(raw, path=f"eurex_{mi.stamp}.json")
    print(f"stamp {mi.stamp} s0={mi.s0:.2f} bp  OOAT expiries={sum(1 for p,_ in opt.expiries if p=='OOAT')}  "
          f"bank={sorted({p for p,_ in opt.bank_expiries})}")

    # Vol fit
    fred = None
    try:
        fred = load_fred_monthly()
    except Exception:  # noqa: BLE001
        pass
    vol_fit = fit_vol_vs_spread(mi.yields, fred, vol=mi.vol)
    vol_flat = flat_vol_fit(vol_fit)
    print(f"vol_fit use_level={vol_fit.use_level} r2={vol_fit.r2:.3f} max_mult={vol_fit.max_obs_mult:.2f}")

    worlds = simulate_worlds(mi.vol, s0=mi.s0, start=mi.start, levels=LEVELS, cfg=scfg)
    duration = {
        "OOAT": float(mi.fc.duration.get("FOAT", 7.1)),
        "OGBL": float(mi.fc.duration.get("FGBL", 7.4)),
    }
    print("duration", duration)

    results: dict = {
        "stamp": mi.stamp,
        "s0": mi.s0,
        "quote_time": mi.quote_time,
        "budget": BUDGET,
        "n_paths": scfg.n_paths,
        "seed": scfg.seed,
        "levels_bp": [int(x) for x in LEVELS],
        "base_level_bp": int(BASE_LEVEL),
        "vol_fit": vol_fit.to_dict(),
        "fee_note": opt.fee_note,
        "structures": {},
        "bank_rank": [],
        "suggestions": [],
    }
    odds = (cfg.get("view") or {}).get("scenario_odds") or {}

    # ---- Bookends: v6 ladder + stop_only ----
    print("bookends…")
    ladder_rule = Rule(d=40.0, step=20.0, keep=0.0)
    stop_only_rule = Rule(d=40.0, step=None)
    for name, rule in (("v6_ladder_40_20", ladder_rule), ("v6_stop_only", stop_only_rule)):
        block = evaluate_spread_levels(worlds, mi.fc, rule, BUDGET, LEVELS)
        # Attach p10/p90
        for lv in LEVELS:
            m = run_sleeve_multiples(
                build_spread_sleeve(worlds[lv], mi.fc), worlds[lv], rule, BUDGET
            )
            block["by_level"][str(int(lv))]["p10"] = float(np.percentile(m, 10))
            block["by_level"][str(int(lv))]["p90"] = float(np.percentile(m, 90))
        m300 = run_sleeve_multiples(
            build_spread_sleeve(worlds[300.0], mi.fc), worlds[300.0], rule, BUDGET
        )
        block["timing_terciles_300"] = _timing(m300, worlds[300.0].tc)
        block["odds_ev"] = _odds_ev(block, odds)
        block["kind"] = "bookend"
        block["means_by_level"] = {
            str(int(lv)): float(block["by_level"][str(int(lv))]["mean"]) for lv in LEVELS
        }
        block["name"] = name
        results["structures"][name] = block
        print(f"  {name} @300 mean={block['by_level']['300']['mean']:.2f}×  EV={block['odds_ev']:.2f}×")

    # ---- Fixed 3/3 stop grid ----
    print("fixed spread…")
    for stop in (30.0, 40.0, 50.0, 60.0):
        res = fixed_spread_multiples(worlds, mi.fc, stop_bp=stop, foat_n=3, fgbl_n=3, budget=BUDGET, levels=LEVELS)
        sc = _scorecard(res.multiples)
        sc["timing_terciles_300"] = _timing(res.multiples[300.0], worlds[300.0].tc)
        sc["odds_ev"] = _odds_ev(sc, odds)
        sc["kind"] = res.kind
        sc["detail"] = res.detail
        sc["name"] = res.name
        results["structures"][f"fixed_3_3_stop_{int(stop)}"] = sc
        print(f"  {res.name} @300={sc['by_level']['300']['mean']:.2f}× EV={sc['odds_ev']:.2f}×")

    # ---- Naked FOAT ----
    print("naked FOAT…")
    for stop, tp in ((30.0, 120.0), (40.0, 160.0), (50.0, 200.0)):
        res = naked_foat_multiples(
            worlds, mi.fc, stop_bp=stop, take_profit_bp=tp, budget=BUDGET, levels=LEVELS
        )
        sc = _scorecard(res.multiples)
        sc["timing_terciles_300"] = _timing(res.multiples[300.0], worlds[300.0].tc)
        sc["odds_ev"] = _odds_ev(sc, odds)
        sc["kind"] = res.kind
        sc["detail"] = res.detail
        sc["name"] = res.name
        key = f"naked_foat_stop{int(stop)}_tp{int(tp)}"
        results["structures"][key] = sc
        print(f"  {res.name} @300={sc['by_level']['300']['mean']:.2f}× EV={sc['odds_ev']:.2f}×")

    # ---- Options ----
    print("options…")
    cands = pick_option_structures(opt)
    print(f"  {len(cands)} live two-sided structures")
    opt_scores = []
    for struct in cands:
        try:
            res = option_roll_multiples(
                worlds, opt, struct, vol_fit, budget=BUDGET, duration=duration, levels=LEVELS
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {struct.name}: {exc}")
            continue
        sc = _scorecard(res.multiples)
        sc["timing_terciles_300"] = _timing(res.multiples[300.0], worlds[300.0].tc)
        sc["odds_ev"] = _odds_ev(sc, odds)
        sc["kind"] = res.kind
        sc["detail"] = res.detail
        sc["name"] = res.name
        key = f"opt_{struct.name.replace(' ', '_').replace('/', '_')}"
        results["structures"][key] = sc
        opt_scores.append((sc["by_level"]["300"]["mean"], sc["odds_ev"], key, sc))

    # Flat-IV sensitivity on the best naked OOAT put and best OGBL call
    opt_scores.sort(key=lambda x: x[0], reverse=True)
    print(f"  top options by @300: {[(k, round(m,2)) for m,_,k,_ in opt_scores[:5]]}")

    # Also evaluate top-3 with flat IV
    for _, _, key, sc0 in opt_scores[:3]:
        struct_name = sc0["name"]
        # Rebuild structure from detail legs is hard; re-pick by name match
        struct = next((s for s in cands if s.name == struct_name), None)
        if struct is None:
            continue
        try:
            res = option_roll_multiples(
                worlds, opt, struct, vol_flat, budget=BUDGET, duration=duration, levels=LEVELS
            )
            sc = _scorecard(res.multiples)
            sc["odds_ev"] = _odds_ev(sc, odds)
            sc["kind"] = "option_roll_flat_iv"
            sc["detail"] = res.detail
            sc["name"] = res.name + " [flat IV]"
            results["structures"][key + "_flat_iv"] = sc
        except Exception as exc:  # noqa: BLE001
            print(f"  flat-iv skip {struct_name}: {exc}")

    # Front-only for best structure
    if opt_scores:
        best_struct = next(s for s in cands if s.name == opt_scores[0][3]["name"])
        try:
            res = option_front_only_multiples(
                worlds, opt, best_struct, vol_fit, budget=BUDGET, duration=duration, levels=LEVELS
            )
            sc = _scorecard(res.multiples)
            sc["odds_ev"] = _odds_ev(sc, odds)
            sc["kind"] = res.kind
            sc["detail"] = res.detail
            sc["name"] = res.name
            results["structures"]["opt_best_front_only"] = sc
        except Exception as exc:  # noqa: BLE001
            print(f"  front-only failed: {exc}")

    # 50/50 OOAT put + OGBL call pair (best naked of each by @300)
    ooat_key = next(
        (
            k
            for m, ev, k, sc in opt_scores
            if sc["detail"].get("structure", "").startswith("OOAT")
            and "/" not in sc["detail"].get("structure", "")
        ),
        None,
    )
    ogbl_key = next(
        (
            k
            for m, ev, k, sc in opt_scores
            if sc["detail"].get("structure", "").startswith("OGBL")
            and "/" not in sc["detail"].get("structure", "")
        ),
        None,
    )
    if ooat_key and ogbl_key:
        a = results["structures"][ooat_key]
        b = results["structures"][ogbl_key]
        sa = next(s for s in cands if s.name == a["name"])
        sb = next(s for s in cands if s.name == b["name"])
        ra = option_roll_multiples(worlds, opt, sa, vol_fit, budget=BUDGET, duration=duration, levels=LEVELS)
        rb = option_roll_multiples(worlds, opt, sb, vol_fit, budget=BUDGET, duration=duration, levels=LEVELS)
        pair = {lv: 0.5 * (ra.multiples[lv] + rb.multiples[lv]) for lv in [None, *LEVELS]}
        sc = _scorecard(pair)
        sc["timing_terciles_300"] = _timing(pair[300.0], worlds[300.0].tc)
        sc["odds_ev"] = _odds_ev(sc, odds)
        sc["kind"] = "option_pair"
        sc["detail"] = {"ooat": a["name"], "ogbl": b["name"], "weights": [0.5, 0.5]}
        sc["name"] = f"50/50 {a['name']} + {b['name']}"
        results["structures"]["opt_ooat_ogbl_pair"] = sc
        print(f"  pair @300={sc['by_level']['300']['mean']:.2f}× EV={sc['odds_ev']:.2f}×")

    # ---- Banks ----
    print("banks…")
    # Prefer long history if present
    stocks = mi.stocks
    long_path = Path(STUDY_DIR) / "input" / "snapshots" / mi.stamp / "data" / "banks_daily_long.csv"
    if long_path.exists():
        long_df = pd.read_csv(long_path, parse_dates=["Date"]).set_index("Date")
        long_df.index = pd.DatetimeIndex(long_df.index).tz_localize(None).normalize()
        # Merge betas on overlapping yields; ranking uses long for drawdowns
        rank_stocks = long_df
    else:
        rank_stocks = stocks

    ranking = rank_banks(rank_stocks, mi.yields, snap=opt)
    results["bank_rank"] = [r.to_dict() for r in ranking]
    for r in ranking:
        print(f"  {r.code}: score={r.score:.2f} beta_s={r.beta_s:.5f} mean_dd={r.mean_dd:.1%} "
              f"two_sided={r.option_two_sided} notes={r.notes}")

    if ranking:
        best = ranking[0]
        yahoo = best.yahoo
        beta_src = rank_stocks if yahoo in rank_stocks.columns else stocks
        betas = stock_betas(beta_src, mi.yields, tickers=[yahoo])
        if yahoo not in betas:
            # Fall back to any bank with a usable beta.
            for alt in ranking[1:]:
                betas = stock_betas(rank_stocks, mi.yields, tickers=[alt.yahoo])
                if alt.yahoo in betas:
                    best, yahoo = alt, alt.yahoo
                    break
        if yahoo not in betas:
            print("  no bank beta available; skipping bank sleeves")
            results["bank_put_suggestion"] = None
        else:
            beta = betas[yahoo]
            spot = float(rank_stocks[yahoo].dropna().iloc[-1])

            # Short stock
            res = bank_short_stock_multiples(worlds, beta, budget=BUDGET, levels=LEVELS)
            sc = _scorecard(res.multiples)
            sc["odds_ev"] = _odds_ev(sc, odds)
            sc["kind"] = res.kind
            sc["detail"] = {**res.detail, "bank": best.code, "yahoo": yahoo, "spot": spot}
            sc["name"] = f"short {best.code} stop 12%"
            results["structures"][f"bank_short_{best.code}"] = sc
            print(f"  short {best.code} @300={sc['by_level']['300']['mean']:.2f}×")

            # Put spread if chain allows
            sug = suggest_bank_put_spread(opt, best.code, spot)
            if sug is None and len(ranking) > 1:
                for alt in ranking[1:]:
                    spot_alt = float(rank_stocks[alt.yahoo].dropna().iloc[-1])
                    sug = suggest_bank_put_spread(opt, alt.code, spot_alt)
                    if sug is not None:
                        best = alt
                        yahoo = alt.yahoo
                        spot = spot_alt
                        beta = stock_betas(rank_stocks, mi.yields, tickers=[yahoo])[yahoo]
                        break
            if sug is not None:
                from datetime import date as date_cls

                exp_d = date_cls.fromisoformat(sug["expiry_date"])
                res = bank_put_spread_multiples(
                    worlds,
                    beta,
                    spot=spot,
                    long_k=sug["k_long"],
                    short_k=sug["k_short"],
                    expiry=exp_d,
                    live_debit=sug["live_debit"],
                    half_spread=sug["half_spread"],
                    atm_iv=sug["atm_iv"],
                    budget=BUDGET,
                    levels=LEVELS,
                    vol_fit=vol_fit,
                )
                sc = _scorecard(res.multiples)
                sc["odds_ev"] = _odds_ev(sc, odds)
                sc["kind"] = res.kind
                sc["detail"] = {**res.detail, "bank": best.code, "suggestion": sug}
                sc["name"] = f"{best.code} {sug['k_long']:g}/{sug['k_short']:g} put spread"
                results["structures"][f"bank_put_spread_{best.code}"] = sc
                results["bank_put_suggestion"] = sug
                print(
                    f"  put spread {best.code} @300={sc['by_level']['300']['mean']:.2f}× "
                    f"debit={sug['live_debit']:.2f}"
                )
            else:
                results["bank_put_suggestion"] = None
                print("  no two-sided bank put spread available")

    # ---- Grid for headline structures ----
    print("exit grid for headlines…")
    headlines = []
    # Pick best option, best fixed, best naked, best bank
    def best_of(kind_prefix: str, metric="mean_300"):
        best_k, best_v = None, -1e9
        for k, v in results["structures"].items():
            if kind_prefix and not (
                v.get("kind", "").startswith(kind_prefix)
                or k.startswith(kind_prefix)
            ):
                continue
            if "by_level" not in v:
                continue
            m = v["by_level"]["300"]["mean"]
            if m > best_v:
                best_v, best_k = m, k
        return best_k

    # Headline keys
    hl_keys = [
        "v6_ladder_40_20",
        "v6_stop_only",
        best_of("fixed"),
        best_of("naked"),
    ]
    # best option_roll (not flat)
    opt_best = None
    opt_best_m = -1e9
    for k, v in results["structures"].items():
        if v.get("kind") == "option_roll" and v["by_level"]["300"]["mean"] > opt_best_m:
            opt_best_m = v["by_level"]["300"]["mean"]
            opt_best = k
    if opt_best:
        hl_keys.append(opt_best)
    for k, v in results["structures"].items():
        if v.get("kind") in ("bank_stock", "bank_put_spread"):
            hl_keys.append(k)
    results["headline_keys"] = [k for k in hl_keys if k]

    # Suggestions: top 3 concrete trades
    suggestions = []
    if opt_best:
        d = results["structures"][opt_best]
        suggestions.append(
            {
                "rank": 1,
                "name": d.get("name"),
                "key": opt_best,
                "mean_300": d["by_level"]["300"]["mean"],
                "odds_ev": d["odds_ev"],
                "detail": d.get("detail"),
                "weakness": (
                    "Roll decay if stress arrives late; OTM OGBL calls are cheap but "
                    "wrong-world premium burn is large; payout depends on Bund flight."
                ),
            }
        )
    fixed_k = best_of("fixed")
    if fixed_k:
        d = results["structures"][fixed_k]
        suggestions.append(
            {
                "rank": 2,
                "name": d.get("name"),
                "key": fixed_k,
                "mean_300": d["by_level"]["300"]["mean"],
                "odds_ev": d["odds_ev"],
                "detail": d.get("detail"),
                "weakness": "Linear in spread; no convexity. Stopout risk in wrong world ~like stop_only.",
            }
        )
    bank_k = next(
        (k for k in results["structures"] if results["structures"][k].get("kind") == "bank_put_spread"),
        next((k for k in results["structures"] if results["structures"][k].get("kind") == "bank_stock"), None),
    )
    if bank_k:
        d = results["structures"][bank_k]
        suggestions.append(
            {
                "rank": 3,
                "name": d.get("name"),
                "key": bank_k,
                "mean_300": d["by_level"]["300"]["mean"],
                "odds_ev": d["odds_ev"],
                "detail": d.get("detail"),
                "weakness": "Bank beta to the OAT–Bund spread is noisy; idiosyncratic bank news can dominate.",
            }
        )
    results["suggestions"] = suggestions

    # Write JSON
    out_json = data_dir() / "v7_evaluate.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)

    def _default(o):
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(type(o))

    out_json.write_text(json.dumps(results, indent=2, default=_default))
    print(f"wrote {out_json}")

    # Write RESULTS_V7.md
    md = _render_md(results, odds)
    out_md = STUDY_DIR / "RESULTS_V7.md"
    out_md.write_text(md)
    print(f"wrote {out_md}")
    return 0


def _option_line(v: dict) -> str:
    d = v.get("detail") or {}
    name = d.get("structure") or v.get("name", "")
    product = "Euro-Bund future (Germany)" if name.startswith("OGBL") else "Euro-OAT future (France)"
    kind = "call" if " call" in name else "put"
    strikes = name.split()[1]
    fwd, ppb = d.get("fwd"), d.get("points_per_bp")
    dist = ""
    if fwd and ppb:
        k1 = float(strikes.split("/")[0])
        pts = k1 - fwd
        dist = (
            f" The first strike is {abs(pts):.1f} points {'above' if pts > 0 else 'below'} the "
            f"future ({fwd:.2f}), i.e. about {abs(pts) / ppb:.0f} bp of "
            f"{'German' if name.startswith('OGBL') else 'French'} 10y yield "
            f"{'fall' if pts > 0 else 'rise'}."
        )
    if "/" in strikes:
        k1, k2 = strikes.split("/")
        what = (
            f"Buy the {k1} {kind} and sell the {k2} {kind} on the {product}, both expiring "
            f"{d.get('front')}; cheaper than the single option, but the payout stops growing beyond {k2}."
        )
    else:
        what = f"Buy {kind} options on the {product} at strike {strikes}, expiring {d.get('front')}."
    return (
        f"{what}{dist} About every 8 weeks the position is rolled into the next expiry at the same "
        f"distance from the market, until mid-2027; the €10k premium budget is split across those rolls "
        f"in proportion to their length. Sold when the stress event completes."
    )


def _describe(key: str, v: dict) -> str:
    kind = v.get("kind", "")
    d = v.get("detail") or {}
    if key == "v6_ladder_40_20":
        return (
            "The v6 primary book, kept as a reference: short Euro-OAT futures / long Euro-Bund futures "
            "(the OAT–Bund spread trade), €10k at risk, stop 40 bp below the last add, and the position is "
            "increased every time the spread widens another 20 bp. Many orders; not a v7 candidate."
        )
    if key == "v6_stop_only":
        return (
            "Same spread trade sized so a 40 bp move against it loses €10k, opened once with a stop and "
            "never added to."
        )
    if kind == "fixed_spread":
        return (
            f"Short {d['foat_n']} Euro-OAT futures and long {d['fgbl_n']} Euro-Bund futures (the spread trade), "
            f"opened once and never added to. Closed if the spread narrows {d['stop_bp']:g} bp below entry "
            f"(checked at the daily close), otherwise held until the event completes. Futures rolled quarterly. "
            f"Multiples are measured against the money lost if stopped: €{d['stop_risk_eur']:,.0f}."
        )
    if kind == "naked_foat":
        return (
            f"Short {d['n']} Euro-OAT futures with no Bund hedge, so it bets on the French 10y yield itself "
            f"rising. Closed at a loss if that yield falls {d['stop_bp']:g} bp from entry, or at a profit if it "
            f"rises {d['take_profit_bp']:g} bp (both checked at the daily close). Stop risk ≈ €{d['stop_risk_eur']:,.0f}."
        )
    if kind == "option_roll":
        return _option_line(v)
    if kind == "option_roll_flat_iv":
        return (
            "Same option trade as the line without “[flat IV]”, but rolls and exits are priced with today's "
            "implied volatility unchanged, instead of letting volatility rise with the spread as fitted on "
            "history. This is the conservative version."
        )
    if kind == "option_front":
        return (
            f"Same option, but the whole €10k is spent on the {d.get('front')} expiry and never rolled. "
            "Expires worthless if the stress comes after that date."
        )
    if kind == "option_pair":
        return (
            f"Half the budget in the “{d.get('ooat')}” trade (France) and half in the “{d.get('ogbl')}” "
            "trade (Germany), both with the same 8-week rolls."
        )
    if kind == "bank_put_spread":
        s = d.get("suggestion") or {}
        return (
            f"Buy Société Générale {d['long_k']:g} puts and sell {d['short_k']:g} puts (Eurex), expiring "
            f"{s.get('expiry', d.get('expiry'))}, opened once and held. Share price {d['spot']:.2f}; pays from "
            f"{d['long_k']:g} down to {d['short_k']:g}, maximum {d['long_k'] - d['short_k']:g} per share against a "
            f"{d['live_debit']:.2f} cost. Loss is limited to the premium."
        )
    if kind == "bank_stock":
        return (
            f"Short Société Générale shares (€{d['notional']:,.0f}) sized so a {d['stop_pct']:g}% rise stops "
            "the trade out for about €10k. Pays borrow cost and the 0.4% French transaction tax when buying back."
        )
    return v.get("name", key)


def _render_md(results: dict, odds: dict) -> str:
    lines = [
        "# RESULTS — france_sovereign_stress (v7 low-ops / convex)",
        "",
        f"Snapshot `{results['stamp']}` · entry spread **{results['s0']:.2f} bp** "
        f"(quote {results.get('quote_time')}) · budget €{results['budget']:,.0f} · "
        f"n={results['n_paths']} · seed={results.get('seed')} · common random numbers.",
        "",
        f"Exit levels simulated: **{' / '.join(str(x) for x in results.get('levels_bp', [200, 250, 300, 350, 400]))} bp** "
        f"(base case **{results.get('base_level_bp', 300)} bp**).",
        "",
        "## Design",
        "",
        "Same v6 world model (driftless walk → 15-business-day jump to the target level, "
        "random timing, Bund flight). Structures are low-touch: **no pyramid**. "
        "Option entry at live Eurex ask/bid; rolls/exits at model mid ± observed half-spread. "
        f"{results.get('fee_note', '')}",
        "",
        "### Vol grounding",
        "",
    ]
    vf = results["vol_fit"]
    lines += [
        f"- Fit realised 21d spread σ on level + Δlevel: R²={vf['r2']:.3f}, "
        f"use_level={vf['use_level']}, max_obs_mult={vf['max_obs_mult']:.2f}, "
        f"base σ={vf['base_sig_bp']:.2f} bp/day, n={vf['n_obs']}.",
        f"- Episodes: {json.dumps(vf.get('by_episode') or {}, default=str)}",
        "- Flat-IV sensitivity (multiplier = 1) reported on the top option structures.",
        "",
        "## Subjective scenario odds (secondary ranking only)",
        "",
        f"`{odds}` — relief+grind → wrong world; stress → mean(200,250,300); "
        "contested → mean(350,400).",
        "",
        "## How to read the tables",
        "",
        "- **Multiple (×)**: money at the end divided by the money put at risk (€10k unless stated). "
        "1.0× = break-even, 0× = all lost.",
        "- **Mean / Median**: average and middle outcome over 10,000 simulated paths in which the spread "
        "reaches the given level by mid-2027.",
        "- **Lost**: share of those paths that end at 0.1× or less.",
        "- **Wrong mean**: average outcome if no stress event happens (spread drifts sideways until 1 Jul 2027).",
        "- **Odds EV**: average weighted by your subjective scenario odds (secondary ranking only).",
        "- Each structure is explained in one line under “What each structure is” below the tables.",
        "",
        "## Comparison @ 300 bp (primary / base case)",
        "",
        "| Structure | Kind | Mean | Median | Lost | Wrong mean | Odds EV |",
        "|-----------|------|-----:|-------:|-----:|-----------:|--------:|",
    ]
    rows = []
    for k, v in results["structures"].items():
        if "by_level" not in v:
            continue
        if v.get("kind") in ("option_roll_flat_iv",):
            continue  # keep table readable; flat IV in sensitivities
        if v.get("kind") == "option_roll" and k not in (results.get("headline_keys") or []) and not k.startswith("opt_best"):
            # Only show top few options in the main table
            continue
        rows.append(
            (
                v["by_level"]["300"]["mean"],
                v.get("name") or k,
                v.get("kind", ""),
                v["by_level"]["300"],
                v["wrong"],
                v.get("odds_ev"),
            )
        )
    # Always include all non-option structures + top 5 options
    rows = []
    opt_rows = []
    keep_kinds = {
        "bookend",
        "fixed_spread",
        "naked_foat",
        "bank_stock",
        "bank_put_spread",
        "option_pair",
        "option_front",
        "option_roll_flat_iv",
    }
    for k, v in results["structures"].items():
        if "by_level" not in v:
            continue
        row = (
            v["by_level"]["300"]["mean"],
            v.get("name") or k,
            v.get("kind", ""),
            v["by_level"]["300"],
            v["wrong"],
            v.get("odds_ev"),
            k,
        )
        if v.get("kind") == "option_roll":
            opt_rows.append(row)
        elif v.get("kind") in keep_kinds:
            rows.append(row)
    opt_rows.sort(key=lambda r: r[0], reverse=True)
    # Top OGBL, top OOAT, and next few
    shown = []
    seen_ooat = seen_ogbl = False
    for row in opt_rows:
        name = row[1]
        if name.startswith("OOAT") and not seen_ooat:
            shown.append(row)
            seen_ooat = True
        elif name.startswith("OGBL") and not seen_ogbl:
            shown.append(row)
            seen_ogbl = True
        elif len(shown) < 6:
            shown.append(row)
    rows.extend(shown)
    rows.sort(key=lambda r: r[0], reverse=True)
    selected_keys: list[str] = []
    for mean, name, kind, at, wrong, ev, _k in rows:
        selected_keys.append(_k)
        lines.append(
            f"| {name} | {kind} | {_fmt_x(at['mean'])} | {_fmt_x(at['median'])} | "
            f"{_fmt_pct(at['p_lost'])} | {_fmt_x(wrong['mean'])} | "
            f"{_fmt_x(ev) if ev is not None else '—'} |"
        )

    # Means across exit levels (same structures as primary table)
    level_cols = [str(x) for x in results.get("levels_bp", [200, 250, 300, 350, 400])]
    lines += [
        "",
        "## Mean multiples by exit level",
        "",
        "| Structure | " + " | ".join(f"{c} bp" for c in level_cols) + " | Wrong |",
        "|-----------|" + "|".join(["-----:"] * len(level_cols)) + "|------:|",
    ]
    # Preserve @300 ranking order
    for _mean, name, _kind, _at, wrong, _ev, key in rows:
        v = results["structures"][key]
        by = v.get("by_level") or {}
        cells = []
        for c in level_cols:
            if c in by:
                cells.append(_fmt_x(by[c]["mean"]))
            else:
                cells.append("—")
        lines.append(f"| {name} | " + " | ".join(cells) + f" | {_fmt_x(wrong['mean'])} |")

    lines += ["", "## What each structure is", ""]
    for _mean, name, _kind, _at, _wrong, _ev, key in rows:
        lines.append(f"- **{name}**: {_describe(key, results['structures'][key])}")

    lines += ["", "## Bank pick", ""]
    if results.get("bank_rank"):
        lines += [
            "| Bank | Score | β_spread | Mean episode DD | Two-sided opts | IV/RV | Notes |",
            "|------|------:|---------:|----------------:|---------------:|------:|-------|",
        ]
        for r in results["bank_rank"]:
            ivrv = f"{r['iv_vs_realised']:.2f}" if r.get("iv_vs_realised") else "—"
            lines.append(
                f"| {r['code']} | {r['score']:.2f} | {r['beta_s']:.5f} | "
                f"{100*r['mean_dd']:.1f}% | {r['option_two_sided']} | {ivrv} | "
                f"{'; '.join(r.get('notes') or []) or '—'} |"
            )
        best = results["bank_rank"][0]
        lines += [
            "",
            "Columns: **β_spread** = daily share-price move per 1 bp of OAT–Bund widening "
            "(−0.0039 ≈ −0.39% per bp), from a regression on two years of daily data; "
            "**Mean episode DD** = average worst fall in the 2011 euro crisis, the June 2024 French snap "
            "election and the Aug–Oct 2026 stress; **Two-sided opts** = Eurex option strikes with both a bid "
            "and an ask; **IV/RV** = option implied vol divided by recent realised vol (above 1 means puts are "
            "expensive).",
            "",
            "Score = β term + drawdown term − idiosyncratic-vol term + liquidity term − expensive-puts "
            "term. The weights are a judgement call, not fitted.",
            "",
        ]
        dd = best.get("episode_drawdowns") or {}
        lines += [
            f"**Pick: {best['code']}** ({best['yahoo']}). It has the largest share-price sensitivity to the "
            f"spread (β {best['beta_s']:.4f}) and the deepest stress drawdowns on average "
            f"(2011 {100 * dd.get('euro_crisis_2011', 0):.0f}%, 2024 {100 * dd.get('france_snap_2024', 0):.0f}%, "
            f"2026 {100 * dd.get('france_stress_2026', 0):.0f}%), and the most quoted option strikes. "
            "Against it: its puts are the most expensive relative to realised vol, and it has the most "
            "bank-specific noise. Crédit Agricole is a close second with cheaper puts but a weaker spread link.",
            "",
        ]
    if results.get("bank_put_suggestion"):
        s = results["bank_put_suggestion"]
        lines += [
            "### Suggested bank put spread (live snapshot)",
            "",
            f"- Buy {s['code']} {s['k_long']:g} put / sell {s['k_short']:g} put, "
            f"expiry {s['expiry']} (spot {s['spot']:.2f}).",
            f"- Live debit ≈ **{s['live_debit']:.2f}** pts (ask−bid crossed); "
            f"half-spread ≈ {s['half_spread']:.2f}; ATM IV ≈ {100*s['atm_iv']:.1f}%.",
            f"- **Why these strikes:** the shape comes from the research note (long put about 10–15% below "
            f"the share price, short put about 35–40% below, longest listed expiry). The code targets 12% and "
            f"37% below {s['spot']:.2f} ({s['spot'] * 0.88:.2f} and {s['spot'] * 0.63:.2f}) and snaps to the "
            f"nearest listed strikes, {s['k_long']:g} and {s['k_short']:g}. "
            f"{s['expiry']} is the last Eurex expiry in the snapshot. The strikes were not optimised.",
            f"- Maximum payout is {s['k_long'] - s['k_short']:g} per share for a {s['live_debit']:.2f} cost "
            f"(≈{(s['k_long'] - s['k_short']) / s['live_debit']:.1f}× before fees), which is why the multiple "
            "flattens above 300 bp.",
            "",
        ]

    lines += ["", "## Concrete trade suggestions", ""]
    for s in results.get("suggestions") or []:
        key = s.get("key")
        by = (results["structures"].get(key) or {}).get("by_level") or {}
        level_bits = ", ".join(
            f"{c}={_fmt_x(by[c]['mean'])}" for c in level_cols if c in by
        )
        lines += [
            f"### {s['rank']}. {s['name']}",
            "",
            f"- @300 (base) mean **{_fmt_x(s['mean_300'])}**, subjective odds EV **{_fmt_x(s['odds_ev'])}**.",
            f"- Means by level: {level_bits}." if level_bits else "",
            f"- Detail: `{json.dumps(s.get('detail') or {}, default=str)[:500]}`",
            f"- Weakness: {s['weakness']}",
            "",
        ]

    lines += [
        "## Notes",
        "",
        "- Broker choice / order frequency are out of scope; fills always cross the bid/ask.",
        "- Swissquote options fee assumed €2.50/contract/side (tariff not confirmed live).",
        "- Machine-readable: `data/v7_evaluate.json`.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
