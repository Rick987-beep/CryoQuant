"""Fetch live Eurex OOAT / OGBL option chains and CNBC 10Y yields into data/chains/.

The Eurex product page renders quotes client-side; the full chain (all strikes) sits in the React props of the
price table, so the page is loaded in headless Chromium and the props are read per expiry.

    .venv/bin/python jobs/france-sovereign-stress/scripts/v4/fetch.py [--expiries 23/10/2026,20/11/2026]
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

JOB = Path(__file__).resolve().parents[2]
CHAINS = JOB / "data" / "chains"
BASE = "https://www.eurex.com/ex-en/markets/int/long-term-interest-rates/fix-opt/government-bonds/"
PRODUCTS = {
    "OOAT": BASE + "Options-on-Euro-OAT-Futures-137406",
    "OGBL": BASE + "Options-on-Euro-Bund-Futures-137308",
}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
FUTURES = {"FOAT": 34684, "FGBL": 34656}
STATS = "https://www.eurex.com/api/v1/overallstatistics/{pid}?filtertype=overview"
CNBC = ("https://quote.cnbc.com/quote-html-webservice/quote.htm?symbols=FR10Y-FR%7CDE10Y-DE&requestMethod=quick"
        "&exthrs=1&noform=1&partnerId=2&fund=1&output=json")

GRAB_JS = """async (expiries) => {
  const FIELDS = ['bid','ask','bidVol','askVol','last','lastTraded','volume','openInt','dSettle','strikePrice'];
  const grab = () => {
    const tbl = document.querySelectorAll('table')[1];
    if (!tbl) return null;
    let f = tbl[Object.keys(tbl).find(k => k.startsWith('__reactFiber'))];
    for (let d = 0; d < 10 && f; d++, f = f.return) {
      const p = f.memoizedProps;
      if (p && p.putData) {
        const v = o => (o && typeof o === 'object' && 'value' in o) ? o.value : o;
        const m = r => Object.fromEntries(FIELDS.map(k => [k, v(r[k])]));
        return {put: p.putData.map(m), call: p.callData.map(m)};
      }
    }
    return null;
  };
  const out = {};
  for (const e of expiries) {
    const b = [...document.querySelectorAll('button')].find(x => x.innerText.trim() === e);
    if (!b) { out[e] = null; continue; }
    b.click();
    await new Promise(r => setTimeout(r, 2500));
    out[e] = grab();
  }
  return out;
}"""


def fetch_chain(page, product: str, expiries: list[str]) -> dict:
    page.goto(PRODUCTS[product], wait_until="networkidle", timeout=60_000)
    page.wait_for_function("() => { const t = document.querySelectorAll('table')[1];"
                           " return t && t.querySelectorAll('tr').length > 5; }", timeout=45_000)
    return page.evaluate(GRAB_JS, expiries)


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return json.load(urllib.request.urlopen(req, timeout=20))


def fetch_futures() -> dict:
    """Eurex statistics API per contract month: `last` = today's last trade (15 min delayed), `dSettle` = previous
    settlement. Back months trade rarely, so their live level is the front's last less the settlement calendar."""
    out = {}
    for code, pid in FUTURES.items():
        head = _get_json(STATS.format(pid=pid))
        busdate = datetime.strptime(head["header"]["tradingDates"][0], "%d-%m-%Y %H:%M").strftime("%Y%m%d")
        rows = _get_json(STATS.format(pid=pid) + f"&busdate={busdate}").get("dataRows", [])
        rows = sorted(rows, key=lambda r: r["date"])
        front = rows[0]
        months = []
        for r in rows:
            last = round(r["last"], 2) if r["last"] else None
            months.append({"expiry": r["date"], "last": last, "settle": round(r["dSettle"], 2),
                           "volume": r["volume"], "open_interest": r["openInt"],
                           "live": round(front["last"] - (front["dSettle"] - r["dSettle"]), 2)})
        out[code] = {"settle_date": busdate, "source": f"Eurex overallstatistics/{pid}", "months": months}
    return out


def fetch_yields() -> dict:
    req = urllib.request.Request(CNBC, headers={"User-Agent": UA})
    quotes = json.load(urllib.request.urlopen(req, timeout=20))["QuickQuoteResult"]["QuickQuote"]
    by = {q["symbol"]: q for q in quotes}
    return {"oat10": float(by["FR10Y-FR"]["last"]), "bund10": float(by["DE10Y-DE"]["last"]),
            "time": by["FR10Y-FR"]["last_time"], "source": "CNBC FR10Y-FR / DE10Y-DE"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expiries", default="23/10/2026,20/11/2026")
    args = ap.parse_args()
    expiries = args.expiries.split(",")
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y-%m-%dT%H%M")
    CHAINS.mkdir(parents=True, exist_ok=True)
    out = {"fetched_at": now.isoformat(timespec="seconds"), "yields": fetch_yields(), "futures": fetch_futures(),
           "chains": {}}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA)
        for product in PRODUCTS:
            out["chains"][product] = fetch_chain(page, product, expiries)
        browser.close()
    path = CHAINS / f"eurex_{stamp}.json"
    path.write_text(json.dumps(out, indent=1))
    for product, chains in out["chains"].items():
        for e, ch in chains.items():
            n = len(ch["put"]) if ch else 0
            print(f"{product} {e}: {n} strikes")
    print("yields", out["yields"])
    for code, fut in out["futures"].items():
        print(code, [(m["expiry"], m["last"], m["settle"], m["live"]) for m in fut["months"]])
    print("wrote", path)


if __name__ == "__main__":
    main()
