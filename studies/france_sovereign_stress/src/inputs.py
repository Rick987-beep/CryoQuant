"""Market inputs for the active snapshot, shared by every runner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from src.calibrate import (
    FutCalib,
    LivePnLCheck,
    StockBeta,
    VolCalib,
    calibrate_futures,
    calibrate_vol,
    live_spread_pnl,
    stock_betas,
)
from src.data.reference import (
    load_eurex_settles,
    load_eurex_snapshot,
    load_stocks_daily,
    load_yields_daily,
)
from src.evaluate import calmer_vol
from src.paths import active_stamp, is_reference_run, load_config, stamp_date


@dataclass
class MarketInputs:
    stamp: str
    start: date
    s0: float
    s0_report: float
    quote_time: str | None
    reference: bool
    yields: pd.DataFrame
    settles: pd.DataFrame
    stocks: pd.DataFrame
    fc: FutCalib
    vol: VolCalib
    vol_calm: VolCalib
    beta_cac: StockBeta
    pnl: LivePnLCheck

    @property
    def history_end(self) -> str:
        return str(self.yields.index[-1].date())

    def meta(self) -> dict:
        return {
            "stamp": self.stamp,
            "start": str(self.start),
            "s0": round(self.s0, 2),
            "s0_report": self.s0_report,
            "quote_time": self.quote_time,
            "reference_run": self.reference,
            "history_end": self.history_end,
            "settles_end": str(self.settles.index[-1].date()),
        }


def load_market_inputs(cfg: dict | None = None) -> MarketInputs:
    cfg = cfg or load_config()
    stamp = active_stamp()
    reference = is_reference_run()
    snap = load_eurex_snapshot(stamp)
    s0 = (float(snap["yields"]["oat10"]) - float(snap["yields"]["bund10"])) * 100.0
    window = int(cfg["simulation"]["vol_window_bdays"])
    settle_window = int((cfg.get("calibration") or {}).get("settle_window_days", 20))

    yields = load_yields_daily()
    settles = load_eurex_settles()
    stocks = load_stocks_daily()
    return MarketInputs(
        stamp=stamp,
        start=stamp_date(stamp),
        s0=s0,
        # v5 reports round the entry to 138 bp for the straight-line ladder
        s0_report=138.0 if reference else round(s0, 1),
        quote_time=snap["yields"].get("time"),
        reference=reference,
        yields=yields,
        settles=settles,
        stocks=stocks,
        fc=calibrate_futures(settles, yields, window=settle_window),
        vol=calibrate_vol(yields, window=window),
        vol_calm=calmer_vol(yields, window=window),
        beta_cac=stock_betas(stocks, yields, vol_window=window, tickers=["^FCHI"])["^FCHI"],
        pnl=live_spread_pnl(settles, yields),
    )
