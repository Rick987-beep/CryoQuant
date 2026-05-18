"""Plotly HTML report for a trend candidate run."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from . import eval as ev


_STATE_COLOR = {1: "rgba(46, 204, 113, 0.20)", -1: "rgba(231, 76, 60, 0.20)", 0: "rgba(0,0,0,0)"}
_STATE_LABEL = {1: "uptrend", 0: "no_trend", -1: "downtrend"}


def _state_shapes(state: pd.Series) -> list[dict]:
    """Build background rectangles spanning the full plot height (paper y)."""
    s = state.to_numpy()
    idx = state.index
    shapes = []
    i = 0
    while i < len(s):
        st = int(s[i])
        j = i
        while j < len(s) and s[j] == st:
            j += 1
        if st != 0:
            shapes.append(dict(
                type="rect", xref="x", yref="y domain",
                x0=idx[i], x1=idx[j - 1], y0=0, y1=1,
                fillcolor=_STATE_COLOR[st], line=dict(width=0), layer="below",
            ))
        i = j
    return shapes


def build_report(
    df: pd.DataFrame,
    state: "pd.Series | pd.DataFrame",
    *,
    candidate_name: str,
    params: dict,
    timeframe: str,
    out_path: str | Path,
) -> Path:
    """Generate a self-contained HTML report."""
    from .trend import as_state_series
    state = as_state_series(state)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # ---------- compute all metrics ----------
    sm = ev.state_metrics(df, state)
    flips_per_day = ev.flip_rate(state)
    strat = ev.strategy_proxy(df, state, cost_bps=2.0)
    episodes = ev.compute_episodes(df, state, cost_bps=2.0)
    ep_stats = ev.episode_stats(episodes)
    regimes = ev.label_regimes(df)
    per_reg = ev.per_regime_metrics(df, state, regimes)

    # ---------- figure 1: candle + state shading + EMA ----------
    fig_main = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3],
        vertical_spacing=0.05,
        subplot_titles=("Price + state shading", "Equity"),
    )
    # price as line (cheaper than candles for many bars)
    fig_main.add_trace(
        go.Scatter(x=df.index, y=df["close"], name="close", line=dict(color="#222", width=1)),
        row=1, col=1,
    )
    fig_main.update_yaxes(type="log", row=1, col=1, autorange=True)
    fig_main.update_layout(shapes=_state_shapes(state))

    # equity curves
    fig_main.add_trace(
        go.Scatter(x=strat.equity.index, y=strat.equity.values, name=f"strategy",
                   line=dict(color="#2980b9", width=1.5)),
        row=2, col=1,
    )
    fig_main.update_yaxes(type="log", row=2, col=1, autorange=True)
    fig_main.update_layout(
        height=720, hovermode="x unified",
        margin=dict(l=40, r=20, t=40, b=20),
        legend=dict(orientation="h", y=1.05),
    )

    # ---------- figure 2: forward-return distributions per state ----------
    close = df["close"].to_numpy()
    fwd24 = pd.Series(close).pct_change(24).shift(-24).to_numpy()
    fig_dist = go.Figure()
    for st, color in [(1, "#27ae60"), (-1, "#c0392b"), (0, "#7f8c8d")]:
        mask = (state.to_numpy() == st) & ~np.isnan(fwd24)
        if mask.sum() == 0:
            continue
        fig_dist.add_trace(go.Histogram(
            x=fwd24[mask], name=f"{_STATE_LABEL[st]} (n={int(mask.sum())})",
            marker_color=color, opacity=0.55, nbinsx=80,
        ))
    fig_dist.add_vline(x=0, line=dict(color="black", width=1, dash="dash"))
    fig_dist.update_layout(
        barmode="overlay", height=380, title="24-bar forward return per state",
        xaxis_title="forward return", margin=dict(l=40, r=20, t=40, b=40),
    )

    # ---------- HTML assembly ----------
    def _f(x, n=4):
        return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{n}f}"

    state_rows = ""
    for st in (1, 0, -1):
        m = sm[st]
        state_rows += (
            f"<tr><td>{_STATE_LABEL[st]}</td>"
            f"<td>{m.n_bars:,}</td><td>{m.share*100:.1f}%</td>"
            f"<td>{_f(m.hit_rate_h1)}</td><td>{_f(m.hit_rate_h4)}</td><td>{_f(m.hit_rate_h24)}</td>"
            f"<td>{_f(m.mean_fwd_ret_h24)}</td><td>{_f(m.median_fwd_ret_h24)}</td>"
            f"<td>{_f(m.mfe_atr,2)}</td><td>{_f(m.mae_atr,2)}</td>"
            f"<td>{m.n_visits}</td><td>{m.avg_dwell:.1f}</td></tr>"
        )

    def _strat_block(title: str, r: ev.StrategyResult | None) -> str:
        if r is None:
            return f"<tr><td>{title}</td><td colspan=5>(insufficient bars)</td></tr>"
        return (
            f"<tr><td>{title}</td>"
            f"<td>{_f(r.cagr)}</td><td>{_f(r.sharpe,2)}</td>"
            f"<td>{_f(r.max_drawdown)}</td><td>{_f(r.win_rate)}</td>"
            f"<td>{r.n_trades}</td></tr>"
        )

    regime_rows = ""
    for r, label in [(1, "bull"), (0, "range"), (-1, "bear")]:
        regime_rows += _strat_block(label, per_reg.get(r))

    overall_rows = (
        _strat_block(f"{candidate_name}", strat)
    )

    # robustness = min sharpe across non-empty regimes
    sharpes = [r.sharpe for r in per_reg.values() if r is not None and not np.isnan(r.sharpe)]
    robustness = min(sharpes) if sharpes else float("nan")

    params_rows = "".join(
        f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in params.items()
    )

    # episode stats row
    def _ep(x, fmt=".3f"):
        return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else format(x, fmt)

    sig_badge = (
        '<span style="color:#27ae60;font-weight:600">★ significant (t&gt;1.645, n≥34)</span>'
        if ep_stats.sig
        else '<span style="color:#c0392b">? inconclusive</span>'
    )
    ep_row = (
        f"<tr><td>episodes (n)</td><td>{ep_stats.n_ep}</td></tr>"
        f"<tr><td>win rate</td><td>{_ep(ep_stats.win_rate, '.1%')}</td></tr>"
        f"<tr><td>payoff ratio (R)</td><td>{_ep(ep_stats.payoff_ratio, '.2f')}</td></tr>"
        f"<tr><td>expectancy / episode</td><td>{_ep(ep_stats.expectancy, '.2%')}</td></tr>"
        f"<tr><td>edge t-stat</td><td>{_ep(ep_stats.edge_tstat, '.2f')}</td></tr>"
        f"<tr><td>edge verdict</td><td>{sig_badge}</td></tr>"
    )

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"/>
<title>{candidate_name} — {timeframe}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 24px; max-width: 1280px; color:#222; }}
  h1 {{ font-size: 22px; margin: 0 0 6px 0; }}
  h2 {{ font-size: 16px; margin: 24px 0 8px 0; color:#444; }}
  table {{ border-collapse: collapse; font-size: 13px; }}
  th, td {{ padding: 4px 10px; border-bottom: 1px solid #eee; text-align: right; }}
  th {{ background: #fafafa; text-align: left; }}
  td:first-child, th:first-child {{ text-align: left; }}
  .meta {{ color: #666; font-size: 13px; margin-bottom: 12px; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
  .robust {{ font-size: 14px; padding: 6px 10px; background:#f4f6f8; border-left: 3px solid #2980b9; margin: 12px 0; }}
</style>
</head><body>
<h1>{candidate_name}</h1>
<div class="meta">
  Timeframe: <b>{timeframe}</b> ·
  Bars: <b>{len(df):,}</b> ·
  Range: <b>{df.index[0].date()} → {df.index[-1].date()}</b> ·
  Flip rate: <b>{flips_per_day:.2f}/day</b>
</div>
<div class="robust">
  Robustness score (worst-regime Sharpe): <b>{_f(robustness, 2)}</b>
</div>

<h2>Parameters</h2>
<table>{params_rows}</table>

<h2>Edge test — episode-level statistics</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
{ep_row}
</table>

<h2>Strategy proxy — overall</h2>
<table>
<tr><th></th><th>CAGR</th><th>Sharpe</th><th>MaxDD</th><th>Win rate</th><th>Trades</th></tr>
{overall_rows}
</table>

<h2>Strategy proxy — per regime</h2>
<table>
<tr><th>Regime</th><th>CAGR</th><th>Sharpe</th><th>MaxDD</th><th>Win rate</th><th>Trades</th></tr>
{regime_rows}
</table>

<h2>State quality</h2>
<table>
<tr><th>state</th><th>bars</th><th>share</th>
    <th>hit h1</th><th>hit h4</th><th>hit h24</th>
    <th>mean fwd24</th><th>median fwd24</th>
    <th>MFE/ATR</th><th>MAE/ATR</th>
    <th>visits</th><th>avg dwell</th></tr>
{state_rows}
</table>

<h2>Price + state + equity</h2>
{fig_main.to_html(include_plotlyjs="cdn", full_html=False, default_height="720px")}

<h2>Forward-return distributions</h2>
{fig_dist.to_html(include_plotlyjs=False, full_html=False, default_height="380px")}

</body></html>"""
    out_path.write_text(html)
    return out_path
