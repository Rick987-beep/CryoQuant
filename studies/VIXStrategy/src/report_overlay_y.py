"""HTML report for Overlay Y isolation screen (CryoBacktester-inspired)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from cryoquant.reporting.html_brand import escape_html as _e
from cryoquant.reporting.html_brand import fig_to_b64
from cryoquant.reporting.html_brand import html_document
from cryoquant.reporting.html_brand import style_axes

from src.overlay_y import YScreenResult

BRAND = "cryo-dark"


def _fmt(v: Any, digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and (v != v)):
        return "—"
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}"
    if isinstance(v, (float, np.floating)):
        return f"{float(v):,.{digits}f}"
    return _e(v)


def _pct(v: float, digits: int = 1) -> str:
    if v != v:
        return "—"
    return f"{100.0 * v:.{digits}f}%"


def _fmt_money(v: Any, digits: int = 0) -> str:
    if v is None or (isinstance(v, float) and (v != v)):
        return "—"
    try:
        return f"${float(v):,.{digits}f}"
    except (TypeError, ValueError):
        return _e(v)


def _params_str(params: dict[str, Any]) -> str:
    return ", ".join(f"{k}={_fmt(v, 3)}" for k, v in params.items() if v == v)


def _plot_equity_fan(
    runs: dict[str, dict[str, Any]],
    run_ids: list[str],
    *,
    title: str,
    initial_cash: float,
) -> str:
    from agent_commons.charts import set_style

    pal = set_style(BRAND)
    fig, ax = plt.subplots(figsize=(11, 4.5))
    fig.patch.set_facecolor(pal.get("bg", "#070d18"))
    ax.set_facecolor(pal.get("panel", "#0f1a2b"))
    accent = pal.get("accent", "#58a6ff")
    colors = [accent, pal.get("drawdown", "#ff5c6c"), "#7ee787", "#d2a8ff", "#ffa657"]
    for i, rid in enumerate(run_ids[:5]):
        run = runs.get(rid)
        if not run:
            continue
        eq = run["equity"]
        label = f"{run['idea']} {_params_str(run['params'])}"
        ax.plot(eq.index, eq.values, linewidth=1.6, color=colors[i % len(colors)], label=label[:60])
    ax.axhline(initial_cash, color=pal.get("muted", "#8fa3bc"), linewidth=0.8, linestyle=":")
    style_axes(ax, title, ylabel="Account equity ($)")
    ax.legend(
        fontsize=7,
        loc="upper left",
        frameon=True,
        facecolor=pal.get("panel", "#0f1a2b"),
        edgecolor=pal.get("grid", "#1e2d45"),
        labelcolor=pal.get("text", "#edf2f9"),
    )
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig_to_b64(fig, brand=BRAND)


def _plot_single_equity(equity: pd.Series, *, title: str, initial_cash: float) -> str:
    from agent_commons.charts import set_style

    pal = set_style(BRAND)
    fig, ax = plt.subplots(figsize=(11, 3.8))
    fig.patch.set_facecolor(pal.get("bg", "#070d18"))
    ax.set_facecolor(pal.get("panel", "#0f1a2b"))
    ax.plot(equity.index, equity.values, color=pal.get("accent", "#58a6ff"), linewidth=1.8)
    ax.fill_between(
        equity.index, initial_cash, equity.values, alpha=0.15, color=pal.get("accent", "#58a6ff")
    )
    ax.axhline(initial_cash, color=pal.get("muted", "#8fa3bc"), linewidth=0.8, linestyle=":")
    style_axes(ax, title, ylabel="Account equity ($)")
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig_to_b64(fig, brand=BRAND)


def _trade_summary(trades: pd.DataFrame) -> dict[str, Any]:
    if trades is None or trades.empty:
        return {
            "n": 0,
            "win_rate": float("nan"),
            "avg_pnl": float("nan"),
            "avg_win": float("nan"),
            "avg_loss": float("nan"),
            "by_side": {},
            "by_exit": {},
        }
    pnl = trades["pnl_pct"].astype(float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    by_side = {}
    if "side" in trades.columns:
        for side, g in trades.groupby("side"):
            by_side[str(side)] = {
                "n": int(len(g)),
                "avg_pnl": float(g["pnl_pct"].mean()),
                "win_rate": float((g["pnl_pct"] > 0).mean()),
            }
    by_exit = {}
    if "exit_type" in trades.columns:
        by_exit = trades["exit_type"].value_counts().astype(int).to_dict()
    return {
        "n": int(len(trades)),
        "win_rate": float((pnl > 0).mean()),
        "avg_pnl": float(pnl.mean()),
        "avg_win": float(wins.mean()) if len(wins) else float("nan"),
        "avg_loss": float(losses.mean()) if len(losses) else float("nan"),
        "by_side": by_side,
        "by_exit": by_exit,
    }


def _trades_table(trades: pd.DataFrame, *, limit: int = 40) -> str:
    if trades is None or trades.empty:
        return "<p class='muted'>No trades.</p>"
    cols = [c for c in (
        "entry_ts", "exit_ts", "side", "qty", "entry_price", "exit_price",
        "pnl_abs", "pnl_pct", "duration_days", "exit_type",
    ) if c in trades.columns]
    show = trades[cols].head(limit)
    # also last trades if long
    tail_note = ""
    if len(trades) > limit:
        show = pd.concat([trades[cols].head(limit // 2), trades[cols].tail(limit // 2)])
        tail_note = f"<p class='muted'>Showing first/last {limit // 2} of {len(trades)} trades.</p>"

    th = "".join(f"<th>{_e(c)}</th>" for c in cols)
    rows = []
    for _, r in show.iterrows():
        tds = []
        for c in cols:
            v = r[c]
            if c in ("entry_ts", "exit_ts"):
                tds.append(f"<td>{_e(str(pd.Timestamp(v).date()))}</td>")
            elif c in ("entry_price", "exit_price"):
                tds.append(f"<td>{_fmt(float(v), 2)}</td>")
            elif c == "pnl_abs":
                cls = "pos" if float(v) > 0 else ("neg" if float(v) < 0 else "")
                tds.append(f"<td class='{cls}'>{_fmt_money(float(v), 0)}</td>")
            elif c == "pnl_pct":
                cls = "pos" if float(v) > 0 else ("neg" if float(v) < 0 else "")
                tds.append(f"<td class='{cls}'>{_pct(float(v), 2)}</td>")
            elif c == "duration_days":
                tds.append(f"<td>{_fmt(float(v), 1)}</td>")
            elif c == "qty":
                tds.append(f"<td>{_fmt(float(v), 0)}</td>")
            else:
                tds.append(f"<td>{_e(v)}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return tail_note + f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _leaderboard_table(board: pd.DataFrame, *, n: int = 40) -> str:
    cols = [
        "idea", "terminal_equity", "total_return", "sharpe_equity", "max_drawdown", "n_trades",
        "trades_per_year", "win_rate", "profit_factor", "cagr", "pass_a",
        "n", "z_enter", "w", "lo", "hi", "rank_w", "g", "g_stop", "max_hold", "contracts",
    ]
    cols = [c for c in cols if c in board.columns]
    show = board.head(n)
    th = "".join(f"<th>{_e(c)}</th>" for c in cols)
    rows = []
    for _, r in show.iterrows():
        tds = []
        for c in cols:
            v = r[c]
            if c == "terminal_equity":
                tds.append(f"<td><strong>{_fmt_money(v, 0)}</strong></td>")
            elif c in ("max_drawdown", "win_rate", "cagr", "total_return"):
                tds.append(f"<td>{_pct(float(v) if v == v else float('nan'), 1)}</td>")
            elif c == "pass_a":
                tds.append(f"<td>{'✓' if v else '—'}</td>")
            elif isinstance(v, float):
                tds.append(f"<td>{_fmt(v, 3)}</td>")
            else:
                tds.append(f"<td>{_e(v) if v == v else '—'}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return f"<table class='lb'><thead><tr>{th}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _best_run_id(board: pd.DataFrame, idea: str, *, min_equity: float) -> str | None:
    g = board[board["idea"] == idea]
    if g.empty:
        return None
    pos = g[g["terminal_equity"] > min_equity]
    pool = pos if len(pos) else g
    pool = pool.sort_values(
        ["terminal_equity", "sharpe_equity"], ascending=[False, False]
    )
    return str(pool.iloc[0]["run_id"])

def render_overlay_y_report(
    screen: YScreenResult,
    *,
    window_start: str,
    window_end: str,
    n_bars: int,
    out_path: Path,
) -> Path:
    board = screen.leaderboard
    runs = screen.runs
    initial_cash = float(board["initial_cash"].iloc[0]) if "initial_cash" in board.columns and len(board) else 100_000.0
    n_pass = int(board["pass_a"].sum()) if "pass_a" in board.columns else 0
    n_income = int(board["income_ok"].sum())
    n_freq = int(board["freq_ok"].sum())

    best_overall_id = str(board.iloc[0]["run_id"]) if len(board) else None
    best_ids = {
        "overall": best_overall_id,
        "Y1": _best_run_id(board, "Y1", min_equity=initial_cash),
        "Y2": _best_run_id(board, "Y2", min_equity=initial_cash),
        "Y3": _best_run_id(board, "Y3", min_equity=initial_cash),
    }

    fan_ids = [rid for rid in (best_ids["Y1"], best_ids["Y2"], best_ids["Y3"]) if rid]
    # add next-best overall if not already included
    for rid in board.head(5)["run_id"]:
        if rid not in fan_ids:
            fan_ids.append(str(rid))
        if len(fan_ids) >= 5:
            break

    fan_img = (
        _plot_equity_fan(runs, fan_ids, title="Top equity curves by idea", initial_cash=initial_cash)
        if fan_ids else ""
    )

    idea_cards = []
    for idea in ("Y1", "Y2", "Y3"):
        g = board[board["idea"] == idea]
        if g.empty:
            continue
        top = g.sort_values("terminal_equity", ascending=False).iloc[0]
        idea_cards.append(
            f"<div class='card'><h3>{_e(idea)}</h3>"
            f"<div class='stat'><strong>{_fmt_money(top.terminal_equity, 0)}</strong><span>best equity</span></div>"
            f"<div class='stat'><strong>{_fmt(top.trades_per_year, 1)}</strong><span>trades/yr</span></div>"
            f"<div class='stat'><strong>{_pct(float(top.max_drawdown), 1)}</strong><span>max DD</span></div>"
            f"<p class='muted'>{_e(_params_str({k: top[k] for k in top.index if k in ('n','z_enter','w','lo','hi','rank_w','g','g_stop','max_hold','contracts') and top[k]==top[k]}))}</p>"
            f"</div>"
        )

    detail_sections = []
    for label, rid in (
        ("Best overall", best_ids["overall"]),
        ("Best Y1 (z-score MR)", best_ids["Y1"]),
        ("Best Y2 (percentile)", best_ids["Y2"]),
        ("Best Y3 (crush fade)", best_ids["Y3"]),
    ):
        if not rid or rid not in runs:
            continue
        run = runs[rid]
        ts = _trade_summary(run["trades"])
        eq_img = _plot_single_equity(
            run["equity"],
            title=f"{label}: {run['idea']} — {_params_str(run['params'])}",
            initial_cash=initial_cash,
        )
        m = run["metrics"]
        side_rows = "".join(
            f"<tr><td>{_e(s)}</td><td>{d['n']}</td><td>{_pct(d['win_rate'])}</td>"
            f"<td>{_pct(d['avg_pnl'], 2)}</td></tr>"
            for s, d in ts["by_side"].items()
        )
        exit_rows = "".join(
            f"<tr><td>{_e(k)}</td><td>{v}</td></tr>" for k, v in ts["by_exit"].items()
        )
        detail_sections.append(f"""
<section class="detail">
  <h2>{_e(label)}</h2>
  <p class="meta">run_id={_e(rid)} · {_e(_params_str(run['params']))}</p>
  <div class="stats">
    <div><strong>{_fmt_money(float(run['equity'].iloc[-1]), 0)}</strong><span>terminal equity</span></div>
    <div><strong>{_fmt(m.get('sharpe_equity'), 2)}</strong><span>equity Sharpe</span></div>
    <div><strong>{_pct(float(m.get('max_drawdown') or 0))}</strong><span>max drawdown</span></div>
    <div><strong>{_fmt(m.get('n_trades'), 0)}</strong><span>trades</span></div>
    <div><strong>{_fmt(m.get('trades_per_year'), 1)}</strong><span>trades / year</span></div>
    <div><strong>{_pct(float(m.get('win_rate') or float('nan')) if m.get('win_rate')==m.get('win_rate') else float('nan'))}</strong><span>win rate</span></div>
    <div><strong>{_fmt(m.get('profit_factor'), 2)}</strong><span>profit factor</span></div>
    <div><strong>{_fmt(m.get('avg_hold_days'), 1)}</strong><span>avg hold days</span></div>
  </div>
  <figure><img src="data:image/png;base64,{eq_img}" alt="equity"/></figure>
  <div class="two-col">
    <div>
      <h3>Trade mix by side</h3>
      <table><thead><tr><th>side</th><th>n</th><th>win%</th><th>avg pnl</th></tr></thead>
      <tbody>{side_rows or '<tr><td colspan="4">—</td></tr>'}</tbody></table>
    </div>
    <div>
      <h3>Exits by reason</h3>
      <table><thead><tr><th>exit_type</th><th>n</th></tr></thead>
      <tbody>{exit_rows or '<tr><td colspan="2">—</td></tr>'}</tbody></table>
    </div>
  </div>
  <h3>Trade log (sample)</h3>
  {_trades_table(run['trades'], limit=40)}
</section>
""")

    extra_css = """
* { box-sizing: border-box; }
body {
  max-width: 1100px;
  margin: 0 auto;
  padding: 28px 20px 64px;
  font-family: var(--font-sans, "Inter", system-ui, sans-serif);
  background: var(--color-bg, #070d18);
  color: var(--color-text, #edf2f9);
  line-height: 1.55;
}
h1 { font-size: 1.55rem; margin: 0 0 6px; color: var(--color-text, #edf2f9); }
h2 {
  margin-top: 36px;
  color: var(--color-accent, #3b9eff);
  border-bottom: 1px solid var(--color-grid, #1e2d45);
  padding-bottom: 6px;
}
h3 { color: var(--color-text, #edf2f9); margin: 0 0 8px; }
.meta, .muted { color: var(--color-muted, #8fa3bc); font-size: 0.92rem; }
.stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin: 14px 0 18px;
}
.stats > div, .card .stat {
  background: var(--color-panel, #0f1a2b);
  border: 1px solid var(--color-grid, #1e2d45);
  padding: 10px 12px;
  border-radius: 8px;
  color: var(--color-text, #edf2f9);
}
.stats strong, .card .stat strong {
  display: block;
  font-size: 1.2rem;
  color: var(--color-accent, #3b9eff);
}
.stats span, .card .stat span {
  font-size: 0.78rem;
  color: var(--color-muted, #8fa3bc);
}
.cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 16px 0; }
.card {
  background: var(--color-panel, #0f1a2b);
  border: 1px solid var(--color-grid, #1e2d45);
  padding: 14px;
  border-radius: 8px;
  color: var(--color-text, #edf2f9);
}
.callout {
  border-left: 3px solid var(--color-accent, #3b9eff);
  padding: 10px 14px;
  background: var(--color-panel, #0f1a2b);
  border: 1px solid var(--color-grid, #1e2d45);
  border-left-width: 3px;
  margin: 12px 0 20px;
  color: var(--color-text, #edf2f9);
}
.callout strong { color: var(--color-gold, #c9a84c); }
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
  margin: 8px 0 16px;
  color: var(--color-text, #edf2f9);
}
th, td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--color-grid, #1e2d45);
}
th { color: var(--color-muted, #8fa3bc); font-weight: 600; }
td { color: var(--color-text, #edf2f9); }
td.pos { color: #7ee787; }
td.neg { color: #ff7b72; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
figure { margin: 12px 0; }
figure img {
  width: 100%;
  height: auto;
  border-radius: 6px;
  border: 1px solid var(--color-grid, #1e2d45);
}
.lb { font-size: 0.75rem; }
@media (max-width: 800px) {
  .stats, .cards, .two-col { grid-template-columns: 1fr 1fr; }
}
"""

    body = f"""
<header>
  <h1>VIXStrategy — Overlay Y isolation</h1>
  <p class="meta">Cash VIX · finer grid · { _e(window_start) } → { _e(window_end) } · {n_bars:,} bars ·
  generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</header>

<section>
  <h2>Summary</h2>
  <div class="stats">
    <div><strong>{len(board):,}</strong><span>candidates</span></div>
    <div><strong>{n_pass}</strong><span>Pass A (equity&gt;start)</span></div>
    <div><strong>{n_income}</strong><span>income_ok</span></div>
    <div><strong>{_fmt(board['trades_per_year'].max() if len(board) else 0, 1)}</strong><span>max trades/yr</span></div>
  </div>
  <div class="callout">
    Scoreboard: <strong>{_fmt_money(initial_cash, 0)}</strong> cash account marked on
    <strong>Mini VIX (VXM)</strong> futures at <strong>$100/point</strong> (standard VX is $1,000).
    Position size = integer contracts. Execution fees / bid-ask / slippage hook into
    <code>ExecutionModel</code> (currently frictionless mid). Pass A = terminal equity &gt; start;
    <strong>no upper cap on trade count</strong>.
  </div>
  <div class="cards">{''.join(idea_cards)}</div>
</section>

<section>
  <h2>Equity fan — top runs</h2>
  <figure><img src="data:image/png;base64,{fan_img}" alt="equity fan"/></figure>
</section>

<section>
  <h2>Leaderboard (top 40)</h2>
  {_leaderboard_table(board, n=40)}
</section>

{''.join(detail_sections)}
"""

    html = html_document(
        title="VIXStrategy Overlay Y — isolation report",
        body=body,
        brand=BRAND,
        extra_head=f"<style>{extra_css}</style>",
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
