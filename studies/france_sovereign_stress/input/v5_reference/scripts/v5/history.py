"""History for v5 calibration: CNBC 10Y yields (FR, DE) and Yahoo closes for French non-bank stocks.

Writes data/v5/yields_daily.csv (about 2 years daily), yields_weekly.csv (about 10 years weekly),
stocks_daily.csv and stocks_weekly.csv.

    .venv/bin/python jobs/france-sovereign-stress/scripts/v5/history.py
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pandas as pd
import yfinance as yf

JOB = Path(__file__).resolve().parents[2]
OUT = JOB / "data" / "v5"
CNBC = "https://ts-api.cnbc.com/harmony/app/charts/{rng}.json?symbol={sym}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
YIELDS = {"oat10": "FR10Y-FR", "bund10": "DE10Y-DE"}
STOCKS = {
    "^FCHI": "CAC 40", "CS.PA": "AXA", "SCR.PA": "SCOR", "ENGI.PA": "Engie", "DG.PA": "Vinci",
    "FGR.PA": "Eiffage", "EN.PA": "Bouygues", "ADP.PA": "Aéroports de Paris", "ORA.PA": "Orange",
    "VIE.PA": "Veolia", "URW.PA": "Unibail-Rodamco-Westfield", "LI.PA": "Klépierre", "GFC.PA": "Gecina",
    "COV.PA": "Covivio", "AMUN.PA": "Amundi", "SPIE.PA": "Spie", "AF.PA": "Air France-KLM", "RNO.PA": "Renault",
}


def cnbc(sym: str, rng: str) -> pd.Series:
    req = urllib.request.Request(CNBC.format(rng=rng, sym=sym), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        bars = json.load(r)["barData"]["priceBars"]
    idx = pd.to_datetime([b["tradeTime"][:8] for b in bars])
    return pd.Series([float(b["close"]) for b in bars], index=idx).sort_index()


def yields(rng: str) -> pd.DataFrame:
    df = pd.DataFrame({k: cnbc(s, rng) for k, s in YIELDS.items()}).dropna()
    df["spread_bp"] = (df["oat10"] - df["bund10"]) * 100
    return df


def stocks(period: str, interval: str) -> pd.DataFrame:
    px = yf.download(list(STOCKS), period=period, interval=interval, auto_adjust=True, progress=False)["Close"]
    px.index = pd.to_datetime(px.index).tz_localize(None).normalize()
    return px


EUREX_STATS = "https://www.eurex.com/api/v1/overallstatistics/{pid}?filtertype=overview"
FUTURES = {"FOAT": 34684, "FGBL": 34656}


def _eurex(pid: int, d: str = "") -> dict:
    url = EUREX_STATS.format(pid=pid) + (f"&busdate={d}" if d else "")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def eurex_settles() -> pd.DataFrame:
    """Daily settlements of the front two quarterly FOAT / FGBL contracts over Eurex's ~21-day window."""
    dates = [pd.to_datetime(x[:10], format="%d-%m-%Y") for x in _eurex(FUTURES["FOAT"])["header"]["tradingDates"]]
    rows = []
    for dt in dates:
        row = {"date": dt}
        for code, pid in FUTURES.items():
            months = sorted(_eurex(pid, dt.strftime("%Y%m%d")).get("dataRows", []), key=lambda m: m["date"])
            months = [m for m in months if m.get("dSettle")]
            if len(months) >= 2:
                row[f"{code}_front"], row[f"{code}_next"] = months[0]["dSettle"], months[1]["dSettle"]
                row[f"{code}_front_month"] = months[0]["date"]
        rows.append(row)
    return pd.DataFrame(rows).set_index("date").sort_index().dropna()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    es = eurex_settles()
    es.to_csv(OUT / "eurex_settles.csv")
    print(f"eurex settlements {es.index[0]:%Y-%m-%d}→{es.index[-1]:%Y-%m-%d} ({len(es)})")
    yd, yw = yields("1Y"), yields("5Y")
    yd.to_csv(OUT / "yields_daily.csv")
    yw.to_csv(OUT / "yields_weekly.csv")
    sd, sw = stocks("3y", "1d"), stocks("10y", "1wk")
    sd.to_csv(OUT / "stocks_daily.csv")
    sw.to_csv(OUT / "stocks_weekly.csv")
    print(f"yields daily {yd.index[0]:%Y-%m-%d}→{yd.index[-1]:%Y-%m-%d} ({len(yd)}), "
          f"weekly {yw.index[0]:%Y-%m-%d}→{yw.index[-1]:%Y-%m-%d} ({len(yw)}); last spread {yd.spread_bp.iloc[-1]:.1f} bp")
    print(f"stocks daily {sd.shape}, weekly {sw.shape}; missing: {[c for c in STOCKS if c not in sd or sd[c].isna().all()]}")


if __name__ == "__main__":
    main()
