#!/usr/bin/env python3
"""Phase 1 — Overlay Y finer-grid isolation screen + HTML report."""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

from src.overlay_y import screen_y_isolation, y1_grid, y2_grid, y3_grid, DEFAULT_ACCOUNT
from src.paths import load_config, reports_dir, data_dir
from src.report_overlay_y import render_overlay_y_report
from src.vix_data import load_vix_ohlc, parse_window

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    cfg = load_config()
    start, end = parse_window(cfg)
    # Default study window: exact trailing 10y → yesterday (see config.yaml).
    research = load_vix_ohlc(start, end)
    if research.empty:
        log.error("No bars in research window %s → %s", start.date(), end.date())
        return 1

    bt = cfg.get("backtest_defaults") or {}
    from cryoquant.backtest.account import VXM, VX, AccountConfig, ExecutionModel

    inst = str(bt.get("instrument", "VXM")).upper()
    instrument = VX if inst == "VX" else VXM
    account = AccountConfig(
        initial_cash=float(bt.get("initial_cash", 100_000.0)),
        instrument=instrument,
        execution=ExecutionModel(
            fee_per_side=float(bt.get("fee_per_side", 0.0)),
            spread_ticks=float(bt.get("spread_ticks", 0.0)),
            slippage_ticks=float(bt.get("slippage_ticks", 0.0)),
        ),
        contracts=int(bt.get("contracts", 1)),
    )

    n1, n2, n3 = len(y1_grid()), len(y2_grid()), len(y3_grid())
    log.info(
        "Overlay Y dollar grid — Y1=%d Y2=%d Y3=%d total=%d",
        n1, n2, n3, n1 + n2 + n3,
    )
    log.info(
        "Research window (default 10y): %s → %s · %d bars",
        research.index.min().date(),
        research.index.max().date(),
        len(research),
    )
    log.info(
        "Account $%.0f · %s ×$%.0f/pt · fee/side=$%.2f spread_ticks=%.2f",
        account.initial_cash,
        account.instrument.symbol,
        account.instrument.multiplier,
        account.execution.fee_per_side,
        account.execution.spread_ticks,
    )

    t0 = time.perf_counter()
    screen = screen_y_isolation(research, account=account)
    elapsed = time.perf_counter() - t0
    board = screen.leaderboard
    log.info(
        "Screen done in %.1fs · candidates=%d · kept runs=%d",
        elapsed, len(board), len(screen.runs),
    )

    out_dir = reports_dir()
    data = data_dir()
    runs_dir = data / "overlay_y_runs"
    if runs_dir.exists():
        for p in runs_dir.glob("*.parquet"):
            p.unlink()
    board_path = out_dir / "phase1_y_isolation_leaderboard.parquet"
    board.to_parquet(board_path)

    for rid, run in screen.runs.items():
        stem = data / "overlay_y_runs" / rid
        stem.parent.mkdir(parents=True, exist_ok=True)
        run["equity"].to_frame("equity").to_parquet(stem.with_suffix(".equity.parquet"))
        if run["trades"] is not None and len(run["trades"]):
            run["trades"].to_parquet(stem.with_suffix(".trades.parquet"))

    survivors = board[board["pass_a"]]
    summary = {
        "elapsed_s": round(elapsed, 2),
        "grid_sizes": {"Y1": n1, "Y2": n2, "Y3": n3, "total": n1 + n2 + n3},
        "account": {
            "initial_cash": account.initial_cash,
            "instrument": account.instrument.symbol,
            "multiplier": account.instrument.multiplier,
            "fee_per_side": account.execution.fee_per_side,
            "spread_ticks": account.execution.spread_ticks,
            "slippage_ticks": account.execution.slippage_ticks,
        },
        "n_candidates": int(len(board)),
        "n_pass_a": int(survivors.shape[0]),
        "n_income_ok": int(board["income_ok"].sum()),
        "n_freq_ok": int(board["freq_ok"].sum()),
        "window_start": str(research.index.min().date()),
        "window_end": str(research.index.max().date()),
        "research_start": str(start.date()),
        "research_end": str(end.date()),
        "n_bars": int(len(research)),
        "best_by_idea": {},
        "top10": board.head(10).to_dict(orient="records"),
    }
    for idea, g in board.groupby("idea"):
        pos = g[g["terminal_equity"] > account.initial_cash]
        pool = pos if len(pos) else g
        top = pool.sort_values(
            ["terminal_equity", "sharpe_equity"], ascending=[False, False]
        ).iloc[0]
        summary["best_by_idea"][idea] = {
            k: (None if isinstance(v, float) and pd.isna(v) else v)
            for k, v in top.to_dict().items()
        }

    js = out_dir / "phase1_y_isolation.json"
    js.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    html_path = render_overlay_y_report(
        screen,
        window_start=str(research.index.min().date()),
        window_end=str(research.index.max().date()),
        n_bars=len(research),
        out_path=out_dir / "overlay_y_isolation_report.html",
    )
    log.info("Pass A=%d · income_ok=%d · freq_ok=%d", summary["n_pass_a"], summary["n_income_ok"], summary["n_freq_ok"])
    log.info("Leaderboard → %s", board_path)
    log.info("Report → %s", html_path)
    for idea, row in summary["best_by_idea"].items():
        log.info(
            "Best %s: equity=$%.0f tpy=%.1f dd=%.1f%% trades=%s contracts=%s",
            idea,
            row.get("terminal_equity") or 0,
            row.get("trades_per_year") or 0,
            100 * (row.get("max_drawdown") or 0),
            row.get("n_trades"),
            row.get("contracts"),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
