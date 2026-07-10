# Event calendar — data sources and CryoQuant ingest

**Study phase:** 4  
**Framework modules:** `cryoquant/data/sources/{bls_calendar,earnings_calendar,economic_events,event_schema}.py`  
**Universe:** [`calendar_universe.yaml`](calendar_universe.yaml) (mirrors BTCpredict `macro_events` pattern)

---

## CryoQuant ingest (correct pattern)

Calendar data is **not** study-local parquet. It follows the alt-data connector pattern (§1f in [`docs/how_to_build_a_study.md`](../../docs/how_to_build_a_study.md)):

```
fetch_*  →  macro_store.write_frame  →  macro_store.load_frame
```

### Ingest

```bash
python studies/tudysho_calm_nights/run_ingest_calendar.py
# optional: --force  --dry-run  --start YYYY-MM-DD --end YYYY-MM-DD
```

### macro_store layout

| Source | series_id | Content |
|--------|-----------|---------|
| `fed_calendar` | `FOMC_DECISION_DAYS` | FOMC sparse frame (BTCpredict D14 compatible) |
| `bls_calendar` | `macro_releases` | BLS ICS — CPI, NFP, PPI, JOLTS, … |
| `yahoo_calendar` | `mag7_earnings` | MAG7 quarterly earnings timestamps |
| `economic_events` | `us_scheduled` | **Merged** view for hold-window joins |

On disk: `$CRYOQUANT_STORE_ROOT/macro/<source>/<series_id>/year=YYYY/month=MM.parquet`

Registered in the data catalog (`python -m cryoquant.cli catalog list`).

### Load in any study

```python
from datetime import datetime, timezone
from cryoquant.data.sources.economic_events import load_scheduled_events, ingest_scheduled_events

start = datetime(2025, 1, 1, tzinfo=timezone.utc)
end = datetime(2026, 7, 9, tzinfo=timezone.utc)

# First time or refresh:
ingest_scheduled_events(start.date(), end.date())

# Subsequent runs (disk only):
events = load_scheduled_events(start, end)
```

Study-specific hold-window helper: `src/event_calendar.py` → `events_in_hold_window()`.

Human-readable export (optional): `reports/calendar/events.csv` after ingest.

---

## Data sources (past + future)

### FOMC — `fomc_calendar` (existing)

| | |
|---|---|
| **Module** | `cryoquant.data.sources.fomc_calendar` |
| **History** | 2018–2026+ |
| **Future** | Fed published calendar + HTML refresh |
| **Lag** | `available_utc` = ~2:00 PM ET announcement (scheduled; no outcome lookahead) |

### BLS macro — `bls_calendar`

| | |
|---|---|
| **URL** | `bls.gov/schedule/news_release/bls.ics` |
| **History** | ICS feed currently **2025–2026** |
| **Future** | Same ICS (subscribe for updates) |
| **Caveat** | Requires browser-like `User-Agent`; pre-2025 needs archived BLS pages |

### MAG7 earnings — `earnings_calendar`

| | |
|---|---|
| **Provider** | Yahoo Finance (`yfinance`) |
| **Tickers** | AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA |
| **History** | ~6 years per ticker (free tier) |
| **Future** | Next scheduled dates in same endpoint |

### Alignment note

Scheduled event times use **calendar semantics** (like FOMC D14 in BTCpredict): `available_utc` equals the published release instant. This is **not** lookahead on CPI prints or earnings surprises — only the scheduled clock time.

For bar-level joins with publication lag, use `align_by_available_utc` from `cryoquant.features.align`.

---

## Event tiers (study policy)

| Tier | Types | Policy sketch |
|------|-------|---------------|
| 1 | `fomc`, `cpi`, `nfp` | Hard skip in hold window |
| 2 | `ppi`, `jolts`, `earnings` | Soft MCI penalty |
| 3 | `bls_other` | Diagnostic |

---

## Phase 4 analysis (next)

1. `load_scheduled_events` → join to `session_extrusion_daily`
2. Stratify hold-night extrusion by tier and `release_slot`
3. Interaction: morning quiet × event day → false-calm rate
4. Event-aware MCI walk-forward

---

## Refresh cadence

| Source | When |
|--------|------|
| BLS ICS | Weekly / before analysis |
| FOMC | Quarterly check |
| MAG7 earnings | Weekly in earnings season |
