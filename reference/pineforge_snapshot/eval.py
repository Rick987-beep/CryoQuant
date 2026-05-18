"""Evaluation harness for 3-state trend classifiers.

State convention: +1 uptrend, 0 no_trend, -1 downtrend.

This module computes:
- State-quality metrics (hit rate per state, forward returns, dwell, flip rate).
- A trivial strategy proxy: long during +1, short during -1, flat during 0,
  next-bar open execution, optional ATR-multiple slippage.
- Per-regime breakdown using a forward-looking labeler so we can score the
  worst regime separately from the best.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import ta


# -----------------------------------------------------------------------------
# State-quality metrics
# -----------------------------------------------------------------------------

@dataclass
class StateMetrics:
    state: int
    n_bars: int
    share: float                   # fraction of total bars
    hit_rate_h1: float             # P(forward 1-bar return has correct sign)
    hit_rate_h4: float             # 4-bar horizon
    hit_rate_h24: float            # 24-bar (1d on 1h tf)
    mean_fwd_ret_h24: float
    median_fwd_ret_h24: float
    mfe_atr: float                 # mean MFE per visit, ATR-normalized
    mae_atr: float                 # mean MAE per visit (negative number)
    avg_dwell: float
    n_visits: int


def _runs(state: np.ndarray) -> list[tuple[int, int, int]]:
    """Return [(state_value, start_idx, end_idx_exclusive), ...]"""
    if len(state) == 0:
        return []
    runs = []
    cur = state[0]
    start = 0
    for i in range(1, len(state)):
        if state[i] != cur:
            runs.append((int(cur), start, i))
            cur = state[i]
            start = i
    runs.append((int(cur), start, len(state)))
    return runs


def state_metrics(
    df: pd.DataFrame, state: "pd.Series | pd.DataFrame", *, atr_len: int = 14
) -> dict[int, StateMetrics]:
    """Per-state quality metrics."""
    from .trend import as_state_series
    state = as_state_series(state)
    s = state.to_numpy()
    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    atr = ta.atr(df["high"], df["low"], df["close"], atr_len).to_numpy()

    fwd_ret = {h: pd.Series(close).pct_change(h).shift(-h).to_numpy() for h in (1, 4, 24)}

    out: dict[int, StateMetrics] = {}
    runs = _runs(s)

    for st in (1, 0, -1):
        mask = s == st
        n = int(mask.sum())
        if n == 0:
            out[st] = StateMetrics(st, 0, 0.0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, 0.0, 0)
            continue

        def _hit(h):
            r = fwd_ret[h][mask]
            r = r[~np.isnan(r)]
            if len(r) == 0:
                return np.nan
            if st == 0:
                # for no_trend, "hit" = small magnitude move (within 0.25 ATR / close)
                # Use a simpler proxy: fraction with |r| < median|r| of trend states
                return float(np.mean(np.abs(r) < np.nanmedian(np.abs(fwd_ret[h]))))
            return float(np.mean(np.sign(r) == st))

        # MFE / MAE per visit, ATR-normalized at entry
        mfes, maes, dwells = [], [], []
        for st_run, a, b in runs:
            if st_run != st:
                continue
            seg_high = high[a:b]
            seg_low = low[a:b]
            entry_close = close[a]
            entry_atr = atr[a] if not np.isnan(atr[a]) else np.nan
            if entry_atr is None or np.isnan(entry_atr) or entry_atr == 0:
                continue
            if st == 1:
                mfe = (np.max(seg_high) - entry_close) / entry_atr
                mae = (np.min(seg_low) - entry_close) / entry_atr
            elif st == -1:
                mfe = (entry_close - np.min(seg_low)) / entry_atr
                # for shorts, MAE is the worst (highest) high above entry; report as negative
                mae = (entry_close - np.max(seg_high)) / entry_atr
            else:
                mfe = (np.max(seg_high) - entry_close) / entry_atr
                mae = (np.min(seg_low) - entry_close) / entry_atr
            mfes.append(mfe)
            maes.append(mae)
            dwells.append(b - a)

        n_visits = len(dwells)
        avg_dwell = float(np.mean(dwells)) if dwells else 0.0
        r24 = fwd_ret[24][mask]
        r24 = r24[~np.isnan(r24)]
        out[st] = StateMetrics(
            state=st,
            n_bars=n,
            share=n / len(s),
            hit_rate_h1=_hit(1),
            hit_rate_h4=_hit(4),
            hit_rate_h24=_hit(24),
            mean_fwd_ret_h24=float(np.mean(r24)) if len(r24) else np.nan,
            median_fwd_ret_h24=float(np.median(r24)) if len(r24) else np.nan,
            mfe_atr=float(np.mean(mfes)) if mfes else np.nan,
            mae_atr=float(np.mean(maes)) if maes else np.nan,
            avg_dwell=avg_dwell,
            n_visits=n_visits,
        )
    return out


def flip_rate(state: "pd.Series | pd.DataFrame") -> float:
    """Mean number of state flips per day (assuming UTC DatetimeIndex)."""
    from .trend import as_state_series
    state = as_state_series(state)
    s = state.to_numpy()
    if len(s) < 2:
        return 0.0
    flips = int(np.sum(s[1:] != s[:-1]))
    span = (state.index[-1] - state.index[0]).total_seconds() / 86400.0
    return flips / span if span > 0 else 0.0


# -----------------------------------------------------------------------------
# Strategy proxy: long +1 / flat 0 / short -1 with next-bar-open execution
# -----------------------------------------------------------------------------

@dataclass
class StrategyResult:
    equity: pd.Series           # cumulative product, starts at 1.0
    bar_returns: pd.Series      # per-bar strategy return
    n_trades: int
    win_rate: float
    sharpe: float               # annualized (assuming bar interval inferred)
    max_drawdown: float
    cagr: float


def strategy_proxy(
    df: pd.DataFrame,
    state: "pd.Series | pd.DataFrame",
    *,
    cost_bps: float = 2.0,      # round-trip cost per state change (basis points)
) -> StrategyResult:
    """Simple long/flat/short on next-bar open."""
    from .trend import as_state_series
    state = as_state_series(state)
    close = df["close"].to_numpy(dtype=float)
    open_ = df["open"].to_numpy(dtype=float)
    s = state.to_numpy()

    # Position from bar i+1 open through bar i+1 close uses the state visible at bar i.
    # Therefore on bar i+1 we hold pos = state[i] from open[i+1] to close[i+1].
    pos = np.zeros(len(df), dtype=float)
    pos[1:] = s[:-1]

    # Per-bar return: pos * (close[i] / open[i] - 1) on bar i (assuming we entered at open[i])
    # If pos was the same on bar i-1 (held overnight) we instead get close[i]/close[i-1] - 1.
    # For simplicity, use close-to-close returns gated by yesterday's state. This is the
    # standard "signal at bar i, return on bar i+1 close-to-close" backtest convention.
    cc = np.zeros(len(df))
    cc[1:] = close[1:] / close[:-1] - 1.0
    # state held from bar i to i+1 is s[i]; return realized on bar i+1.
    held = np.zeros(len(df))
    held[1:] = s[:-1]
    raw_ret = held * cc

    # Costs: charge cost_bps each time the held position changes.
    pos_change = np.zeros(len(df))
    pos_change[1:] = np.abs(held[1:] - held[:-1])
    cost = (cost_bps / 10000.0) * pos_change
    bar_ret = raw_ret - cost

    bar_ret_s = pd.Series(bar_ret, index=df.index)
    equity = (1.0 + bar_ret_s).cumprod()

    # Trade-level stats: a trade = a non-zero position run.
    runs = _runs(held.astype(np.int8))
    trade_returns = []
    for st_run, a, b in runs:
        if st_run == 0:
            continue
        # cumulative return over the run
        seg = bar_ret[a:b]
        trade_returns.append(float(np.prod(1 + seg) - 1))

    n_trades = len(trade_returns)
    win_rate = float(np.mean([r > 0 for r in trade_returns])) if trade_returns else np.nan

    # Sharpe (annualized). Infer bars per year from index spacing.
    if len(df) > 1:
        dt = (df.index[-1] - df.index[0]).total_seconds() / max(len(df) - 1, 1)
        bars_per_year = (365.25 * 86400.0) / dt
    else:
        bars_per_year = 0.0
    rstd = float(bar_ret_s.std(ddof=0))
    sharpe = (
        float(bar_ret_s.mean()) / rstd * np.sqrt(bars_per_year)
        if rstd > 0 and bars_per_year > 0
        else np.nan
    )

    # Max drawdown
    peak = equity.cummax()
    dd = equity / peak - 1.0
    max_dd = float(dd.min())

    # CAGR
    if len(df) > 1 and equity.iloc[-1] > 0:
        years = (df.index[-1] - df.index[0]).total_seconds() / (365.25 * 86400.0)
        cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else np.nan
    else:
        cagr = np.nan

    return StrategyResult(
        equity=equity,
        bar_returns=bar_ret_s,
        n_trades=n_trades,
        win_rate=win_rate,
        sharpe=sharpe,
        max_drawdown=max_dd,
        cagr=cagr,
    )


# -----------------------------------------------------------------------------
# Per-regime breakdown
# -----------------------------------------------------------------------------

def label_regimes(df: pd.DataFrame, *, win_days: int = 90, k_atr: float = 0.5) -> pd.Series:
    """Forward-looking regime labels using a centered smoothed return.

    For each bar, look at the close `win_days` ahead vs `win_days` behind.
    If forward 90d return > k * (90d-ATR-budget): bull. < -k: bear. Else: range.
    Returns int Series in {-1, 0, +1}.
    """
    bars_per_day = int(round(86400.0 / ((df.index[1] - df.index[0]).total_seconds())))
    win = win_days * bars_per_day
    close = df["close"]
    fwd = close.shift(-win) / close - 1.0
    atr = ta.atr(df["high"], df["low"], df["close"], 14)
    atr_pct = (atr / close).rolling(win).mean()
    threshold = k_atr * atr_pct * np.sqrt(win)
    label = np.where(fwd > threshold, 1, np.where(fwd < -threshold, -1, 0))
    return pd.Series(label, index=df.index, dtype="int8")


# -----------------------------------------------------------------------------
# Episode-level statistics — directional edge test
# -----------------------------------------------------------------------------

@dataclass
class EpisodeStats:
    """Per-candidate episode statistics for the directional edge test."""
    n_ep: int
    win_rate: float          # fraction of episodes with positive net return
    payoff_ratio: float      # mean_win / mean_abs_loss
    expectancy: float        # p * mean_win - (1-p) * mean_abs_loss  (per episode)
    edge_tstat: float        # one-sample t on episode net returns (H0: mean=0)
    sig: bool                # True if t > 1.645 AND n_ep >= 34


def compute_episodes(
    df: pd.DataFrame,
    state: "pd.Series | pd.DataFrame",
    *,
    cost_bps: float = 2.0,
) -> pd.DataFrame:
    """One row per completed trend episode with net return after costs.

    Columns: direction (+1/-1), n_bars, net_return, win (bool).

    Uses the same cost-accounting and bar-return convention as
    strategy_proxy: signal at bar i → return realised on bar i+1 close.
    """
    from .trend import as_state_series
    state = as_state_series(state)
    strat = strategy_proxy(df, state, cost_bps=cost_bps)
    bar_ret = strat.bar_returns.to_numpy()

    # Held position at bar i = state[i-1] (same as strategy_proxy)
    s = state.to_numpy()
    held = np.zeros(len(s), dtype=np.int8)
    held[1:] = s[:-1]

    episodes = []
    for st_run, a, b in _runs(held):
        if st_run == 0:
            continue
        seg = bar_ret[a:b]
        net_ret = float(np.prod(1.0 + seg) - 1.0)
        episodes.append({
            "direction": int(st_run),
            "n_bars": b - a,
            "net_return": net_ret,
            "win": net_ret > 0,
        })

    cols = ["direction", "n_bars", "net_return", "win"]
    return pd.DataFrame(episodes, columns=cols) if episodes else pd.DataFrame(columns=cols)


def episode_stats(episodes: pd.DataFrame) -> EpisodeStats:
    """Aggregate EpisodeStats from the output of compute_episodes()."""
    _nan = float("nan")
    n = len(episodes)
    if n == 0:
        return EpisodeStats(
            n_ep=0, win_rate=_nan, payoff_ratio=_nan,
            expectancy=_nan, edge_tstat=_nan, sig=False,
        )

    rets = episodes["net_return"].to_numpy(dtype=float)
    wins_mask = rets > 0
    wins = rets[wins_mask]
    losses = rets[~wins_mask]

    p = float(wins_mask.mean())
    mean_win = float(wins.mean()) if len(wins) > 0 else 0.0
    mean_loss_abs = float(np.abs(losses).mean()) if len(losses) > 0 else _nan

    payoff_ratio = (
        mean_win / mean_loss_abs
        if len(losses) > 0 and not np.isnan(mean_loss_abs) and mean_loss_abs > 0
        else _nan
    )

    l_abs = mean_loss_abs if not np.isnan(mean_loss_abs) else 0.0
    expectancy = p * mean_win - (1.0 - p) * l_abs

    mean_ret = float(rets.mean())
    std_ret = float(rets.std(ddof=1)) if n > 1 else _nan
    tstat = (
        mean_ret / (std_ret / np.sqrt(n))
        if not np.isnan(std_ret) and std_ret > 0
        else _nan
    )

    sig = (not np.isnan(tstat)) and (tstat > 1.645) and (n >= 34)

    return EpisodeStats(
        n_ep=n,
        win_rate=p,
        payoff_ratio=payoff_ratio,
        expectancy=expectancy,
        edge_tstat=tstat,
        sig=sig,
    )


# -----------------------------------------------------------------------------
# Per-regime breakdown
# -----------------------------------------------------------------------------

def per_regime_metrics(
    df: pd.DataFrame, state: "pd.Series | pd.DataFrame", regimes: pd.Series
) -> dict[int, StrategyResult]:
    """Per-regime strategy metrics.

    We compute bar-returns once on the full series (so close-to-close
    transitions are correct), then mask by regime to avoid creating
    artificial price jumps when slicing.
    """
    from .trend import as_state_series
    state = as_state_series(state)
    full = strategy_proxy(df, state, cost_bps=2.0)
    out: dict[int, StrategyResult] = {}
    for r in (1, 0, -1):
        mask = (regimes == r).to_numpy()
        if mask.sum() < 50:
            out[r] = None  # type: ignore[assignment]
            continue
        bar_ret = full.bar_returns[mask]
        equity = (1.0 + bar_ret).cumprod()
        # trade-level: count trades whose entry bar falls in this regime
        held = np.zeros(len(df), dtype=np.int8)
        held[1:] = state.to_numpy()[:-1]
        runs = _runs(held)
        trade_returns = []
        for st_run, a, b in runs:
            if st_run == 0:
                continue
            if not mask[a]:
                continue
            seg = full.bar_returns.to_numpy()[a:b]
            trade_returns.append(float(np.prod(1 + seg) - 1))
        n_trades = len(trade_returns)
        win_rate = (
            float(np.mean([t > 0 for t in trade_returns])) if trade_returns else np.nan
        )
        rstd = float(bar_ret.std(ddof=0))
        if len(df) > 1:
            dt = (df.index[-1] - df.index[0]).total_seconds() / max(len(df) - 1, 1)
            bars_per_year = (365.25 * 86400.0) / dt
        else:
            bars_per_year = 0.0
        sharpe = (
            float(bar_ret.mean()) / rstd * np.sqrt(bars_per_year)
            if rstd > 0 and bars_per_year > 0 else np.nan
        )
        peak = equity.cummax()
        dd = equity / peak - 1.0
        max_dd = float(dd.min()) if len(dd) else np.nan
        # CAGR on the spanned wall-clock time of the masked bars
        masked_idx = df.index[mask]
        years = (masked_idx[-1] - masked_idx[0]).total_seconds() / (365.25 * 86400.0) if len(masked_idx) > 1 else np.nan
        cagr = (
            float(equity.iloc[-1] ** (1.0 / years) - 1.0)
            if years and years > 0 and equity.iloc[-1] > 0 else np.nan
        )
        out[r] = StrategyResult(
            equity=equity, bar_returns=bar_ret,
            n_trades=n_trades, win_rate=win_rate,
            sharpe=sharpe, max_drawdown=max_dd, cagr=cagr,
        )
    return out


# -----------------------------------------------------------------------------
# Burst / flip-only + fixed-hold eval
# -----------------------------------------------------------------------------

def _burst_held(classified: pd.DataFrame, hold_bars: int) -> np.ndarray:
    """Build the position array for flip-only fixed-hold evaluation.

    On each flip_up / flip_down event at bar i the position is set to
    +1 / -1 for bars i+1 … i+hold_bars (next-bar-open execution).
    New flip signals arriving while a hold is active are ignored — the hold
    runs to completion before the next entry is considered.
    """
    flip_up = classified["flip_up"].to_numpy()
    flip_down = classified["flip_down"].to_numpy()
    n = len(flip_up)
    held = np.zeros(n, dtype=np.int8)
    i = 0
    while i < n:
        if flip_up[i] or flip_down[i]:
            direction = np.int8(1) if flip_up[i] else np.int8(-1)
            entry = i + 1
            exit_bar = min(i + 1 + hold_bars, n)
            held[entry:exit_bar] = direction
            i = exit_bar          # skip past hold — no re-entry during hold
        else:
            i += 1
    return held


def strategy_proxy_burst(
    df: pd.DataFrame,
    classified: pd.DataFrame,
    *,
    hold_bars: int = 8,
    cost_bps: float = 2.0,
) -> StrategyResult:
    """Flip-only + fixed-hold strategy proxy.

    Enters long / short on flip_up / flip_down events and holds for exactly
    ``hold_bars`` bars, then exits flat.  New flips during an active hold are
    ignored (i.e. this is *not* a continuous trend-follower).  Round-trip cost
    is charged at each position change.

    This eval model is designed for momentum-burst indicators where the edge
    is concentrated in the first few bars after the flip and continuous
    position-holding would add noise/cost.
    """
    held = _burst_held(classified, hold_bars)
    close = df["close"].to_numpy(dtype=float)
    n = len(df)

    cc = np.zeros(n, dtype=float)
    cc[1:] = close[1:] / close[:-1] - 1.0
    raw_ret = held.astype(float) * cc

    pos_change = np.zeros(n, dtype=float)
    pos_change[1:] = np.abs(held[1:].astype(float) - held[:-1].astype(float))
    cost = (cost_bps / 10_000.0) * pos_change
    bar_ret = raw_ret - cost

    bar_ret_s = pd.Series(bar_ret, index=df.index)
    equity = (1.0 + bar_ret_s).cumprod()

    runs_list = _runs(held)
    trade_returns = []
    for st_run, a, b in runs_list:
        if st_run == 0:
            continue
        seg = bar_ret[a:b]
        trade_returns.append(float(np.prod(1.0 + seg) - 1.0))

    n_trades = len(trade_returns)
    win_rate = float(np.mean([r > 0 for r in trade_returns])) if trade_returns else np.nan

    if len(df) > 1:
        dt = (df.index[-1] - df.index[0]).total_seconds() / max(len(df) - 1, 1)
        bars_per_year = (365.25 * 86400.0) / dt
    else:
        bars_per_year = 0.0
    rstd = float(bar_ret_s.std(ddof=0))
    sharpe = (
        float(bar_ret_s.mean()) / rstd * np.sqrt(bars_per_year)
        if rstd > 0 and bars_per_year > 0 else np.nan
    )

    peak = equity.cummax()
    dd = equity / peak - 1.0
    max_dd = float(dd.min())

    if len(df) > 1 and equity.iloc[-1] > 0:
        years = (df.index[-1] - df.index[0]).total_seconds() / (365.25 * 86400.0)
        cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else np.nan
    else:
        cagr = np.nan

    return StrategyResult(
        equity=equity,
        bar_returns=bar_ret_s,
        n_trades=n_trades,
        win_rate=win_rate,
        sharpe=sharpe,
        max_drawdown=max_dd,
        cagr=cagr,
    )


def compute_episodes_burst(
    df: pd.DataFrame,
    classified: pd.DataFrame,
    *,
    hold_bars: int = 8,
    cost_bps: float = 2.0,
) -> pd.DataFrame:
    """One row per fixed-hold trade with net return after costs.

    Uses the same cost and return convention as ``compute_episodes`` but
    derives entries from flip events rather than continuous state runs.
    Columns: direction (+1/-1), n_bars, net_return, win (bool).
    """
    strat = strategy_proxy_burst(df, classified, hold_bars=hold_bars, cost_bps=cost_bps)
    bar_ret = strat.bar_returns.to_numpy()
    held = _burst_held(classified, hold_bars)

    episodes = []
    for st_run, a, b in _runs(held):
        if st_run == 0:
            continue
        seg = bar_ret[a:b]
        net_ret = float(np.prod(1.0 + seg) - 1.0)
        episodes.append({
            "direction": int(st_run),
            "n_bars": b - a,
            "net_return": net_ret,
            "win": net_ret > 0,
        })

    cols = ["direction", "n_bars", "net_return", "win"]
    return pd.DataFrame(episodes, columns=cols) if episodes else pd.DataFrame(columns=cols)

