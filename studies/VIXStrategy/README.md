# VIXStrategy

Dual-overlay VIX study on **daily CBOE VIX OHLC**, scored on a **$100k Mini VIX
(VXM)** account. Path A first; Path B if we sweep.

```bash
cd /Users/ulrikdeichsel/CryoQuant && source .venv/bin/activate
python studies/VIXStrategy/run_phase0_data.py          # refresh CBOE OHLC + QA parquet
python studies/VIXStrategy/run_ingest_vx_front.py      # VX front → shared macro_store
python studies/VIXStrategy/run_phase1_overlay_y.py      # Overlay Y Pass A screen + HTML
python -m pytest studies/VIXStrategy/tests/ tests/test_cboe_vx_futures.py -q
```

| Doc | Role |
|-----|------|
| [`PLAN.md`](PLAN.md) | Phases, defaults, status (source of truth) |
| [`KICKOFF.md`](KICKOFF.md) | Purpose, decisions, open questions |
| [`config.yaml`](config.yaml) | Window, account, instrument |
| [`RESULTS.md`](RESULTS.md) | Latest screen numbers |
| [`reports/overlay_y_isolation_report.html`](reports/overlay_y_isolation_report.html) | HTML report |

**Primary series:** `cboe:VIX` via `src.vix_data.load_vix_ohlc`.

**Shared futures:** `cboe:VX_FRONT` in `universe.yaml` → `macro_store` frame
`cboe/VX_FRONT` plus scalars `VX_FRONT_{OPEN,HIGH,LOW,CLOSE,SETTLE,VOLUME}`
(any study can list the same symbol). Raw CDN CSVs cache under
`macro/cboe/_raw/vx/`; use `--force` only to re-download.

**Default research window (locked):** exact trailing **10 calendar years** ending
**yesterday UTC** (`window.mode: trailing_years`). Do not change unless asked.

**Account:** `$100k` · **VXM** `$100/pt` · integer contracts · execution hooks ready
(`fee_per_side`, `spread_ticks`, `slippage_ticks`).

**Overlay Y:** Y1 z-score / Y2 percentile / Y3 crush-fade with OHLC touch fills.
See PLAN and the HTML report.
