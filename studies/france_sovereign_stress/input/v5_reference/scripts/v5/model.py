"""v5 calibration and daily scenario paths (business days, today → 1 Jul 2027).

Right world (base case): the OAT–Bund spread reaches a stress level S* (240 / 300 / 340 / 400 bp) by 1 Jul 2027.
Completion day tc ~ U(EVENT_BD, T). Before the event start (tc − EVENT_BD) spread and Bund follow driftless random
walks with realized daily vol (last 6 months, Student-t tails). Over the event the spread is bridged to exactly S*
at tc (doubled noise), while Bunds move −f · jump on top of their own noise, f ~ U(0.10, 0.70). Everything is closed
at tc (take profit at the stress level).
Wrong world (check only): the same random walks with no event, closed on 1 Jul 2027.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

JOB = Path(__file__).resolve().parents[2]
DATA = JOB / "data" / "v5"
END = date(2027, 7, 1)
LEVELS = (240, 300, 340, 400)
EVENT_BD = 15
F_RANGE = (0.10, 0.70)
T_DOF = 4
VOL_WINDOW = 126
EVENT_VOL_MULT = 2.0


def _weekdays(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df.index.dayofweek < 5]
    return df[~df.index.duplicated()]


@dataclass
class Calib:
    sig_s: float
    sig_b: float
    rho: float
    stocks: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Calib":
        y = _weekdays(pd.read_csv(DATA / "yields_daily.csv", index_col=0, parse_dates=True))
        d = pd.DataFrame({"ds": y.spread_bp.diff(), "db": y.bund10.diff() * 100}).dropna()
        recent = d.iloc[-VOL_WINDOW:]
        px = pd.read_csv(DATA / "stocks_daily.csv", index_col=0, parse_dates=True)
        r = np.log(px).diff()
        stocks = {}
        for c in px.columns:
            df = pd.concat([r[c], d], axis=1, join="inner").dropna()
            x = np.column_stack([np.ones(len(df)), df.ds, df.db])
            yv = df[c].to_numpy()
            b = np.linalg.lstsq(x, yv, rcond=None)[0]
            e = pd.Series(yv - x @ b)
            stocks[c] = {"beta_s": float(b[1]), "beta_b": float(b[2]), "idio": float(e.iloc[-VOL_WINDOW:].std()),
                         "r2": float(1 - e.var() / yv.var(ddof=1))}
        return cls(float(recent.ds.std()), float(recent.db.std()), float(recent.ds.corr(recent.db)), stocks)


@dataclass
class FutCalib:
    """Futures price sensitivity and roll cost measured from Eurex settlements against CNBC 10Y yields."""
    eur_per_bp: dict
    duration: dict
    carry_bp_per_day: dict
    corr: dict
    days: int

    @classmethod
    def load(cls) -> "FutCalib":
        es = pd.read_csv(DATA / "eurex_settles.csv", index_col=0, parse_dates=True)
        y = _weekdays(pd.read_csv(DATA / "yields_daily.csv", index_col=0, parse_dates=True))
        df = es.join(y, how="inner")
        d = df.diff().dropna()
        eur, dur, carry, corr = {}, {}, {}, {}
        for code, yld in (("FOAT", "oat10"), ("FGBL", "bund10")):
            slope = np.polyfit(d[yld] * 100, d[f"{code}_front"], 1)[0]
            eur[code] = float(-slope * 1000)
            dur[code] = float(-slope * 1e4 / df[f"{code}_front"].mean())
            corr[code] = float(np.corrcoef(d[yld], d[f"{code}_front"])[0, 1])
            calendar = float((df[f"{code}_front"] - df[f"{code}_next"]).mean())
            carry[code] = calendar * 1000 / eur[code] / 63
        return cls(eur, dur, carry, corr, len(df))


def bdays(start: date, end: date = END) -> np.ndarray:
    return np.array([start + timedelta(days=i) for i in range((end - start).days + 1)
                     if (start + timedelta(days=i)).weekday() < 5])


def _t(rng, shape):
    return rng.standard_t(T_DOF, shape) * np.sqrt((T_DOF - 2) / T_DOF)


@dataclass
class World:
    """Cumulative changes from today (bp): spread ds[n, T+1], Bund db[n, T+1]; exit index tc[n]."""
    s0: float
    days: np.ndarray
    ds: np.ndarray
    db: np.ndarray
    tc: np.ndarray
    f: np.ndarray
    level: float | None
    seed: int

    @property
    def n(self) -> int:
        return self.ds.shape[0]

    @property
    def T(self) -> int:
        return self.ds.shape[1] - 1

    def stock_returns(self, cal: Calib, tic: str) -> np.ndarray:
        """Cumulative log return paths for one stock: beta to spread and Bund increments plus t-noise."""
        st = cal.stocks[tic]
        rng = np.random.default_rng(self.seed + 1000 + sorted(cal.stocks).index(tic))
        inc = st["beta_s"] * np.diff(self.ds, axis=1) + st["beta_b"] * np.diff(self.db, axis=1)
        inc = inc + st["idio"] * _t(rng, inc.shape)
        return np.concatenate([np.zeros((self.n, 1)), np.cumsum(inc, axis=1)], axis=1)


def simulate(cal: Calib, s0: float, start: date, n: int, level: float | None, seed: int = 5) -> World:
    rng = np.random.default_rng(seed)
    days = bdays(start)
    T = len(days) - 1
    es = cal.sig_s * _t(rng, (n, T))
    eb = cal.sig_b * (cal.rho * es / cal.sig_s + np.sqrt(1 - cal.rho ** 2) * _t(rng, (n, T)))
    ds = np.concatenate([np.zeros((n, 1)), np.cumsum(es, axis=1)], axis=1)
    db = np.concatenate([np.zeros((n, 1)), np.cumsum(eb, axis=1)], axis=1)
    if level is None:
        return World(s0, days, ds, db, np.full(n, T), np.zeros(n), None, seed)
    tc = rng.integers(EVENT_BD, T + 1, n)
    f = rng.uniform(*F_RANGE, n)
    ts = tc - EVENT_BD
    rows = np.arange(n)
    jump = (level - s0) - ds[rows, ts]
    k = np.arange(T + 1)[None, :] - ts[:, None]
    frac = np.clip(k / EVENT_BD, 0, 1)
    walk = cal.sig_s * EVENT_VOL_MULT * np.cumsum(_t(rng, (n, EVENT_BD)), axis=1)
    bridge = walk - (np.arange(1, EVENT_BD + 1) / EVENT_BD)[None, :] * walk[:, -1:]
    noise = np.zeros((n, T + 1))
    idx = ts[:, None] + np.arange(1, EVENT_BD + 1)[None, :]
    noise[rows[:, None], idx] = bridge
    in_event = (k > 0) & (k <= EVENT_BD)
    ds = np.where(k <= 0, ds, ds[rows, ts][:, None] + jump[:, None] * frac + np.where(in_event, noise, 0))
    db = db - (f * jump)[:, None] * frac
    return World(s0, days, ds, db, tc, f, level, seed)
