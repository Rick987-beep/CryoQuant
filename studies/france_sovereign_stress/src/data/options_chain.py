"""Fetch live Eurex OOAT / OGBL (and optional equity) option chains via Playwright.

The Eurex product page renders quotes client-side; the full chain sits in the
React props of the price table. Port of ``input/v5_reference/scripts/v4/fetch.py``
with all listed expiries (not just Oct/Nov).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

BOND_OPT_BASE = (
    "https://www.eurex.com/ex-en/markets/int/long-term-interest-rates/"
    "fix-opt/government-bonds/"
)
BOND_PRODUCTS: dict[str, str] = {
    "OOAT": BOND_OPT_BASE + "Options-on-Euro-OAT-Futures-137406",
    "OGBL": BOND_OPT_BASE + "Options-on-Euro-Bund-Futures-137308",
}

# Eurex equity options (single-stock) — product pages under equ/equ-opt/options/.
EQUITY_PRODUCTS: dict[str, str] = {
    "BNP": "https://www.eurex.com/ex-en/markets/equ/equ-opt/options/BNP-Paribas-951478",
    "GLE": "https://www.eurex.com/ex-en/markets/equ/equ-opt/options/Soci-t-G-n-rale-945950",
    "ACA": "https://www.eurex.com/ex-en/markets/equ/equ-opt/options/Cr-dit-Agricole-945860",
}

FIELDS = [
    "bid",
    "ask",
    "bidVol",
    "askVol",
    "last",
    "lastTraded",
    "volume",
    "openInt",
    "dSettle",
    "strikePrice",
]

LIST_EXPIRIES_JS = """() => {
  const buttons = [...document.querySelectorAll('button')];
  const re = /^\\d{2}\\/\\d{2}\\/\\d{4}$/;
  const out = [];
  for (const b of buttons) {
    const t = (b.innerText || '').trim();
    if (re.test(t) && !out.includes(t)) out.push(t);
  }
  return out;
}"""

GRAB_JS = """async (expiries) => {
  const FIELDS = %s;
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
}""" % json.dumps(FIELDS)


def _sort_expiries(labels: list[str]) -> list[str]:
    def key(s: str) -> datetime:
        return datetime.strptime(s, "%d/%m/%Y")

    return sorted(labels, key=key)


def fetch_product_chain(
    page: Any,
    product: str,
    url: str,
    *,
    expiries: list[str] | None = None,
) -> dict[str, Any]:
    """Navigate to a product page and return ``{expiry_label: {put, call}}``."""
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    try:
        page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:  # noqa: BLE001 — some product pages keep connections open
        pass
    page.wait_for_function(
        "() => { const t = document.querySelectorAll('table')[1];"
        " return t && t.querySelectorAll('tr').length > 5; }",
        timeout=60_000,
    )
    listed = _sort_expiries(page.evaluate(LIST_EXPIRIES_JS) or [])
    if not listed:
        log.warning("%s: no expiry buttons found on %s", product, url)
        return {}
    want = expiries or listed
    want = [e for e in want if e in listed] or listed
    log.info("%s: fetching %d/%d expiries", product, len(want), len(listed))
    raw = page.evaluate(GRAB_JS, want)
    out: dict[str, Any] = {}
    for label, ch in (raw or {}).items():
        if not ch:
            out[label] = None
            continue
        out[label] = {
            "put": ch.get("put") or [],
            "call": ch.get("call") or [],
            "n_put": len(ch.get("put") or []),
            "n_call": len(ch.get("call") or []),
        }
    return out


def fetch_bond_option_chains(
    *,
    products: dict[str, str] | None = None,
    expiries: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch OOAT / OGBL chains. Returns ``{product: {expiry: chain}}``."""
    from playwright.sync_api import sync_playwright

    products = products or BOND_PRODUCTS
    out: dict[str, dict[str, Any]] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA)
        for code, url in products.items():
            try:
                out[code] = fetch_product_chain(page, code, url, expiries=expiries)
            except Exception as exc:  # noqa: BLE001
                log.exception("%s chain fetch failed: %s", code, exc)
                out[code] = {}
        browser.close()
    return out


def fetch_equity_option_chains(
    *,
    products: dict[str, str] | None = None,
    expiries: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch BNP / GLE / ACA Eurex equity option chains."""
    return fetch_bond_option_chains(products=products or EQUITY_PRODUCTS, expiries=expiries)


def chain_summary(chains: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compact QA: expiries, two-sided quote counts, median half-spread."""
    summary: dict[str, Any] = {}
    for product, by_exp in chains.items():
        exps = []
        for label, ch in by_exp.items():
            if not ch:
                exps.append({"expiry": label, "ok": False})
                continue
            two_sided = 0
            half_spreads: list[float] = []
            for side in ("put", "call"):
                for r in ch.get(side) or []:
                    bid, ask = _num(r.get("bid")), _num(r.get("ask"))
                    if bid is not None and ask is not None and bid > 0 and ask > bid:
                        two_sided += 1
                        half_spreads.append(0.5 * (ask - bid))
            exps.append(
                {
                    "expiry": label,
                    "ok": True,
                    "n_put": ch.get("n_put", len(ch.get("put") or [])),
                    "n_call": ch.get("n_call", len(ch.get("call") or [])),
                    "two_sided": two_sided,
                    "median_half_spread": (
                        float(sorted(half_spreads)[len(half_spreads) // 2]) if half_spreads else None
                    ),
                }
            )
        summary[product] = exps
    return summary


def _num(x: Any) -> float | None:
    if x in (None, "", "-"):
        return None
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def write_chains_sidecar(path: Path, chains: dict[str, dict[str, Any]], *, kind: str) -> None:
    """Write a sidecar JSON next to the main eurex snapshot."""
    now = datetime.now(ZoneInfo("Europe/Berlin"))
    payload = {
        "fetched_at": now.isoformat(timespec="seconds"),
        "kind": kind,
        "chains": chains,
        "summary": chain_summary(chains),
    }
    path.write_text(json.dumps(payload, indent=2))
    log.info("wrote %s (%s products)", path, len(chains))


_EXPIRY_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
