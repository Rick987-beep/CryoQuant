---
name: VIXStrategy
status: active
path: A
isProject: true
overview: >
  Dual-overlay VIX study on daily CBOE OHLC. Dollar Mini-VIX (VXM) account
  scoreboard; Overlay Y isolation done; Overlay T + compose next.
todos:
  - id: scaffold
    content: "Create studies/VIXStrategy tree"
    status: completed
  - id: phase0-data
    content: "Ingest + QA CBOE VIX OHLC; study parquet"
    status: completed
  - id: phase1-overlay-y
    content: "Overlay Y isolation (Y1/Y2/Y3) on $100k VXM account"
    status: completed
  - id: phase1-spike-catalog
    content: "Fear / spike episode catalog for Overlay T evaluation"
    status: pending
  - id: phase1-overlay-t
    content: "Overlay T floor + tactical rules; compose T+Y with mutex"
    status: pending
  - id: hypothesis-proxy
    content: "Lock tradable proxy vs cash-VIX signal semantics"
    status: pending
  - id: report
    content: "Keep RESULTS.md + HTML report current with each re-run"
    status: completed
---

# VIXStrategy — Plan

## Status

| Phase | Status | Notes |
|-------|--------|-------|
| 0 — Data | ✅ | Ingest through **2026-09-18**; research **2016-09-19 → 2026-09-18** (2,547 bars) |
| 1a — Spike catalog | ⏳ | Fear-leg catalog for Overlay T evaluation |
| 1b — Overlay Y | ✅ | Dollar VXM screen (928); best Y2 **$171.8k**, Y1 **$162.7k**, Y3 **$123.9k** |
| 1c — Overlay T + compose | ⏳ | Floor + tactical; mutex with Y |
| Report | ✅ | HTML + [`RESULTS.md`](RESULTS.md) refreshed 2026-09-20 |

### Study defaults (do not change unless asked)

- **Window:** exact trailing **10 calendar years**, end = **yesterday UTC**
  (`config.yaml` → `window.mode: trailing_years`, `years: 10`)
- **Account:** `$100,000` · **VXM** Mini VIX · **`$100/point`** · integer contracts (grid: 1–2)
- **Execution hooks:** `fee_per_side` / `spread_ticks` / `slippage_ticks` (currently 0)
- **Scoreboard:** cash equity marked with futures variation margin — not unit NAV

### Overlay Y Pass A (2026-09-20)

- Framework: [`cryoquant.backtest.account`](../../cryoquant/backtest/account.py) + touch fills in [`replay`](../../cryoquant/backtest/replay.py)
- Study: [`src/overlay_y.py`](src/overlay_y.py) · [`run_phase1_overlay_y.py`](run_phase1_overlay_y.py)
- Artifacts: `reports/overlay_y_isolation_report.html`, leaderboard parquet/json, [`RESULTS.md`](RESULTS.md)

**Economics note:** Old unit-NAV `weight=1` ≈ **~50 VXM** at VIX 20 on $100k. Y1/Y2 “wipeouts” under that model were leverage, not a different signal. At 1–2 contracts, Y1/Y2 survive spikes and lead the dollar leaderboard.

```bash
.venv/bin/python studies/VIXStrategy/run_phase0_data.py
.venv/bin/python studies/VIXStrategy/run_phase1_overlay_y.py
.venv/bin/pytest studies/VIXStrategy/tests/ tests/test_backtest_replay.py -q
```

## Data

- **Source:** CBOE public CSV (`cryoquant.data.sources.cboe.fetch_vix`)
- **Storage:** `data/macro/cboe/VIX_{OPEN,HIGH,LOW,CLOSE}/`
- **Study artifact:** `data/vix_daily_ohlc.parquet` (research window only)
- **QA notes:** 2010+ OHLC integrity is clean; pre-2007 opens can be bad — ingest from 2010.

## Research questions

1. Can Overlay Y (mean-reversion income) fund Overlay T (spike catcher) on a realistic VXM lot?
2. Should VIX be the **traded asset** (VXM/VX) or a **regime gate** for another book?
3. How do rare jump days dominate PnL — and should policy size/skip them?
4. What contract sizing (fixed vs % equity) makes Pass A rankings meaningful?

## Non-goals (for now)

- Intraday VIX / VX microstructure
- Full options surface modelling
- Promoting study-local helpers to `cryoquant/` until a second study needs them

## Next

1. Fear / spike episode catalog (1a)
2. Overlay T rules + T+Y mutex compose (1c)
3. Optional: risk-matched contract sizing for fairer Y1/Y2 vs Y3 comparison
