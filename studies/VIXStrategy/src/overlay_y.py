"""Overlay Y — mean-reversion income sleeve (VIX-only).

Three ideas (Y1 z-score, Y2 percentile, Y3 crush fade). Primary path uses OHLC
**touch** fills with levels frozen from prior closes. Mutex: no new entries /
flatten at open when ``t_tactical_on`` is true as of prior close.

Scoreboard is a **dollar futures account** (default: $100k cash, Mini VIX / VXM
at $100 per point). Execution fees / bid-ask live on ``AccountConfig.execution``
so costs can be turned on later without rewriting the state machines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from cryoquant.backtest.account import (
    VXM,
    AccountConfig,
    apply_fill_price,
    build_futures_equity,
    futures_pnl_dollars,
)
from cryoquant.backtest.metrics import compute_metrics
from cryoquant.backtest.replay import (
    ReplayResult,
    long_touch_fill,
    short_touch_fill,
)
from cryoquant.backtest.trades import _empty_enriched, enrich_trades

from src.band_features import (
    build_y_features,
    rolling_quantile_price,
    rolling_std,
    sma,
)

IdeaId = Literal["Y1", "Y2", "Y3"]

DEFAULT_ACCOUNT = AccountConfig(
    initial_cash=100_000.0,
    instrument=VXM,
    contracts=1,
)


@dataclass(frozen=True)
class Y1Config:
    n: int = 20
    z_enter: float = 1.5
    max_hold: int = 10
    contracts: int = 1


@dataclass(frozen=True)
class Y2Config:
    w: int = 60
    lo: float = 0.20
    hi: float = 0.80
    mid: float = 0.50
    max_hold: int = 10
    contracts: int = 1


@dataclass(frozen=True)
class Y3Config:
    rank_w: int = 60
    g: float = 0.20
    g_stop: float = 0.25
    rank_min: float = 0.70
    max_hold: int = 10
    contracts: int = 1
    use_t_exit_arm: bool = True


def _years(index: pd.DatetimeIndex) -> float:
    if len(index) < 2:
        return 0.0
    days = (index[-1] - index[0]).total_seconds() / 86_400.0
    return max(days / 365.25, 1e-9)


def _account_for(cfg_contracts: int, account: AccountConfig | None) -> AccountConfig:
    base = account or DEFAULT_ACCOUNT
    return base.with_contracts(int(cfg_contracts))


def _make_trade(
    *,
    entry_i: int,
    exit_i: int,
    entry_mid: float,
    exit_mid: float,
    side: Literal["long", "short"],
    exit_type: str,
    idx: pd.DatetimeIndex,
    account: AccountConfig,
) -> dict[str, Any]:
    qty = abs(int(account.contracts))
    entry_px = apply_fill_price(entry_mid, side=side, is_entry=True, account=account)
    exit_px = apply_fill_price(exit_mid, side=side, is_entry=False, account=account)
    gross, fee, net = futures_pnl_dollars(
        side=side,
        contracts=qty,
        entry_price=entry_px,
        exit_price=exit_px,
        account=account,
    )
    return {
        "entry_i": int(entry_i),
        "exit_i": int(exit_i),
        "entry_ts": idx[entry_i].to_pydatetime(),
        "exit_ts": idx[exit_i].to_pydatetime(),
        "entry_price": float(entry_px),
        "exit_price": float(exit_px),
        "side": side,
        "exit_type": exit_type,
        "qty": float(qty),
        "pnl_abs": float(net),
        "fee_pct": 0.0,  # filled after equity known
        "pnl_pct": 0.0,
        "gross_pnl_dollars": float(gross),
        "fee_dollars": float(fee),
    }


def _result_from_trades(
    bars: pd.DataFrame,
    trade_rows: list[dict[str, Any]],
    positions: np.ndarray,
    *,
    account: AccountConfig,
    feature_snap: pd.DataFrame | None = None,
) -> ReplayResult:
    """Build dollar equity via futures MTM; enrich blotter with account returns."""
    close = bars["close"].astype(float).to_numpy(dtype=float)
    eq = build_futures_equity(close, trade_rows, account=account)
    eq.index = bars.index

    if trade_rows:
        rows = []
        for t in trade_rows:
            row = dict(t)
            # equity_before ≈ cash at bar before entry
            before_i = max(int(t["entry_i"]) - 1, 0)
            eq_before = float(eq.iloc[before_i])
            fee = float(t.get("fee_dollars") or 0.0)
            net = float(t["pnl_abs"])
            row["pnl_pct"] = net / eq_before if eq_before else 0.0
            row["fee_pct"] = fee / eq_before if eq_before else 0.0
            row["gross_pnl_pct"] = (net + fee) / eq_before if eq_before else 0.0
            rows.append(row)
        trades = pd.DataFrame(rows)
        enriched = enrich_trades(trades, eq, bars_index=bars.index)
        # restore dollar pnl (enrich would overwrite from pnl_pct * equity_before)
        enriched["pnl_abs"] = [float(t["pnl_abs"]) for t in trade_rows]
        enriched["qty"] = [float(t["qty"]) for t in trade_rows]
        metrics = compute_metrics(enriched, eq)
    else:
        enriched = _empty_enriched()
        metrics = compute_metrics(enriched, eq)

    metrics["trades_per_year"] = float(metrics.get("n_trades") or 0) / _years(bars.index)
    metrics["terminal_equity"] = float(eq.iloc[-1])
    metrics["initial_cash"] = float(account.initial_cash)
    metrics["multiplier"] = float(account.instrument.multiplier)
    metrics["instrument"] = account.instrument.symbol
    metrics["contracts"] = int(account.contracts)
    bar_log = _bar_log(bars, positions, eq, feature_snap, account=account)
    return ReplayResult(equity=eq, trades=enriched, metrics=metrics, bar_log=bar_log)


def _bar_log(
    bars: pd.DataFrame,
    positions: np.ndarray,
    equity: pd.Series,
    features: pd.DataFrame | None,
    *,
    account: AccountConfig,
) -> pd.DataFrame:
    peak = equity.cummax()
    log = pd.DataFrame(
        {
            "timestamp": bars.index,
            "open": bars["open"].to_numpy(dtype=float),
            "high": bars["high"].to_numpy(dtype=float),
            "low": bars["low"].to_numpy(dtype=float),
            "close": bars["close"].to_numpy(dtype=float),
            "position_contracts": positions.astype(float),
            "equity": equity.to_numpy(dtype=float),
            "drawdown": (equity / peak - 1.0).to_numpy(dtype=float),
            "instrument": account.instrument.symbol,
            "multiplier": account.instrument.multiplier,
        },
        index=bars.index,
    )
    if features is not None:
        for col in ("z", "pct_rank", "sma_prev", "median_prev", "giveback_prev"):
            if col in features.columns:
                log[f"feature_{col}"] = features[col].to_numpy(dtype=float)
    return log


def _mutex_on(t_tactical: pd.Series | None, i: int) -> bool:
    if t_tactical is None:
        return False
    j = i - 1 if i > 0 else i
    val = t_tactical.iloc[j]
    if pd.isna(val):
        return False
    return bool(val)


def simulate_y1(
    bars: pd.DataFrame,
    cfg: Y1Config | None = None,
    *,
    t_tactical_on: pd.Series | None = None,
    account: AccountConfig | None = None,
) -> ReplayResult:
    """Y1: z-score MR with high/low touch on sma ± z·σ levels."""
    cfg = cfg or Y1Config()
    acct = _account_for(cfg.contracts, account)
    qty = abs(int(acct.contracts))
    close = bars["close"].astype(float)
    opens = bars["open"].to_numpy(dtype=float)
    highs = bars["high"].to_numpy(dtype=float)
    lows = bars["low"].to_numpy(dtype=float)
    idx = bars.index

    mu = sma(close, cfg.n).shift(1)
    sd = rolling_std(close, cfg.n).shift(1)
    long_lvl = (mu - cfg.z_enter * sd).to_numpy(dtype=float)
    short_lvl = (mu + cfg.z_enter * sd).to_numpy(dtype=float)
    exit_lvl = mu.to_numpy(dtype=float)

    feat = build_y_features(bars, z_n=cfg.n)
    positions = np.zeros(len(bars), dtype=float)
    trades: list[dict[str, Any]] = []
    side: str | None = None
    entry_i = -1
    entry_px = 0.0
    hold = 0

    for i in range(len(bars)):
        mutex = _mutex_on(t_tactical_on, i)

        if side is not None:
            hold += 1
            exit_px = None
            exit_type = None
            if mutex:
                exit_px = float(opens[i])
                exit_type = "mutex"
            elif hold >= cfg.max_hold:
                exit_px = float(opens[i])
                exit_type = "max_hold"
            elif side == "long":
                if not np.isnan(exit_lvl[i]) and highs[i] >= exit_lvl[i]:
                    exit_px = (
                        float(opens[i])
                        if opens[i] >= exit_lvl[i]
                        else float(exit_lvl[i])
                    )
                    exit_type = "touch_mean"
            else:
                if not np.isnan(exit_lvl[i]) and lows[i] <= exit_lvl[i]:
                    exit_px = (
                        float(opens[i])
                        if opens[i] <= exit_lvl[i]
                        else float(exit_lvl[i])
                    )
                    exit_type = "touch_mean"

            if exit_px is not None and side is not None:
                trades.append(
                    _make_trade(
                        entry_i=entry_i,
                        exit_i=i,
                        entry_mid=entry_px,
                        exit_mid=exit_px,
                        side=side,  # type: ignore[arg-type]
                        exit_type=str(exit_type),
                        idx=idx,
                        account=acct,
                    )
                )
                side = None
                hold = 0
                positions[i] = 0.0
                continue

            positions[i] = qty if side == "long" else -qty
            continue

        if mutex or np.isnan(long_lvl[i]) or np.isnan(short_lvl[i]):
            continue

        long_px = long_touch_fill(opens[i], lows[i], long_lvl[i])
        short_px = short_touch_fill(opens[i], highs[i], short_lvl[i])
        if long_px is not None and short_px is not None:
            continue
        if long_px is not None:
            side = "long"
            entry_i = i
            entry_px = long_px
            hold = 0
            positions[i] = qty
        elif short_px is not None:
            side = "short"
            entry_i = i
            entry_px = short_px
            hold = 0
            positions[i] = -qty

    if side is not None:
        i = len(bars) - 1
        trades.append(
            _make_trade(
                entry_i=entry_i,
                exit_i=i,
                entry_mid=entry_px,
                exit_mid=float(bars["close"].iloc[i]),
                side=side,  # type: ignore[arg-type]
                exit_type="end_of_data",
                idx=idx,
                account=acct,
            )
        )

    return _result_from_trades(bars, trades, positions, account=acct, feature_snap=feat)


def simulate_y2(
    bars: pd.DataFrame,
    cfg: Y2Config | None = None,
    *,
    t_tactical_on: pd.Series | None = None,
    account: AccountConfig | None = None,
) -> ReplayResult:
    """Y2: percentile band edges with high/low touch on quantile price levels."""
    cfg = cfg or Y2Config()
    acct = _account_for(cfg.contracts, account)
    qty = abs(int(acct.contracts))
    close = bars["close"].astype(float)
    opens = bars["open"].to_numpy(dtype=float)
    highs = bars["high"].to_numpy(dtype=float)
    lows = bars["low"].to_numpy(dtype=float)
    idx = bars.index

    level_lo = rolling_quantile_price(close, cfg.w, cfg.lo).shift(1).to_numpy(dtype=float)
    level_hi = rolling_quantile_price(close, cfg.w, cfg.hi).shift(1).to_numpy(dtype=float)
    level_mid = rolling_quantile_price(close, cfg.w, cfg.mid).shift(1).to_numpy(dtype=float)
    feat = build_y_features(bars, rank_w=cfg.w)
    positions = np.zeros(len(bars), dtype=float)
    trades: list[dict[str, Any]] = []
    side: str | None = None
    entry_i = -1
    entry_px = 0.0
    hold = 0

    for i in range(len(bars)):
        mutex = _mutex_on(t_tactical_on, i)
        if side is not None:
            hold += 1
            exit_px = None
            exit_type = None
            if mutex:
                exit_px, exit_type = float(opens[i]), "mutex"
            elif hold >= cfg.max_hold:
                exit_px, exit_type = float(opens[i]), "max_hold"
            elif side == "long" and not np.isnan(level_mid[i]) and highs[i] >= level_mid[i]:
                exit_px = float(max(opens[i], level_mid[i])) if opens[i] > level_mid[i] else float(level_mid[i])
                if opens[i] >= level_mid[i]:
                    exit_px = float(opens[i])
                exit_type = "touch_mid"
            elif side == "short" and not np.isnan(level_mid[i]) and lows[i] <= level_mid[i]:
                exit_px = float(min(opens[i], level_mid[i]))
                exit_type = "touch_mid"

            if exit_px is not None:
                trades.append(
                    _make_trade(
                        entry_i=entry_i,
                        exit_i=i,
                        entry_mid=entry_px,
                        exit_mid=exit_px,
                        side=side,  # type: ignore[arg-type]
                        exit_type=str(exit_type),
                        idx=idx,
                        account=acct,
                    )
                )
                side = None
                hold = 0
                positions[i] = 0.0
                continue
            positions[i] = qty if side == "long" else -qty
            continue

        if mutex or np.isnan(level_lo[i]) or np.isnan(level_hi[i]):
            continue
        long_px = long_touch_fill(opens[i], lows[i], level_lo[i])
        short_px = short_touch_fill(opens[i], highs[i], level_hi[i])
        if long_px is not None and short_px is not None:
            continue
        if long_px is not None:
            side, entry_i, entry_px, hold = "long", i, long_px, 0
            positions[i] = qty
        elif short_px is not None:
            side, entry_i, entry_px, hold = "short", i, short_px, 0
            positions[i] = -qty

    if side is not None:
        i = len(bars) - 1
        trades.append(
            _make_trade(
                entry_i=entry_i,
                exit_i=i,
                entry_mid=entry_px,
                exit_mid=float(close.iloc[i]),
                side=side,  # type: ignore[arg-type]
                exit_type="end_of_data",
                idx=idx,
                account=acct,
            )
        )

    return _result_from_trades(bars, trades, positions, account=acct, feature_snap=feat)


def simulate_y3(
    bars: pd.DataFrame,
    cfg: Y3Config | None = None,
    *,
    t_tactical_on: pd.Series | None = None,
    account: AccountConfig | None = None,
) -> ReplayResult:
    """Y3: short-biased crush fade — arm on prior close, fill next open; exits via touch."""
    cfg = cfg or Y3Config()
    acct = _account_for(cfg.contracts, account)
    qty = abs(int(acct.contracts))
    close = bars["close"].astype(float)
    opens = bars["open"].to_numpy(dtype=float)
    highs = bars["high"].to_numpy(dtype=float)
    lows = bars["low"].to_numpy(dtype=float)
    idx = bars.index

    feat = build_y_features(bars, rank_w=cfg.rank_w)
    median = feat["median"].shift(1).to_numpy(dtype=float)
    giveback = feat["giveback"].to_numpy(dtype=float)
    pct_rank = feat["pct_rank"].to_numpy(dtype=float)
    mom3 = feat["mom_3"].to_numpy(dtype=float)

    tac = None
    if t_tactical_on is not None:
        tac = t_tactical_on.reindex(bars.index).fillna(False).astype(bool).to_numpy()

    positions = np.zeros(len(bars), dtype=float)
    trades: list[dict[str, Any]] = []
    side: str | None = None
    entry_i = -1
    entry_px = 0.0
    hold = 0
    armed = False

    for i in range(len(bars)):
        mutex = _mutex_on(t_tactical_on, i)

        if i > 0 and side is None and not mutex:
            gb = giveback[i - 1]
            pr = pct_rank[i - 1]
            m3 = mom3[i - 1]
            cond = (
                not np.isnan(gb)
                and not np.isnan(pr)
                and not np.isnan(m3)
                and gb >= cfg.g
                and pr >= cfg.rank_min
                and m3 <= 0.0
            )
            t_exit = False
            if cfg.use_t_exit_arm and tac is not None and i >= 2:
                t_exit = bool(tac[i - 2]) and (not bool(tac[i - 1]))
            if cond or (t_exit and not np.isnan(pr) and pr >= cfg.rank_min and m3 <= 0.0):
                armed = True

        if side is not None:
            hold += 1
            exit_px = None
            exit_type = None
            stop_lvl = entry_px * (1.0 + cfg.g_stop)
            if mutex:
                exit_px, exit_type = float(opens[i]), "mutex"
            elif hold >= cfg.max_hold:
                exit_px, exit_type = float(opens[i]), "max_hold"
            elif highs[i] >= stop_lvl:
                exit_px = float(max(opens[i], stop_lvl)) if opens[i] > stop_lvl else float(stop_lvl)
                if opens[i] >= stop_lvl:
                    exit_px = float(opens[i])
                exit_type = "touch_stop"
            elif not np.isnan(median[i]) and lows[i] <= median[i]:
                exit_px = float(min(opens[i], median[i]))
                exit_type = "touch_median"

            if exit_px is not None:
                trades.append(
                    _make_trade(
                        entry_i=entry_i,
                        exit_i=i,
                        entry_mid=entry_px,
                        exit_mid=exit_px,
                        side="short",
                        exit_type=str(exit_type),
                        idx=idx,
                        account=acct,
                    )
                )
                side = None
                hold = 0
                positions[i] = 0.0
                continue
            positions[i] = -qty
            continue

        if armed and not mutex:
            side = "short"
            entry_i = i
            entry_px = float(opens[i])
            hold = 0
            armed = False
            positions[i] = -qty
        elif mutex:
            armed = False

    if side is not None:
        i = len(bars) - 1
        trades.append(
            _make_trade(
                entry_i=entry_i,
                exit_i=i,
                entry_mid=entry_px,
                exit_mid=float(close.iloc[i]),
                side="short",
                exit_type="end_of_data",
                idx=idx,
                account=acct,
            )
        )

    return _result_from_trades(bars, trades, positions, account=acct, feature_snap=feat)


def y1_grid() -> list[Y1Config]:
    out: list[Y1Config] = []
    for n in (10, 14, 20, 30):
        for z in (1.25, 1.5, 1.75, 2.0, 2.5):
            for H in (5, 7, 10, 15):
                for c in (1, 2):
                    out.append(Y1Config(n=n, z_enter=z, max_hold=H, contracts=c))
    return out


def y2_grid() -> list[Y2Config]:
    out: list[Y2Config] = []
    for w in (40, 60, 90, 120):
        for lo in (0.10, 0.15, 0.20, 0.25):
            for hi in (0.75, 0.80, 0.85):
                for H in (5, 10, 15):
                    for c in (1, 2):
                        out.append(Y2Config(w=w, lo=lo, hi=hi, max_hold=H, contracts=c))
    return out


def y3_grid() -> list[Y3Config]:
    out: list[Y3Config] = []
    for g in (0.10, 0.15, 0.20, 0.25, 0.30):
        for gs in (0.15, 0.20, 0.25, 0.35):
            for H in (5, 10, 15, 20):
                for w in (60, 90, 120):
                    for c in (1, 2):
                        out.append(
                            Y3Config(rank_w=w, g=g, g_stop=gs, max_hold=H, contracts=c)
                        )
    return out


def _metrics_row(
    idea: str,
    params: dict[str, Any],
    res: ReplayResult,
    *,
    min_tpy: float,
    max_tpy: float | None,
    min_equity: float,
) -> dict[str, Any]:
    m = res.metrics
    tpy = float(m.get("trades_per_year") or 0.0)
    initial = float(m.get("initial_cash") or min_equity)
    eq = float(res.equity.iloc[-1]) if len(res.equity) else initial
    freq_ok = tpy >= min_tpy and (max_tpy is None or tpy <= max_tpy)
    return {
        "idea": idea,
        **params,
        "n_trades": int(m.get("n_trades") or 0),
        "trades_per_year": tpy,
        "terminal_equity": eq,
        "total_return": eq / initial - 1.0 if initial else float("nan"),
        "max_drawdown": float(m.get("max_drawdown") or 0.0),
        "sharpe": float(m.get("sharpe") or float("nan")),
        "sharpe_equity": float(m.get("sharpe_equity") or float("nan")),
        "sortino_equity": float(m.get("sortino_equity") or float("nan")),
        "calmar": float(m.get("calmar") or float("nan")),
        "win_rate": float(m.get("win_rate") or float("nan")),
        "profit_factor": float(m.get("profit_factor") or float("nan")),
        "expectancy": float(m.get("expectancy") or float("nan")),
        "avg_hold_days": float(m.get("avg_hold_days") or float("nan")),
        "cagr": float(m.get("cagr") or float("nan")),
        "initial_cash": initial,
        "multiplier": float(m.get("multiplier") or float("nan")),
        "instrument": m.get("instrument"),
        "freq_ok": freq_ok,
        "income_ok": eq > min_equity,
        "pass_a": freq_ok and eq > min_equity,
    }


@dataclass
class YScreenResult:
    """Leaderboard plus top-run artifacts for reporting."""

    leaderboard: pd.DataFrame
    # run_id -> {equity, trades, metrics, params, idea, bar_log}
    runs: dict[str, dict[str, Any]]


def screen_y_isolation(
    bars: pd.DataFrame,
    *,
    account: AccountConfig | None = None,
    min_trades_per_year: float = 0.0,
    max_trades_per_year: float | None = None,
    min_equity: float | None = None,
    keep_top_per_idea: int = 5,
    keep_top_overall: int = 15,
) -> YScreenResult:
    """Pass A isolation screen.

    Default gate is **income only** (terminal equity > initial cash). No upper
    bound on trade count — busy books are allowed.
    """
    acct = account or DEFAULT_ACCOUNT
    gate = float(acct.initial_cash if min_equity is None else min_equity)
    rows: list[dict[str, Any]] = []
    artifacts: dict[str, dict[str, Any]] = {}

    def _keep(run_id: str, idea: str, params: dict[str, Any], res: ReplayResult) -> None:
        artifacts[run_id] = {
            "idea": idea,
            "params": params,
            "equity": res.equity.copy(),
            "trades": res.trades.copy(),
            "metrics": dict(res.metrics),
        }

    run_i = 0
    for c in y1_grid():
        res = simulate_y1(bars, c, account=acct)
        params = {"n": c.n, "z_enter": c.z_enter, "max_hold": c.max_hold, "contracts": c.contracts}
        row = _metrics_row(
            "Y1", params, res,
            min_tpy=min_trades_per_year, max_tpy=max_trades_per_year, min_equity=gate,
        )
        run_id = f"Y1_{run_i}"
        row["run_id"] = run_id
        rows.append(row)
        _keep(run_id, "Y1", params, res)
        run_i += 1

    for c in y2_grid():
        res = simulate_y2(bars, c, account=acct)
        params = {"w": c.w, "lo": c.lo, "hi": c.hi, "max_hold": c.max_hold, "contracts": c.contracts}
        row = _metrics_row(
            "Y2", params, res,
            min_tpy=min_trades_per_year, max_tpy=max_trades_per_year, min_equity=gate,
        )
        run_id = f"Y2_{run_i}"
        row["run_id"] = run_id
        rows.append(row)
        _keep(run_id, "Y2", params, res)
        run_i += 1

    for c in y3_grid():
        res = simulate_y3(bars, c, account=acct)
        params = {
            "rank_w": c.rank_w,
            "g": c.g,
            "g_stop": c.g_stop,
            "max_hold": c.max_hold,
            "contracts": c.contracts,
        }
        row = _metrics_row(
            "Y3", params, res,
            min_tpy=min_trades_per_year, max_tpy=max_trades_per_year, min_equity=gate,
        )
        run_id = f"Y3_{run_i}"
        row["run_id"] = run_id
        rows.append(row)
        _keep(run_id, "Y3", params, res)
        run_i += 1

    board = pd.DataFrame(rows).sort_values(
        ["pass_a", "terminal_equity", "sharpe_equity"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    keep_ids: set[str] = set(board.head(keep_top_overall)["run_id"].tolist())
    for idea, g in board.groupby("idea"):
        keep_ids.update(g.nlargest(keep_top_per_idea, "terminal_equity")["run_id"].tolist())
        keep_ids.update(g.nlargest(2, "sharpe_equity")["run_id"].tolist())
        survivors = g[g["pass_a"]]
        if len(survivors):
            keep_ids.update(survivors.head(5)["run_id"].tolist())

    pruned = {k: v for k, v in artifacts.items() if k in keep_ids}
    return YScreenResult(leaderboard=board, runs=pruned)
