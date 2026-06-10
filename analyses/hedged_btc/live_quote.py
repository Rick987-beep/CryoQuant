"""1e — Live Deribit snapshot: index, DVOL, term structure, candidate leg prices."""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

DERIBIT = "https://www.deribit.com/api/v2/public"


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{DERIBIT}/{path}", timeout=30) as resp:
        return json.load(resp)["result"]


def _ticker(exp: str, strike: int, cp: str) -> dict | None:
    try:
        return _get(f"ticker?instrument_name=BTC-{exp}-{strike}-{cp}")
    except Exception:
        return None


def fetch_snapshot() -> dict:
    now = datetime.now(timezone.utc)
    spot = float(_get("get_index_price?index_name=btc_usd")["index_price"])

    end_ms = int(now.timestamp() * 1000)
    start_ms = end_ms - 3 * 86400000
    dvol_payload = _get(
        f"get_volatility_index_data?currency=BTC&start_timestamp={start_ms}"
        f"&end_timestamp={end_ms}&resolution=3600"
    )
    dvol = float(dvol_payload["data"][-1][4]) if dvol_payload.get("data") else None

    insts = _get("get_instruments?currency=BTC&kind=option&expired=false")
    by_exp: dict[str, list] = {}
    dte_by_exp: dict[str, float] = {}
    for i in insts:
        lbl = i["instrument_name"].split("-")[1]
        dte = (i["expiration_timestamp"] / 1000 - now.timestamp()) / 86400
        by_exp.setdefault(lbl, []).append(i)
        if lbl not in dte_by_exp or dte < dte_by_exp[lbl]:
            dte_by_exp[lbl] = dte

    term_rows = []
    for exp, dte in sorted(dte_by_exp.items(), key=lambda x: x[1]):
        if dte < 0.5 or dte > 300:
            continue
        strikes = [i["strike"] for i in by_exp[exp]]
        atm = int(min(strikes, key=lambda s: abs(s - spot)))
        for cp in ("C", "P"):
            t = _ticker(exp, atm, cp)
            if not t:
                continue
            term_rows.append({
                "expiry": exp, "dte": round(dte, 1), "strike": atm, "side": cp,
                "mark_btc": t["mark_price"], "mark_usd": t["mark_price"] * spot,
                "iv_pct": t.get("mark_iv"), "delta": t.get("greeks", {}).get("delta"),
            })

    def pick_expiry(lo: float, hi: float) -> str | None:
        target = (lo + hi) / 2
        best: str | None = None
        best_dist: float | None = None
        for exp, dte in dte_by_exp.items():
            if lo <= dte <= hi:
                dist = abs(dte - target)
                if best is None or (best_dist is not None and dist < best_dist):
                    best, best_dist = exp, dist
        return best

    candidates: dict[str, dict] = {}
    for label, exp in [
        ("quarterly", pick_expiry(75, 120)),
        ("monthly", pick_expiry(40, 60)),
        ("front", pick_expiry(5, 14)),
    ]:
        if not exp:
            continue
        p62 = _ticker(exp, 62000, "P")
        c68 = _ticker(exp, 68000, "C")
        c72 = _ticker(exp, 72000, "C")
        if p62 and c68:
            net_btc = p62["mark_price"] - c68["mark_price"]
            candidates[f"C1_collar_{label}"] = {"expiry": exp, "net_usd": net_btc * spot, "net_pct": net_btc * 100}
        if p62 and c68 and c72:
            net_btc = p62["mark_price"] - c68["mark_price"] + c72["mark_price"]
            candidates[f"C1_reopener_{label}"] = {"expiry": exp, "net_usd": net_btc * spot, "net_pct": net_btc * 100}
        cc = _ticker(exp, 66000, "C") if label == "front" else None
        if cc:
            candidates["L2_covered_call_front"] = {
                "expiry": exp, "credit_usd": cc["mark_price"] * spot, "credit_pct": cc["mark_price"] * 100,
            }

    return {
        "as_of_utc": now.isoformat(),
        "spot_usd": spot,
        "dvol_30d": dvol,
        "term_structure": term_rows,
        "candidates": candidates,
    }


def snapshot_to_frames(snap: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    meta = pd.DataFrame([{
        "as_of_utc": snap["as_of_utc"],
        "spot_usd": snap["spot_usd"],
        "dvol_30d": snap.get("dvol_30d"),
    }])
    term = pd.DataFrame(snap.get("term_structure", []))
    return meta, term


def run(out_dir: Path) -> dict:
    snap = fetch_snapshot()
    meta, term = snapshot_to_frames(snap)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    meta.to_csv(out_dir / f"live_quote_meta_{ts}.csv", index=False)
    term.to_csv(out_dir / f"live_quote_term_{ts}.csv", index=False)
    if snap.get("candidates"):
        pd.DataFrame([
            {"structure": k, **v} for k, v in snap["candidates"].items()
        ]).to_csv(out_dir / f"live_quote_candidates_{ts}.csv", index=False)
    log.info("Live snapshot: spot=$%s dvol=%s", snap["spot_usd"], snap.get("dvol_30d"))
    return snap
