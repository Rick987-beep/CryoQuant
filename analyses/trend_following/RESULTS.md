# Trend-Following Research — Results

**Created:** 2026-06-11  
**Updated:** 2026-06-15 (TD timezone fix + hourly re-ingest)  
**Status:** Phase 1 complete — Phase 2 not started  
**Plan:** [`PLAN.md`](PLAN.md)

---

## Phase 1 — Instruments and Data Ingest

**Completed:** 2026-06-15  
**Outcome:** 34 daily OHLCV + 13 hourly OHLCV + 17 macro series ingested; **0 data errors**

### Summary

| Dataset | Symbols | Source | Coverage | On disk |
|---|---|---|---|---|
| Daily OHLCV | 34 | Yahoo Finance | 2010–2026 | 34 symbols |
| Hourly OHLCV | 13 | Twelve Data | 2020–2026 (6.3 yr) | 13 symbols |
| FRED macro | 16 series | FRED API (`fredapi`) | 2010–2026 (varies) | 16 series |
| CBOE VIX | 1 (4 columns) | CBOE CSV | 2010–2026 | OHLC + close |
| **Total** | | | | **11,072 parquet files, 83 MB** |

### Framework components built

| Component | File |
|---|---|
| FX 24/5 calendar | `cryocore/calendars.py` |
| Instrument registry (40+ symbols) | `cryocore/instruments.py` |
| Yahoo OHLCV source | `cryoquant/data/sources/yahoo.py` |
| Twelve Data OHLCV source | `cryoquant/data/sources/twelvedata.py` |
| CBOE VIX source | `cryoquant/data/sources/cboe.py` |
| FRED macro source (25+ aliases) | `cryoquant/data/sources/fred.py` |
| OHLCV cleaning + audit | `cryoquant/data/cleaning.py` |
| Macro parquet store | `cryoquant/data/macro_store.py` |
| Loader (yahoo + TD routing) | `cryoquant/data/loader.py` |
| Generic ingest orchestrator | `cryoquant/data/ingest.py` |
| Universe manifest | `analyses/trend_following/universe.yaml` |
| Ingest CLI (thin wrapper) | `analyses/trend_following/run_ingest.py` |
| Tests | `test_data_cleaning`, `test_sources_twelvedata`, `test_sources_fred`, `test_ingest` (+ existing suite; **279 passing**) |

API keys stored in `.env` (gitignored); loaded via `python-dotenv` → `cryoquant.config`.

### Daily OHLCV (Yahoo Finance)

| Group | Symbols | Bars | Notes |
|---|---|---|---|
| US index ETFs | SPY, QQQ, DIA, IWM | 4,136 each | From 2010 |
| Sector ETFs | XLK–XLU (9) | 4,136 each | From 2010 |
| Sector ETF | XLRE | 2,685 | Launched Oct 2015 |
| Commodity ETFs | GLD, SLV, USO | 4,136 each | From 2010 |
| Commodity ETF | PDBC | 2,915 | Launched Nov 2014 |
| Commodity futures | GC, SI, CL, BZ, NG, HG, ZC, ZW, ZS | 4,100–4,139 | Front-month continuous |
| Index futures | ES, NQ | 4,139 each | Front-month continuous |
| FX majors | EURUSD, GBPUSD, AUDUSD, JPY=X, CAD=X | 4,285–4,286 | 24/5 spot mid |

**34/34 daily symbols ✅**

### Hourly OHLCV (Twelve Data)

Replaced yfinance hourly (730-day cap, ~2 years) with Twelve Data (back to Feb 2020, ~6.3 years).

| Group | Symbols | Bars | Range |
|---|---|---|---|
| US index ETFs | SPY, QQQ, DIA, IWM | 11,078–11,124 | 2020-02-10 → 2026-06-12 |
| Commodity ETFs | GLD, SLV, USO, PDBC | 11,078–11,103 | 2020-02-10 → 2026-06-12 |
| FX (direct) | EURUSD=X, GBPUSD=X, AUDUSD=X | 37,436–37,520 | 2020-01-29 → 2026-06-15 |
| FX (inverted) | JPY=X, CAD=X | 37,462–37,517 | 2020-01-29 → 2026-06-15 |

**13/13 hourly symbols ✅** — loader routes `yahoo` + `1h` for equity/commodity ETF/FX to Twelve Data automatically.

Sector ETFs and futures are **daily only** (by design in `universe.yaml`).

### Macro series

| Series | Alias | Rows | Freq | Notes |
|---|---|---|---|---|
| Daily eff. fed funds | FEDFUNDS | 6,006 | Daily | Alias → `DFF` (not monthly `FEDFUNDS`) |
| FOMC target upper | FEDFUNDS_UPPER | 6,009 | Daily | `DFEDTARU` |
| FOMC target lower | FEDFUNDS_LOWER | 6,009 | Daily | `DFEDTARL` |
| US 2Y / 10Y / 30Y | US2Y, US10Y, US30Y | 4,290 each | Daily | |
| TIPS 10Y real rate | TIPS10Y | 4,290 | Daily | |
| 10Y breakeven inflation | BREAKEVEN10Y | 4,291 | Daily | |
| SOFR | SOFR | 2,138 | Daily | From Apr 2018 |
| Yield curve 10Y–2Y | YIELD_CURVE | 4,291 | Daily | |
| Yield curve 10Y–3M | YIELD_CURVE_3M | 4,291 | Daily | Fed's preferred recession indicator |
| HY OAS spread | HY_SPREAD | 795 | Daily | ICE BofA — FRED only from Jun 2023 |
| IG OAS spread | IG_SPREAD | 795 | Daily | Same licensing restriction |
| Chicago Fed NFCI | NFCI | 858 | Weekly | Primary long-history credit-stress proxy |
| NFCI credit sub-index | NFCI_CREDIT | 858 | Weekly | |
| Trade-weighted USD | DXY | 4,286 | Daily | |
| CBOE VIX OHLC | VIX | 4,166 | Daily | Close + open/high/low stored separately |

**17/17 macro ingest jobs ✅** (16 FRED + 1 CBOE with 4 columns)

### Key decisions (data sources)

1. **Daily OHLCV → Yahoo Finance.** Free, 2010+ depth, good enough for trend research. ETF proxies preferred over `=F` futures (roll noise).
2. **Hourly OHLCV → Twelve Data free tier.** 6+ years vs yfinance's 730-day cap. ~79 API requests for full initial ingest; ~13/day incremental. Futures hourly skipped — use ETF proxies (GLD, USO).
3. **FRED macro → API key via `fredapi`.** Public CSV endpoint was unreliable (504s). `FEDFUNDS` alias remapped to daily `DFF`. ICE BofA HY/IG spreads only available from Jun 2023 on FRED; `NFCI`/`NFCI_CREDIT` used for 2010+ credit-stress history.
4. **VIX → CBOE CSV.** Full OHLC from 1990; FRED `VIXCLS` is close-only fallback.
5. **FX inverted pairs (JPY=X, CAD=X).** Twelve Data returns standard market quote; prices inverted after fetch to match Yahoo's stored convention.

### Data quality audit

**0 errors** across all ingested data.

#### Daily OHLCV

| Warning | Verdict |
|---|---|
| `GAPS` (~112/symbol, NYSE/CME) | Weekend + holiday gaps — expected |
| `GAPS` (1/symbol, FX) | Isolated holiday gaps — expected |
| `PRICE_SPIKE` (commodities, FX) | Genuine events: WTI negative Apr 2020, nat gas 2022, Brexit GBP 2016 |

#### Hourly OHLCV (post threshold tuning)

Audit thresholds updated in `cleaning.py`:
- `STALE_CLOSE`: FX threshold raised 5 → 8 consecutive bars (off-peak flatlines are normal)
- `PRICE_SPIKE`: `cme_futures` calendar threshold raised 20% → 35% (energy crisis moves)

| Warning | Symbols | Verdict |
|---|---|---|
| `GAPS` | All 13 | Weekend/holiday gaps — expected |
| `PRICE_SPIKE` | USO (3), PDBC (1) | Genuine energy shocks; commodity ETFs now audited at 35% via `asset_class` |
| `STALE_CLOSE` (≥8 bars) | GBPUSD=X, CAD=X | NY2021 holiday flatline — data provider repeated last price for ~14h |

**17 warnings total — all legitimate market events; no data corruption.**

### Post-ingest refactor (2026-06-15)

Hardening pass after initial ingest — no data re-fetched:

| Change | Rationale |
|---|---|
| `cryoquant/data/ingest.py` | Reusable orchestrator; `run_ingest.py` is now a thin CLI wrapper |
| `loader.delete_partitions()` | `--force` clears parquet + sentinel files before re-fetch |
| `Instrument.meta.td_ticker` | Twelve Data FX/ETF mapping lives in registry, not source code |
| `asset_class`-aware `audit_bars` | Commodity ETFs (USO, GLD) use 35% spike threshold on NYSE calendar |
| `calendar.is_open()` in `clean_ohlcv` | FX weekend drop uses calendar logic instead of hardcoded weekday checks |
| TD rate limiter + HTTP error surfacing | Prevents silent partial fetches; respects free-tier 8 req/min |
| Mocked HTTP tests | `test_sources_twelvedata`, `test_sources_fred`, `test_ingest` — no network in CI |
| `macro_store.list_macro()` | Discovers sources from `STORE_ROOT/macro/` subdirs |
| CBOE FRED fallback | Uses `observation_start/end` (not `vintage_date`) |

### Twelve Data timezone fix + hourly re-ingest (2026-06-15)

**Bug:** US ETF hourly bars from Twelve Data arrived in `America/New_York` wall clock but were
stored as UTC without conversion (~4–5 h timestamp shift, DST-dependent). FX hourly was unaffected.

**Fix:** `twelvedata.py` now passes `timezone=UTC` on all API requests; `_utc_timestamp()` helper
converts exchange-local strings when needed (tests).

**Re-ingest:** `run_ingest --ohlcv-only --tf 1h --force` — **13/13 symbols OK**, 0 failed (~8.7 min).

**Verification (parquet vs Yahoo hourly, same UTC timestamp):**

| Symbol | Test timestamp (UTC) | Result |
|---|---|---|
| SPY | 2024-11-06 20:00 (= 3 PM ET) | ✅ close match |
| SPY | 2024-07-15 19:00 (= 3 PM EDT) | ✅ close match |
| GLD | 2024-11-06 20:00 | ✅ close match |
| QQQ | 2024-08-05 19:00 | ✅ close match |
| SPY batch | Nov 4–8 2024 | ✅ 35/35 bars match at same UTC ts |
| EURUSD=X | 2025-01-15 12:00 | ✅ (~2 bp vs Yahoo) |
| JPY=X | 2025-01-15 12:00 | ✅ (inverted convention) |

**Tests:** 281 passing (incl. `test_exchange_local_converted_to_utc`, `test_requests_timezone_utc`).

### Open items (low priority)

| Item | Notes |
|---|---|
| Incremental refresh workflow | Re-run `run_ingest` without `--force` for latest bars |
| QA JSON reports (`data/qa/`) | Per-run JSON not yet implemented |
| `FIN_STRESS` (STLFSI4) | Available in `fred.py` aliases; deferred (similar to NFCI) |
| Daily gap audit threshold | Consider calendar-aware 5-day threshold for equity daily bars |

---

## Phase 2 — Feature Library

*Not started.*

---

## Phase 3A — Tier-A Rule Candidates

*Not started.*

---

## Phase 3B — Tier-B Macro-Filtered Candidates

*Not started.*

---

## Phase 3C — Tier-C ML Candidates

*Not started.*

---

## Phase 4 — Deep Dive on Survivors

*Not started.*
