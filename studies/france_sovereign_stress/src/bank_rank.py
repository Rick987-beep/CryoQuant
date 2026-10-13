"""Rank French banks for the sovereign-stress sleeve.

Criteria (higher score is better for a short / put trade):
  1. Beta to OAT–Bund spread changes (more negative equity when spread widens).
  2. Drawdown in past French-stress episodes.
  3. Idiosyncratic vol (more idio = noisier; mildly penalised).
  4. Option liquidity (two-sided quotes, open interest) when a chain exists.
  5. IV vs realised (richer put IV is worse for buying puts).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.calibrate import StockBeta, stock_betas
from src.options import OptionSnapshot, implied_vol, num


BANK_YAHOO = {
    "BNP": "BNP.PA",
    "GLE": "GLE.PA",
    "ACA": "ACA.PA",
    "EXV1": "EXV1.DE",  # Euro Stoxx Banks ETF proxy
}

EPISODES = [
    ("euro_crisis_2011", "2011-07-01", "2012-06-30"),
    ("france_snap_2024", "2024-06-01", "2024-08-31"),
    ("france_stress_2026", "2026-08-15", "2026-10-12"),
]


@dataclass
class BankScore:
    code: str
    yahoo: str
    beta_s: float
    beta_b: float
    idio: float
    r2: float
    episode_drawdowns: dict[str, float]
    mean_dd: float
    option_two_sided: int
    option_median_hs: float | None
    atm_iv: float | None
    realised_vol: float | None
    iv_vs_realised: float | None
    score: float
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "yahoo": self.yahoo,
            "beta_s": self.beta_s,
            "beta_b": self.beta_b,
            "idio": self.idio,
            "r2": self.r2,
            "episode_drawdowns": self.episode_drawdowns,
            "mean_dd": self.mean_dd,
            "option_two_sided": self.option_two_sided,
            "option_median_hs": self.option_median_hs,
            "atm_iv": self.atm_iv,
            "realised_vol": self.realised_vol,
            "iv_vs_realised": self.iv_vs_realised,
            "score": self.score,
            "notes": self.notes,
        }


def _max_drawdown(px: pd.Series) -> float:
    if px.empty or px.isna().all():
        return 0.0
    s = px.dropna()
    if s.empty:
        return 0.0
    peak = s.cummax()
    dd = (s / peak - 1.0).min()
    return float(dd)


def _realised_vol(px: pd.Series, window: int = 63) -> float | None:
    r = np.log(px).diff().dropna()
    if len(r) < window:
        return None
    return float(r.iloc[-window:].std() * np.sqrt(252))


def _option_liquidity(snap: OptionSnapshot | None, code: str) -> tuple[int, float | None, float | None]:
    if snap is None:
        return 0, None, None
    exps = [(e, exp) for (p, e), exp in snap.bank_expiries.items() if p == code]
    if not exps:
        return 0, None, None
    # Use nearest expiry with quotes.
    label, exp = min(exps, key=lambda x: x[1].date)
    two = 0
    hs: list[float] = []
    for cp in ("P", "C"):
        for q in exp.quotes.get(cp, {}).values():
            if q.two_sided:
                two += 1
                if q.half_spread is not None:
                    hs.append(q.half_spread)
    atm = exp.skew.atm if exp.skew.atm > 0 else None
    return two, (float(np.median(hs)) if hs else None), atm


def rank_banks(
    stocks: pd.DataFrame,
    yields: pd.DataFrame,
    *,
    snap: OptionSnapshot | None = None,
    vol_window: int = 126,
) -> list[BankScore]:
    """Return banks sorted by score (best short/put candidate first)."""
    tickers = [t for t in BANK_YAHOO.values() if t in stocks.columns]
    betas = stock_betas(stocks, yields, vol_window=vol_window, tickers=tickers)
    scores: list[BankScore] = []

    for code, yahoo in BANK_YAHOO.items():
        if yahoo not in stocks.columns or yahoo not in betas:
            continue
        b: StockBeta = betas[yahoo]
        px = stocks[yahoo].dropna()
        dds: dict[str, float] = {}
        for name, a, c in EPISODES:
            dds[name] = _max_drawdown(px.loc[a:c])
        mean_dd = float(np.mean(list(dds.values()))) if dds else 0.0
        rv = _realised_vol(px)
        two, med_hs, atm_iv = _option_liquidity(snap, code)
        iv_vs = None
        if atm_iv is not None and rv is not None and rv > 0:
            iv_vs = atm_iv / rv

        notes: list[str] = []
        # Score components (higher = better for short/put on French stress).
        # beta_s: more negative is better (equity falls when spread widens).
        # mean_dd: more negative drawdown is better.
        # idio: mild penalty.
        # option liquidity: bonus.
        # iv_vs_realised: penalise rich puts when buying.
        s_beta = -b.beta_s * 500.0  # scale: beta_s ~ -0.001 to -0.01 per bp
        s_dd = -mean_dd * 10.0  # drawdown -0.3 → +3
        s_idio = -b.idio * 50.0
        s_liq = np.log1p(two) * 0.5
        s_iv = 0.0
        if iv_vs is not None:
            s_iv = -max(iv_vs - 1.0, 0.0) * 1.0
            if iv_vs > 1.3:
                notes.append(f"puts rich vs realised (IV/RV={iv_vs:.2f})")
        if two == 0:
            notes.append("no two-sided Eurex equity option quotes in snapshot")
        if abs(b.beta_s) < 1e-5:
            notes.append("near-zero spread beta")

        score = float(s_beta + s_dd + s_idio + s_liq + s_iv)
        scores.append(
            BankScore(
                code=code,
                yahoo=yahoo,
                beta_s=b.beta_s,
                beta_b=b.beta_b,
                idio=b.idio,
                r2=b.r2,
                episode_drawdowns=dds,
                mean_dd=mean_dd,
                option_two_sided=two,
                option_median_hs=med_hs,
                atm_iv=atm_iv,
                realised_vol=rv,
                iv_vs_realised=iv_vs,
                score=score,
                notes=notes,
            )
        )

    scores.sort(key=lambda x: x.score, reverse=True)
    return scores


def suggest_bank_put_spread(
    snap: OptionSnapshot,
    code: str,
    spot: float,
    *,
    otm_long: float = 0.12,
    otm_short: float = 0.37,
) -> dict[str, Any] | None:
    """Pick ~12% OTM long put / ~37% OTM short put on the longest listed expiry."""
    exps = [exp for (p, _), exp in snap.bank_expiries.items() if p == code]
    if not exps:
        return None
    exp = max(exps, key=lambda e: e.date)
    k_long = round(spot * (1 - otm_long) * 20) / 20  # 0.05 grid
    k_short = round(spot * (1 - otm_short) * 20) / 20
    # Snap to available strikes.
    puts = sorted(exp.quotes.get("P", {}))
    if not puts:
        return None

    def nearest(target: float) -> float:
        return min(puts, key=lambda k: abs(k - target))

    k_long = nearest(k_long)
    k_short = nearest(k_short)
    if k_short >= k_long:
        # Ensure short is further OTM.
        deeper = [k for k in puts if k < k_long]
        if not deeper:
            return None
        k_short = deeper[0]
    q_l = exp.quotes["P"].get(k_long)
    q_s = exp.quotes["P"].get(k_short)
    if q_l is None or q_s is None:
        return None
    if not q_l.two_sided:
        return None
    # Short leg: prefer two-sided; else use settle as sell (flagged).
    if q_s.two_sided:
        debit = q_l.ask - q_s.bid  # type: ignore[operator]
        hs = 0.5 * ((q_l.ask - q_l.bid) + (q_s.ask - q_s.bid))  # type: ignore[operator]
        flagged = False
    elif q_s.settle is not None and q_s.settle > 0:
        debit = q_l.ask - q_s.settle  # type: ignore[operator]
        hs = q_l.half_spread or 0.05
        flagged = True
    else:
        return None
    if debit is None or debit <= 0:
        return None
    return {
        "code": code,
        "expiry": exp.label,
        "expiry_date": str(exp.date),
        "spot": spot,
        "k_long": k_long,
        "k_short": k_short,
        "live_debit": float(debit),
        "half_spread": float(hs),
        "atm_iv": exp.skew.atm,
        "fwd": exp.fwd,
        "settle_flagged_short": flagged,
        "long_ask": q_l.ask,
        "short_bid": q_s.bid if q_s.two_sided else q_s.settle,
    }
