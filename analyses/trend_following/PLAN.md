# Trend-Following Strategy Research — Plan

**Created:** 2026-06-11  
**Updated:** 2026-06-15  
**Status:** Phase 1 complete — Phase 2 (feature library) next  
**Audience:** AI agents and quant developers running this analysis in CryoQuant  

---

## Objective

Research a **trend-following strategy** across a diversified multi-asset universe (US equities,
indices, major FX pairs, gold, common commodities) that meets the following operating constraints:

- **Trade frequency:** ≥ 5 trades per month (liquidity, keeps the strategy "alive")
- **Trade intensity cap:** ≤ 3 trades per day (prevents over-trading / execution noise)
- **Timeframes:** all welcome — intraday to weekly bars
- **Direction:** long and/or short, to be determined by research
- **Evaluation:** DSR > 0.95 before any strategy is considered credible

### Approach

Run the standard CryoQuant pipeline end-to-end:

`data → features → labels → models → signals → backtest`

**Framework extensions are encouraged** when they add reusable capability to CryoQuant
(`cryoquant/`, `cryocore/`). This exercise is also a good forcing function for gaps the
repo already has (multi-asset OHLCV ingest, macro series, calendars). The discipline is
not *whether* to extend the framework, but *what belongs there* vs what stays in this
analysis folder.

### Scope — framework extension vs analysis-local

Use this rubric before adding code:

| Question | → Framework | → Analysis-local |
|---|---|---|
| Would a **different** analysis (asset class, hypothesis) reuse it? | Yes | No |
| Is it venue-agnostic (Symbol, loader, primitives, calendars)? | Yes | No |
| Is it tied to **this** candidate list, parameter grid, or ranking weights? | No | Yes |
| Is it orchestration glue for one research sweep? | No | Yes |

**Default workflow:** prototype in `analyses/trend_following/` → promote to `cryoquant/` or
`cryocore/` once the API is stable, covered by tests in `tests/`, and not entangled with
experiment-specific choices. Do not block research on framework polish; do not leave
general-purpose fetchers or primitives permanently buried in an analysis dir.

#### Belongs in the framework (extend when needed)

| Gap | Likely home | Trigger to promote |
|---|---|---|
| yfinance OHLCV ingest (ETFs, futures, FX, indices) | `cryoquant.data.sources.yahoo` + `loader` venue map | Part of Phase 1 framework work |
| OHLCV normalize / clean / QA | `cryoquant.data.cleaning` | Reusable across all multi-asset analyses |
| Macro series store | extend `sources.fred` + `macro_store.py` | Partitioned parquet + catalog row per series |
| CBOE VIX CSV | `cryoquant.data.sources.cboe` | One-off fetcher, catalog-backed |
| Multi-asset trading calendars (FX 24/5, equity RTH, crypto 24/7) | `cryocore.calendars` or `cryoquant.features.calendar_features` | Needed for correct bar alignment across universe |
| Missing trend primitives (Donchian, channel breakouts, …) | `cryoquant.features.primitives` | General technical primitive, not one signal recipe |
| Portfolio-level trade-frequency governor | `cryoquant.backtest` | Reusable across multi-instrument sweeps |
| Credible signal after Phase 3 | `cryoquant.signals` + `scripts/` | DSR > 0.95 and multi-instrument robustness |

#### Stays in this analysis (do not generalise prematurely)

| Item | Location | Why |
|---|---|---|
| Universe ticker lists, train/holdout splits | `PLAN.md`, `candidates.py` | Experiment design |
| Signal candidate factories and parameter grids | `candidates.py` | Hypothesis-specific |
| Phase orchestration (sweep, rank, report) | `backtest.py`, `run_*.py` | One research workflow |
| Cached parquet for this run | `data/` via `STORE_ROOT` + DuckDB catalog | Shared across analyses; gitignored |
| Findings and DSR tables | `RESULTS.md` | Research output |

---

## Phase 1 — Instruments and Historic Data Sources

**Status: ✅ Complete (2026-06-15).** Full ingest results, audit findings, and data-source
decisions are in [`RESULTS.md`](RESULTS.md) §Phase 1. The sections below document the
original design; the implemented stack matches §1.2 and the integration map at the end.

### 1.1 Target Universe

The universe is organised into five asset classes. For each we list the preferred
**tradeable proxy** (liquid, available on mainstream APIs), the **yfinance ticker**, and
alternative sources.

#### US Equity Indices

| Instrument | yfinance ticker | Notes |
|---|---|---|
| S&P 500 | `^GSPC` (index) / `SPY` (ETF) | ETF preferred for OHLCV with volume |
| Nasdaq-100 | `^NDX` / `QQQ` | |
| Dow Jones IA | `^DJI` / `DIA` | |
| Russell 2000 | `^RUT` / `IWM` | Small-cap; independent trend character |
| S&P 500 mini futures | `ES=F` | Higher volume than ETF for intraday |
| Nasdaq-100 mini futures | `NQ=F` | |

#### US Sector ETFs (sub-universe for stock-selection sub-strategies)

| Sector | Ticker |
|---|---|
| Technology | `XLK` |
| Energy | `XLE` |
| Financials | `XLF` |
| Materials | `XLB` |
| Industrials | `XLI` |
| Consumer Discretionary | `XLY` |
| Consumer Staples | `XLP` |
| Healthcare | `XLV` |
| Utilities | `XLU` |
| Real Estate | `XLRE` |

Rationale: sector rotation is a well-documented trend-following edge; relative strength
across sectors is a robust feature.

#### Gold & Precious Metals

| Instrument | yfinance ticker | Notes |
|---|---|---|
| Gold (continuous futures) | `GC=F` | Primary price discovery venue |
| Gold ETF | `GLD` | Adjusted, easy ingest; preferred for daily bars |
| Silver (continuous futures) | `SI=F` | Correlated but independent character |
| Silver ETF | `SLV` | |

#### Common Commodities

| Instrument | yfinance ticker | Notes |
|---|---|---|
| Crude Oil WTI (cont.) | `CL=F` | Most liquid commodity |
| Brent Crude (cont.) | `BZ=F` | |
| Natural Gas (cont.) | `NG=F` | High volatility, trend-friendly |
| Copper (cont.) | `HG=F` | "Dr. Copper" — macro proxy |
| Corn (cont.) | `ZC=F` | Agricultural; seasonality matters |
| Wheat (cont.) | `ZW=F` | |
| Soybeans (cont.) | `ZS=F` | |
| Crude Oil ETF | `USO` | Dividend/roll-adjusted, simpler to use |
| Diversified Commodity ETF | `PDBC` | Broad exposure without roll management |

#### Major FX Pairs (G10)

Five liquid majors — enough breadth for cross-pair robustness without bloating the initial
sweep. Covers the largest share of spot FX turnover and a mix of macro drivers (rates,
risk sentiment, commodities).

| Pair | yfinance ticker | Notes |
|---|---|---|
| EUR/USD | `EURUSD=X` | Largest pair; slow macro trends (ECB vs Fed) |
| USD/JPY | `JPY=X` | yfinance quotes USD per JPY; strong trends around BoJ/Fed policy |
| GBP/USD | `GBPUSD=X` | Higher vol than EUR; independent from euro bloc |
| AUD/USD | `AUDUSD=X` | Risk-on proxy; China/commodity sensitivity |
| USD/CAD | `CAD=X` | yfinance quotes USD per CAD; oil-linked, North America macro |

Rationale: these five are the most liquid G10 crosses after NZD/USD and USD/CHF. NZD and CHF
are omitted from the **initial** narrow universe to keep the first sweep at ~6–8 instruments
total (see §Open Questions #5); add `NZDUSD=X` and `CHF=X` in the robustness expansion pass
if a survivor generalises across the other majors.

FX caveats for backtesting:
- yfinance FX is spot mid/close — no spread or swap; treat results as upper bound on net P&L
- Pairs trade **24/5** (Sun 17:00 ET → Fri 17:00 ET); align bar timestamps to UTC and
  exclude weekend bars when computing returns on daily+ timeframes
- `JPY=X` and `CAD=X` are inverted vs the table label (USD per unit of foreign); normalise
  to a consistent quote convention in `cleaning.normalize_ohlcv` if combining with directly quoted pairs

### 1.2 Data Sources — Evaluation and Recommended Stack

*Updated 2026-06-15 after Phase 1 ingest and API testing with real keys.*

#### Summary verdict (current)

| Role | Source | Pay? | Status |
|---|---|---|---|
| **Primary OHLCV daily** | Yahoo Finance (`yfinance`) | No | ✅ Ingested (2010+) |
| **Primary OHLCV hourly** | Twelve Data (free tier, 800 req/day) | No | ✅ Ingested (2020+) |
| **Macro / regime filters** | FRED API key (`fredapi`) | No | ✅ Ingested (15 series) |
| **VIX OHLC** | CBOE direct CSV | No | ✅ Ingested |
| **Optional cross-check** | Frankfurter (FX daily) | No | — |
| **Skip** | IBKR, TradingView scrapers, Barchart, Quandl | — | — |

> API keys in `.env` (gitignored). Load via `python-dotenv` → `cryoquant.config`. See `.env.example` for required vars.

**Ingest results:** see [`RESULTS.md`](RESULTS.md) §Phase 1.

#### Hourly data depth comparison (2026-06-15 test results)

| Source | ETF 1h from | FX 1h from | Cost | Req/day | Notes |
|---|---|---|---|---|---|
| **yfinance** | ~Jun 2024 (730d cap) | ~Jun 2024 | Free | Unlimited | Hard server-side cap; no pagination past 730d |
| **Twelve Data** | **2020-02-10** | **2020-01-30** | Free | 800 | **3.2× more history**; 5,000 bars/page; `1day` and `1h` |

**Twelve Data free tier is the clear winner for 1h OHLCV.** 6+ years of hourly data vs 2 years from yfinance. Budget: initial full ingest ~79 requests (~10% of daily quota); daily incremental ~17 requests.

**Request budget for full 1h ingest (Twelve Data, 2020 → present):**

| Group | Symbols | Bars/symbol | Pages needed | Requests |
|---|---|---|---|---|
| US index ETFs | SPY, QQQ, DIA, IWM | ~11,000 | 3 | 12 |
| Commodity ETFs | GLD, SLV, USO, PDBC | ~11,000 | 3 | 12 |
| FX majors (24/5) | EURUSD, GBPUSD, AUDUSD, USDJPY, USDCAD | ~54,000 | 11 | 55 |
| **Total initial** | | | | **~79 req** |
| **Daily incremental** | all 13 symbols | latest page | 1 per sym | **13 req/day** |

#### Coverage — final data stack

| Asset class | Primary symbols | Daily source | Daily depth | Hourly source | Hourly depth |
|---|---|---|---|---|---|
| US index ETFs | SPY, QQQ, DIA, IWM | yfinance | 2010+ (16yr) | **Twelve Data** | **2020+ (6yr)** |
| Sector ETFs | XLK–XLRE | yfinance | 2010+ (XLRE: 2015+) | *skip (daily only)* | — |
| Gold / silver ETF | GLD, SLV | yfinance | 2010+ | **Twelve Data** | **2020+** |
| Commodity ETFs | USO, PDBC | yfinance | 2010+/2014+ | **Twelve Data** | **2020+** |
| FX majors | EURUSD, GBPUSD, AUDUSD | yfinance | 2010+ | **Twelve Data** | **2020+** |
| FX inverted | JPY=X, CAD=X | yfinance | 2010+ | **Twelve Data** | **2020+** |
| Commodity futures | GC, SI, CL, BZ, NG, HG, ZC, ZW, ZS | yfinance | 2010+ | *skip* | Roll noise; ETF proxy preferred |
| Index futures | ES, NQ | yfinance | 2010+ | *skip* | Use ETF for intraday |
| VIX | CBOE | CBOE CSV | 1990+ | — | — |
| Macro (yields, spreads, DXY) | FRED series | FRED API | 2010+ | — | Not OHLCV |

**Practical rule:** backtest on **SPY, GLD, USO, PDBC + sector ETFs + FX majors** for daily sweeps; use **Twelve Data for all 1h backtests**. Reserve `=F` futures for exploration with roll caveats.

---

#### Option-by-option assessment

##### A. Yahoo Finance + `yfinance` — primary OHLCV (free)

| | |
|---|---|
| **Protocol** | Unofficial Python wrapper scraping Yahoo web endpoints — not a licensed API |
| **Coverage** | US stocks, ETFs, indices, continuous futures (`=F`), FX — matches our universe |
| **History** | Daily: 10–20+ years (ETFs). 1h: ~2 years. Sub-hourly: ~60 days only |
| **Format** | Pandas-ready OHLCV via `yf.download()` |
| **Cost** | Free |

**Good for:** fast prototyping, multi-asset daily trend sweeps, Phase 1 ingest. CryoQuant's
own docs note yfinance is "convenient but flaky" — accurate for 2024–2026.

**Bad for:** production systems, high-volume automated refresh, sub-hourly backtests,
trusting continuous-futures rolls (`=F`) without ETF cross-check.

**Known issues:** intermittent 401/429 rate limits, cookie/crumb breakage, corporate-action
glitches, no SLA. Yahoo has disabled third-party API redistribution of quotes; personal
research use is fine.

```python
import yfinance as yf
df = yf.download("GLD", start="2010-01-01", interval="1d", auto_adjust=True)
```

**Verdict:** Use as **primary**. Prefer **ETF proxies** (SPY, GLD, USO, PDBC) over `=F`
continuous futures for backtesting.

##### B. FRED — macro / regime features (free, official)

| | |
|---|---|
| **Protocol** | Official REST API; `fredapi` already in CryoQuant (`cryoquant.data.sources.fred`) |
| **Coverage** | Yields, CPI, credit spreads, oil/gold reference — no OHLCV |
| **History** | Decades; ALFRED vintages for revision-aware research |
| **Cost** | Free API key at [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) |

**Good for:** Tier-B macro filters. Paying Barchart/Polygon for *price* data does not improve
macro quality — FRED is the right free source.

**Bad for:** intraday macro; using **latest revised** CPI/GDP in backtests without vintage
handling (look-ahead bias).

**Verdict:** **Keep FRED.** Extend the framework stub. For Tier-B, use `realtime_start` /
ALFRED vintages on revisable series; daily yields (`DGS10`, `T10Y2Y`) are less sensitive.

| Series | FRED ID | Use |
|---|---|---|
| 10-Year Treasury Yield | `DGS10` | Risk-off / risk-on regime |
| 2-Year Treasury Yield | `DGS2` | Short-term rate path |
| Yield Curve (10Y−2Y) | `T10Y2Y` | Recession / expansion signal |
| Fed Funds Rate | `DFF` | Policy regime |
| CPI (all items) | `CPIAUCSL` | Inflation regime (use vintages) |
| CPI Core | `CPILFESL` | |
| WTI Crude (weekly) | `DCOILWTICO` | Cross-check for CL=F / USO |
| Gold (London Fix) | `GOLDAMGBD228NLBM` | Cross-check for GLD |
| ISM Manufacturing PMI | `MANEMP` | Industrial cycle proxy |
| Consumer Sentiment | `UMCSENT` | Risk appetite proxy |
| High-Yield Credit Spread | `BAMLH0A0HYM2` | Risk regime |
| Investment-Grade Spread | `BAMLC0A0CM` | Liquidity regime |

##### C. TradingView — not recommended for programmatic ingest

| | |
|---|---|
| **Protocol** | **No official historical-data API.** Libs (`tvdatafeed`, `tvkit`) reverse-engineer private WebSocket endpoints with your TV login |
| **Coverage** | Broad charts; capped (~5,000 bars per request) |
| **Cost** | TV subscription does **not** grant a data API |

**Verdict:** **Skip for ingest.** Keep TV for charting, manual CSV export, and Pine output
from CryoQuant. Do not build `cryoquant.data.sources.tradingview`.

##### D. Barchart OnDemand — skip unless budget is $500+/mo

Official REST (JSON/XML/CSV), institutional futures/forex coverage. OnDemand APIs **from
~$500/month**; Excel add-in ~$70/mo is not useful for a Python pipeline.

##### E. Tiingo — best paid upgrade; strong free tier (~$0)

Official REST; US equities/ETFs (EOD + IEX hourly since ~2017); FX hourly. Free tier:
1,000 req/day, 500 symbols/month. **Sign up for a free token now** — use as cross-check
or fallback per symbol if Yahoo returns gaps. Paid Power ~$10–30/mo if you outgrow limits.

##### F. Twelve Data — free multi-asset backup (800 req/day)

Official REST; ETFs, FX, commodities (`XAU/USD`, energy). `interval=1h` with `start_date` /
`end_date`; up to 5,000 bars per request. Good second source for FX and commodity proxies
without paying.

##### G. Polygon.io (Massive) — defer

Official REST + WebSocket. Free tier: 5 calls/min and **~2-year delayed data** — unsuitable
for recent holdout validation. Revisit for deep US intraday work later.

##### H. Nasdaq Data Link / Quandl CHRIS — deprecated

Free `CHRIS/CME_*` continuous futures were **discontinued in 2024**. Do not plan around them.

##### I. CBOE — free official VIX history

Prefer direct CSV over `^VIX` on Yahoo:

`https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv`

##### J. ECB / Frankfurter — free FX cross-check (daily close only)

[Frankfurter API](https://api.frankfurter.dev/) — ECB reference rates, no key, back to 1999.
Close only (no OHLC), EUR-based. Sanity-check Yahoo FX; not a full OHLCV replacement.

---

#### Recommended tiered stack

```
Tier 1 — Primary (free)
  yfinance  → ETFs, indices, FX, commodity proxies (daily + 1h up to 730d)
  FRED      → macro regime features
  CBOE CSV  → VIX history

Tier 2 — Optional cross-check (free, no login conflicts)
  Frankfurter → FX daily close sanity check
  Tiingo / Twelve Data free tokens → per-symbol fallback if Yahoo gaps

Tier 3 — Paid fallback (only if Tier 1 fails QA on a symbol)
  Tiingo Power (~$10–30/mo) → cleaner adjusted EOD + IEX hourly

Not planned: IBKR, TradingView scrapers, Barchart, Polygon free tier
```

**Phase 1 QA gate:** compare Yahoo daily close vs Frankfurter (FX) or Tiingo/Twelve Data
(ETFs) on 252 overlapping days. Log max abs % diff. Swap source for symbols above 0.5%
median diff.

**When paying actually helps:**
- Yahoo returns gaps or bad adjustments on a symbol → Tiingo free token, then paid if needed
- Intraday bars >2 years on US names at exchange quality → Tiingo IEX or Polygon paid
- Licensed continuous futures with roll logic → defer; we use ETF proxies first

### 1.3 Data Ingestion — Design Principles

Build on the **existing CryoQuant data layer** (`loader`, `catalog`, `OHLCVBars`,
`STORE_ROOT`) — do not invent a parallel cache under `analyses/trend_following/data/`.
Multi-asset OHLCV lands in the same partitioned parquet tree as Binance data so any future
analysis can call `load(Symbol("yahoo", "SPY"), tf="1d", ...)`.

| Principle | Rule |
|---|---|
| **Single source of truth** | `data/` (`STORE_ROOT`) + DuckDB `catalog.duckdb` — not ad-hoc CSVs |
| **Closed bars only** | Drop the in-progress bar at fetch time (match Binance source behaviour) |
| **Bar-open timestamps** | Index = bar open, UTC tz-aware; use `cryocore.time.floor_to_tf` |
| **No price imputation** | Missing bars stay missing; log gaps, never forward-fill OHLCV at ingest |
| **Validate before write** | `OHLCVBars` + extended sanity checks; bad partitions are not committed |
| **Incremental refresh** | Re-run fetches only missing year-month partitions (loader already does this) |
| **Reproducible QA** | Every ingest run writes `data/qa/ingest_<run_id>.json` with per-symbol reports |

---

### 1.4 Ingestion Pipeline

Six stages. Framework code owns stages 1–5; this analysis owns the universe manifest
and the orchestration script.

```
┌──────────┐   ┌───────────┐   ┌────────┐   ┌──────────┐   ┌───────┐   ┌─────────┐
│ 1.FETCH  │ → │2.NORMALIZE│ → │3.CLEAN │ → │4.VALIDATE│ → │5.WRITE │ → │6.QA LOG │
└──────────┘   └───────────┘   └────────┘   └──────────┘   └───────┘   └─────────┘
  sources.*     cleaning.py     cleaning.py   OHLCVBars     loader       qa/report
```

#### Stage 1 — Fetch (`cryoquant.data.sources.*`)

| Dataset | Source module | Symbol venue | Notes |
|---|---|---|---|
| OHLCV | `sources.yahoo` | `yahoo` | `fetch_bars(symbol, tf, start, end)` — wraps yfinance |
| Macro | `sources.fred` | `fred` | `fetch_series(id, start, end)` — already exists; extend aliases |
| VIX | `sources.cboe` | `cboe` | `fetch_vix(start, end)` — CBOE CSV |

Fetchers return **raw** DataFrames. No catalog writes inside sources.

#### Stage 2 — Normalize (`cryoquant.data.cleaning.normalize_ohlcv`)

Convert provider output → canonical schema:

- Index: `DatetimeIndex`, name `timestamp`, **UTC tz-aware**
- Columns: `open`, `high`, `low`, `close`, `volume` — all `float64`
- Fix yfinance quirks: flatten MultiIndex columns; `auto_adjust=True` for equities/ETFs
- **FX quote convention:** store `quote_usd_per_unit` metadata; convert `JPY=X` / `CAD=X`
  to direct pair quotes (e.g. USDJPY) in a `quote_mode` column or sidecar JSON so downstream
  code never mixes conventions silently
- **Bar labelling:** floor timestamps to bar-open via `floor_to_tf`; reject bars that don't
  align to the expected grid (log count of misaligned rows)

#### Stage 3 — Clean (`cryoquant.data.cleaning.clean_ohlcv`)

| Check | Action |
|---|---|
| Duplicate timestamps | `keep="last"` (same as loader merge logic) |
| Non-monotonic index | Sort; error if duplicates remain |
| In-progress bar | Drop bar where `bar_open + tf > utcnow()` |
| OHLC sanity | `low ≤ open,close ≤ high`; swap/fix or drop row if violated |
| Zero/negative prices | Drop row (FX/commodity bad ticks) |
| Negative volume | Drop row or set 0 for index symbols without volume |
| Weekend FX daily bars | Drop Sat/Sun for `asset_class=fx` at `tf >= 1d` |
| Extreme single-bar jumps | Flag (not remove) if `\|ret\| > 20%` on liquid ETF — roll artefact on `=F` |
| Empty result | Raise — do not write empty partition |

**Do not** at this stage: forward-fill, back-fill, interpolate, or smooth futures rolls.

#### Stage 4 — Validate

1. **`OHLCVBars.validate_df`** — structural (existing `cryocore.schemas`)
2. **`cleaning.audit_bars(df, symbol, tf)`** — returns `BarAudit`:
   - `n_bars`, `ts_min`, `ts_max`, `pct_duplicate_dropped`, `n_gaps`, `gap_max_bars`
   - `calendar` used (`nyse`, `fx_eur`, `crypto_24_7`)
   - `flags`: list of warnings (jump bars, low volume days, etc.)
3. **Cross-source spot-check** (optional, offline): compare last 252 daily closes vs
   Frankfurter (FX) or Tiingo (ETF) — warn if median abs diff > 0.5%

Failed validation → no write; error surfaces in ingest log.

#### Stage 5 — Write + catalog

Use existing loader partition logic:

```
STORE_ROOT/
  yahoo/yahoo_SPY/1d/year=2024/month=03.parquet
  yahoo/yahoo_EURUSD/1h/year=2025/month=06.parquet
  macro/fred/DGS10/year=2024.parquet          # macro: one series, yearly parts
  macro/cboe/VIX/year=2024.parquet
```

- OHLCV: extend `loader._fetch` / `_partition_path` for `venue=yahoo`
- Macro series: new `cryoquant.data.macro_store.write_series(series_id, df)` — not OHLCV;
  stores `value` + optional `realtime_start`/`realtime_end` columns for vintage-aware series
- Register in DuckDB catalog (`catalog.register`) with `row_count`, `ts_min`, `ts_max`,
  `schema_hash`, `last_refresh`

#### Stage 6 — QA report

Write `STORE_ROOT/qa/ingest_<ISO-datetime>.json`:

```json
{
  "run_id": "2026-06-15T12:00:00Z",
  "symbols": {
    "yahoo:SPY/1d": {"status": "ok", "n_bars": 3521, "n_gaps": 0, "cross_check": "pass"},
    "yahoo:EURUSD/1h": {"status": "warn", "flags": ["fx_weekend_bars_dropped: 104"]}
  }
}
```

Also write/update `STORE_ROOT/qa/latest.json` symlink or copy for agents to read quickly.

---

### 1.5 Look-Ahead Bias Controls (at ingest + downstream)

Ingest can eliminate several bias classes **before** features or backtests run:

| Risk | Ingest-time mitigation | Feature-time rule (still required) |
|---|---|---|
| **In-progress bar** | Drop open bar in `clean_ohlcv` | Signals use `.shift(1)` or closed-bar primitives only |
| **Misaligned bar timestamps** | `floor_to_tf`; audit misaligned count | `htf_align` with `lookahead_off` semantics |
| **FX weekend phantom bars** | Drop for daily+ FX | Calendar filter in `calendar_features` |
| **FRED revisions** | Store `observation_date`; for CPI/GDP fetch **vintage** columns via `realtime_start` | Tier-B: merge macro with `merge_asof(..., direction="backward")` on **as-of date**, not calendar date |
| **Macro forward-fill** | **Never** at ingest | Forward-fill to bar frequency only in feature builder, lagged one release day where needed |
| **Split-adjusted prices** | `auto_adjust=True` for Yahoo equities/ETFs; record in catalog metadata | Consistent across train/holdout |
| **Futures roll jumps** | Flag in audit; prefer ETF proxies in universe | Document in RESULTS if `=F` used |

Macro ingest stores two tables per revisable series when Tier-B is enabled:

- `macro/fred/CPIAUCSL/latest.parquet` — convenience (research only, not for strict OOS)
- `macro/fred/CPIAUCSL/vintages.parquet` — `(observation_date, realtime_start, value)` for
  point-in-time joins

---

### 1.6 Storage Format Summary

| Data type | Layout | Loader API | Catalog key |
|---|---|---|---|
| OHLCV bars | `STORE_ROOT/<source>/<venue>_<ticker>/<tf>/year=YYYY/month=MM.parquet` | `loader.load(symbol, tf, start, end)` | `(source, venue, ticker, tf)` |
| Macro series | `STORE_ROOT/macro/fred/<series_id>/year=YYYY.parquet` | `macro_store.load_series(id, start, end)` | `(macro, fred, series_id, daily)` |
| VIX | `STORE_ROOT/macro/cboe/VIX/year=YYYY.parquet` | same as macro | `(macro, cboe, VIX, daily)` |
| QA reports | `STORE_ROOT/qa/*.json` | read directly | not cataloged |

Parquet over CSV: typed columns, fast partial reads, consistent with Binance/Deribit paths.
`data/` is gitignored repo-wide; catalog is the discovery index.

**Instrument registry:** extend `cryocore.instruments` defaults with `yahoo` entries
(`SPY`, `GLD`, `EURUSD`, …) including `asset_class` and `calendar` — reusable metadata
for cleaning rules and session filters.

---

### 1.7 Refresh and Re-Run Workflow

```bash
# Full universe — daily from 2010, hourly from 2020 (Twelve Data)
python -m analyses.trend_following.run_ingest --tf 1d,1h

# Daily only (incremental — fetches missing partitions only)
python -m analyses.trend_following.run_ingest --tf 1d --start 2010-01-01

# Hourly only — force re-fetch from Twelve Data
python -m analyses.trend_following.run_ingest --ohlcv-only --tf 1h --start 2020-01-01 --force

# Macro + VIX only
python -m analyses.trend_following.run_ingest --macro-only --start 2010-01-01

# Specific symbols
python -m analyses.trend_following.run_ingest --symbols yahoo:SPY,yahoo:GLD --tf 1d --force

# Post-ingest audit
python -m analyses.trend_following.run_ingest --audit --tf 1d
```

On re-run of the research task:

1. `run_ingest` refreshes stale partitions (loader fetches missing months only)
2. QA report regenerated; compare to prior `qa/latest.json` for drift
3. Feature cache (`FEATURE_STORE_DIR`) may need invalidation if bar data changed — bump
   builder version or delete affected cache keys
4. RESULTS.md notes ingest `run_id` and any new QA warnings

---

### 1.8 Code Map — Framework vs This Analysis

**Framework (reusable — Phase 1 complete):**

```
cryoquant/data/
├── cleaning.py              # normalize_ohlcv, clean_ohlcv, audit_bars (asset_class-aware)
├── ingest.py                # generic orchestrator: load_universe, run_ingest, run_audit
├── macro_store.py           # write_series, load_series, list_macro (auto-discovers sources)
├── loader.py                # yahoo venue + Twelve Data 1h routing; delete_partitions()
├── catalog.py               # (existing)
└── sources/
    ├── yahoo.py             # fetch_bars (daily + yfinance hourly fallback)
    ├── twelvedata.py        # fetch_bars (hourly, paginated, timezone=UTC)
    ├── cboe.py              # fetch_vix (FRED fallback uses observation_start/end)
    └── fred.py              # fetch_series (25+ aliases, fredapi + CSV fallback)

cryocore/
├── instruments.py           # Symbol entries + td_ticker_info / should_use_twelvedata helpers
└── calendars.py             # fx_24_5 (replaces stub)
```

**Analysis-local:**

```
analyses/trend_following/
├── universe.yaml            # tickers, asset_class, preferred tf, train/holdout splits
├── run_ingest.py            # thin CLI wrapper → cryoquant.data.ingest.run_ingest
├── PLAN.md
└── RESULTS.md               # records ingest run_id per phase
```

**Tests (framework):**

- `tests/test_data_cleaning.py` — dupes, OHLC sanity, FX weekends, commodity spike thresholds
- `tests/test_sources_twelvedata.py` — TD parsing, inversion, pagination error handling (mocked)
- `tests/test_sources_fred.py` — CSV fallback, alias table (mocked)
- `tests/test_ingest.py` — universe parsing, delete_partitions, IngestResult
- `tests/live/test_yahoo_smoke.py` — fetch SPY 30d 1d, passes OHLCVBars
- Reuse existing catalog/loader offline tests with `venue=yahoo` fixtures

---

### 1.9 Phase 1 Checklist

| Step | Status |
|---|---|
| `sources.yahoo` + loader dispatch | ✅ |
| `sources.twelvedata` + loader 1h routing | ✅ |
| `cleaning.py` + tests (42+ passing) | ✅ |
| `ingest.py` generic orchestrator + thin `run_ingest.py` | ✅ |
| `loader.delete_partitions()` for `--force` re-ingest | ✅ |
| TD ticker mapping in `Instrument.meta` (`td_ticker_info`) | ✅ |
| Asset-class-aware audit (`commodity` → 35% spike) | ✅ |
| FX closed-bar drop via `calendar.is_open()` | ✅ |
| Mocked HTTP tests (twelvedata, fred) | ✅ |
| TD `timezone=UTC` fix + hourly re-ingest | ✅ |
| `sources.cboe` + VIX in macro store | ✅ |
| FRED alias table (25+ series, `DFF` fix) | ✅ |
| `fx_24_5` calendar | ✅ |
| `universe.yaml` + `run_ingest.py` | ✅ |
| Full universe ingest (34 daily + 13 hourly + 16 macro) | ✅ |
| Audit threshold tuning (FX stale, futures/commodity spike) | ✅ |
| QA JSON reports (`data/qa/`) | ⬜ deferred |
| Frankfurter/Tiingo cross-check | ⬜ deferred |

Downstream (`features.py`, `backtest.py`) **only** read via `loader.load` / `macro_store` —
never call yfinance, Twelve Data, or FRED directly.

---

## Phase 2 — Feature Engineering

### 2.1 OHLCV Multi-Timeframe Features (CryoQuant primitives)

These are the foundation. All are available in `cryoquant.features.primitives` and can be
applied to any DataFrame in the canonical schema.

| Feature | Primitive | Timeframes |
|---|---|---|
| EMA crossovers (fast/slow) | `ema(close, n)` | 1h, 4h, 1d |
| Price vs EMA distance (%) | `ema` | 20, 50, 100, 200 bar EMA |
| RSI | `rsi(close, 14)` | 1h, 4h, 1d |
| ATR (absolute + %) | `atr(df, 14)`, `atr_pct` | 1h, 4h, 1d |
| Bollinger Band width | `bb_width` | 20-bar, 2σ |
| Realized volatility | `realised_vol(close, n)` | 24h, 5d, 20d |
| RV rank (percentile) | `rv_rank` | 252-day window |
| Vol Z-score | `vol_z` | vs trailing mean |
| Range ratio (H/L / ATR) | `range_ratio` | 1d |
| Returns (multi-period) | `close.pct_change` | 1h, 4h, 1d, 5d, 20d |
| Momentum / acceleration | rolling return diff | 1h, 1d |

**Multi-timeframe alignment:** Use `cryoquant.features.primitives.resample` and `htf_align`
to bring higher-timeframe (HTF) features down to the analysis timeframe without look-ahead.

### 2.2 Trend-Specific Technical Features

Beyond the standard primitives, trend-following research benefits from:

| Feature | Description | Rationale |
|---|---|---|
| **ADX** (Average Directional Index) | Trend strength 0–100; ADX > 25 = trending | Filters whipsaw in range-bound periods |
| **Donchian Channel** (20/55-bar) | Price vs N-bar high/low | Classic CTA/turtle breakout signal |
| **Keltner Channel** | ATR-based channel around EMA | Volatility-adjusted trend channel |
| **Supertrend** | ATR-based trend flip | Simple, robust trend-state indicator |
| **MACD** | EMA(12) − EMA(26) + signal | Momentum confirmation |
| **52-week high/low proximity** | Close / rolling 252d max | Strong trend anchor |
| **Rate of Change (ROC)** | `close / close.shift(n) - 1` | 1m, 3m, 6m, 12m lookbacks |
| **Linear regression slope** | OLS slope of close over N bars | Trend gradient; cleaner than EMA diff |
| **Hurst exponent (approx.)** | R/S or DFA over 64/128 bars | > 0.5 = trending; < 0.5 = mean-reverting |

### 2.3 Volume Features

Volume is a powerful confirmation layer for trend signals; available for ETFs and futures.

| Feature | Description |
|---|---|
| **Volume ratio** | `volume / volume.rolling(20).mean()` — volume surge |
| **OBV** (On-Balance Volume) | Cumulative signed volume; trend of OBV vs price |
| **Volume-weighted price deviation** | `(close - vwap) / atr` — intraday position within VWAP |
| **Volume momentum** | ROC of volume (vol surge preceding breakout) |
| **Price-volume divergence** | Price makes new high but OBV does not — trend warning |

### 2.4 Macro / Cross-Asset Features

These add regime context — trend strategies behave very differently across macro regimes.

| Feature | Source | Construction |
|---|---|---|
| **VIX level** | CBOE CSV (§1.2) | Raw + 20d Z-score; above 30 = stress |
| **VIX term structure slope** | `^VIX9D`, `^VIX3M` | VIX9D / VIX3M; < 1 = backwardation (fear) |
| **Yield curve** | FRED `T10Y2Y` | Sign (normal/inverted) + slope trend |
| **10Y yield trend** | FRED `DGS10` | 20d EMA direction; rising = headwind for equities |
| **DXY trend** | `DX-Y.NYB` (yfinance) | USD strength; headwind for gold/commodities |
| **HY credit spread** | FRED `BAMLH0A0HYM2` | Widening = risk-off; dampens equity trend signals |
| **Equity/commodity correlation** | Rolling 20d corr(SPY, GLD) | Regime-shifted; useful for portfolio diversification |
| **Inflation regime** | FRED `CPIAUCSL` MoM, YoY | High inflation → commodity trend tailwind |
| **PMI level and trend** | FRED `MANEMP` proxy | > 50 expanding = industrials/commodities tailwind |

**Note on frequency mismatch:** FRED macro series are monthly or daily; they must be forward-filled to align with intraday/daily bar frequency without introducing look-ahead.

### 2.5 Cross-Instrument Relative Strength

| Feature | Construction | Use |
|---|---|---|
| **RS vs benchmark** | `instrument_return / SPY_return` over 20d/60d | Sector rotation, commodity leadership |
| **Breadth** | Fraction of S&P 500 sectors above 50d EMA | Market-wide trend health |
| **Gold/Oil ratio** | `GLD / USO` | Deflationary vs inflationary regime proxy |
| **Copper/Gold ratio** | `HG=F / GC=F` | Growth expectations |

### 2.6 Calendar Features

Already available in `cryoquant.features.calendar_features`:

| Feature | Notes |
|---|---|
| Day of week | Weekend effects in commodities |
| Hour UTC | US market open (14:30 UTC), close (21:00 UTC) |
| US session flag | Active-market filter for intraday signals |
| US holiday flag | Thin market — suppress signals |
| Month / quarter | Seasonal patterns in commodities and gold |

### 2.7 Features to Explicitly Avoid (Lookahead Traps)

- Any forward return (belongs in labels only — `ForwardReturnLabeler`)
- Volume of the *current* bar combined with the *current* close (bar not yet closed)
- Analyst revisions, earnings surprises — require point-in-time database to avoid lookahead
- Short interest — only monthly frequency, risk of survivorship bias in free data

---

## Phase 3 — Candidate Generation and Evaluation Framework

### 3.1 Strategy Taxonomy

We organise candidate trend strategies into three tiers by complexity:

**Tier A — Pure rule-based (`BoolSignal` / `StateSignal`):**
Fast to test; no ML training required. Interpretable. Baseline comparison point for
all more complex strategies.

| Candidate | Description | Timeframe | Instruments |
|---|---|---|---|
| A1: EMA crossover | EMA(fast) crosses EMA(slow) | 1d, 4h | All |
| A2: Donchian breakout | Close > N-bar high | 1d, 4h | Commodities, gold |
| A3: Supertrend flip | Price crosses Supertrend line | 1h, 4h | Indices, commodities |
| A4: 52-week high breakout | Close exceeds 52-week high | 1d | US equities / ETFs |
| A5: MA stack alignment | 20/50/200 EMA all aligned | 1d | All |
| A6: ADX + EMA direction | ADX > 25 AND price above/below EMA | 4h, 1d | All |

**Tier B — Rule + Macro filter (`StateSignal` + FRED context):**
Applies a macro-regime gate on top of a Tier A signal.

| Candidate | Description |
|---|---|
| B1: A1 + VIX filter | Only trade when VIX < 25 (avoid crisis regimes) |
| B2: A2 + DXY filter | Commodity breakout only when DXY is falling (EMA trending down) |
| B3: A3 + yield curve | Equity trend only when yield curve is not deeply inverted |
| B4: A4 + credit spread | Equity breakout only when HY spreads < 400 bps |

**Tier C — ML-augmented (`ProbSignal` via `TabularModel`):**
Feature-engineered dataset → LightGBM → calibrated probability → threshold selection.

| Candidate | Description |
|---|---|
| C1: Multi-TF momentum model | Features from §2.1–2.2; labels = 5d forward return > 1% |
| C2: Volume-confirmed breakout | Adds §2.3 volume features; label = breakout continuation |
| C3: Macro-aware trend model | All feature tiers; label = 10d return > 2% |

### 3.2 Candidate Evaluation Criteria

Each candidate must pass all gates before being promoted to detailed analysis:

| Gate | Metric | Threshold |
|---|---|---|
| Minimum trade count | `n_trades / month` | ≥ 5 |
| Maximum daily intensity | Max trades on any single day | ≤ 3 |
| Positive expectancy | `avg_pnl_pct` (net of 10 bps fee) | > 0 |
| Credible Sharpe | Annualised Sharpe (trade returns) | ≥ 0.8 |
| Deflated Sharpe Ratio | `deflated_sharpe(sharpe, n_trials, n_trades)` | > 0.95 |
| Max drawdown | Peak-to-trough equity | ≤ −25% |
| Win rate | Fraction of profitable trades | ≥ 40% |
| Out-of-sample validity | Walk-forward hold-out performance | Not worse than −30% vs IS |

**Fee assumption:** 10 bps round-trip (ETF market order; 5 bps for liquid index futures).

**n_trials accounting:** every parameter combination tested (EMA period, breakout window,
threshold, etc.) must be counted in `deflated_sharpe`. No cherry-picking.

### 3.3 Evaluation Pipeline (CryoQuant tools)

```python
# 1. Load cached bars (framework loader — not raw yfinance)
from cryocore.instruments import Symbol, parse_symbol
from cryoquant.data.loader import load
from datetime import datetime, timezone

sym = parse_symbol("yahoo:GLD")
bars = load(sym, tf="1d", start=datetime(2010, 1, 1, tzinfo=timezone.utc))
```

# 2. Build features (uses cryoquant primitives under the hood)
from analyses.trend_following.features import TrendFeatures
X = TrendFeatures().build(bars)

# 3. Create signal (Tier A example)
from cryoquant.signals.base import BoolSignal
sig = BoolSignal(
    signal_id="donchian_breakout_55d_GLD",
    condition=lambda df: df["close"] > df["close"].shift(1).rolling(55).max(),
    version="1",
    symbol_str="yfinance:GLD",
)

# 4. Backtest
from cryoquant.backtest.spot_pnl import simulate
result = simulate(sig, bars, hold_h=5, fee_bps=10.0)

# 5. Robustness
from cryoquant.backtest.robustness import deflated_sharpe
dsr = deflated_sharpe(result.metrics["sharpe"], n_trials=n_tested, n_obs=result.metrics["n_trades"])

# 6. Report
from cryoquant.backtest.reports import render_spot_result
render_spot_result(result, "analyses/trend_following/reports/donchian_55d_GLD.html")
```

### 3.4 Ranking Methodology

After all candidates pass the gates above, rank survivors on a **composite score**:

```
Score = w1 × DSR
      + w2 × Sharpe
      + w3 × (1 - |max_drawdown|)
      + w4 × avg_pnl_pct
      + w5 × trade_frequency_score    # penalises < 5 or > 90 trades/month
      + w6 × instrument_diversity     # bonus for strategy working across ≥ 3 instruments
```

Weights to be set empirically based on Phase 3 findings. All weights are linear; no
hidden penalties. The ranking is a starting point for prioritisation, not a final verdict.

### 3.5 Multi-Instrument Robustness Test

A trend strategy is more credible if it works across multiple instruments without
instrument-specific parameter tuning. Procedure:

1. Develop and select parameters on a **training universe** (SPY, GLD, CL=F daily bars,
   2010–2021)
2. Validate on **held-out universe** (QQQ, GC=F, XLE, NG=F daily bars, 2021–present)
3. Validate on a **held-out time window** (all instruments, 2022–present)
4. Flag any strategy that only works on one instrument as **fragile** (still worth
   reporting, but deprioritised)

---

## Phase 4 — Deeper Investigation of Survivors

For candidates with DSR > 0.95 and positive multi-instrument results:

1. **Parameter sensitivity sweep:** ±20% around selected parameters; report degradation
2. **Timeframe robustness:** re-run on adjacent timeframes (e.g. if 1d works, check 4h and 1w)
3. **Macro-regime segmentation:** segment equity curve by VIX quartile, yield curve state,
   bull/bear market phase — understand where the edge comes from
4. **Correlation check across instruments:** if SPY and QQQ give nearly identical signals,
   they're the same trade — prefer the less correlated instrument pair for diversification
5. **Optional ML uplift:** if a rule-based candidate is near the DSR threshold, test whether
   a `TabularModel` wrapping the same feature set improves calibration

---

## Research Phases — Summary

| Phase | Goal | Tools | Status |
|---|---|---|---|
| **1** | Ingest pipeline: fetch, clean, validate, store | `loader`, `cleaning`, `run_ingest` | ✅ **Complete** — daily 2010+, hourly 2020+ (TD), 17 macro series, 0 data errors |
| **2** | Feature library — technical + macro | `cryoquant.features.primitives`, local `features.py` | Pending |
| **3A** | Tier-A rule candidates sweep | `cryoquant.signals`, `simulate`, `deflated_sharpe` | Pending |
| **3B** | Tier-B macro-filtered candidates | Same + FRED features | Pending |
| **3C** | Tier-C ML candidates | `TabularModel`, `walk_forward`, `prob_from_model` | Pending |
| **4** | Deep dive on survivors | Sensitivity, regime segmentation, diversification | Pending |

**Agent rules:**
- Phases 1–3A may proceed autonomously.
- After Phase 3A, present findings and ranked table before continuing to 3B/3C.
- Never commit generated artifacts (`data/`, `reports/` are gitignored).
- Count every parameter combination tested in `n_trials` for DSR — no exceptions.
- Re-fetch data at analysis time; never hardcode prices.

---

## Open Questions

1. **Intraday vs daily:** yfinance 1h covers only ~2 years; **Twelve Data free tier provides 1h from 2020 (6+ years)** — resolved. Plan: use Twelve Data as primary 1h source for ETFs and FX. Daily sweep first, then 1h as second pass.
2. **Long-only vs long/short:** commodities and gold have meaningful short opportunities
   (backwardation, DXY correlation); indices are structurally long-biased. Should we
   evaluate each leg separately?
3. **Continuous futures roll handling:** `=F` tickers on yfinance use nearest-month
   continuous contracts; no explicit roll-adjustment is applied. For commodities with
   large roll costs (NG, CL), this creates phantom P&L around roll dates. Use ETF proxies
   (USO, GLD) for backtesting; futures for live signal generation?
4. **Trade frequency constraint mechanics:** the `simulate()` function in CryoQuant is
   non-overlapping (one open trade at a time). To enforce ≤ 3 trades/day across a
   multi-instrument portfolio, we need a portfolio-level governor — not yet in the
   framework. **Phase 3A workaround:** evaluate each instrument independently (constraint
   is per-instrument). **If the sweep needs portfolio-level logic:** implement in
   `cryoquant.backtest` (framework extension), not a one-off hack in this dir.
5. **Universe breadth vs. depth:** start narrow (6–8 instruments) for the initial sweep,
   then expand to the full universe for robustness. Prevents overfitting to a large
   instrument set during signal development.

---

## CryoQuant Integration Map

| Need | Status | Target | Notes |
|---|---|---|---|
| OHLCV normalize / clean / audit | ✅ **Done** | `data.cleaning` | `normalize_ohlcv`, `clean_ohlcv`, `audit_bars` |
| Macro parquet store | ✅ **Done** | `data.macro_store` | Partitioned parquet; catalog-backed |
| Partitioned parquet + catalog | ✅ **Done** | — | `yahoo` venue + sentinel files for pre-inception |
| Ingest orchestration | ✅ **Done** | **Analysis** | `universe.yaml`, `run_ingest.py` |
| FRED macro series | ✅ **Done** | `sources.fred` | 25+ aliases; `FEDFUNDS` → `DFF`; NFCI for long credit history |
| VIX history | ✅ **Done** | `sources.cboe` | CBOE CSV primary; FRED VIXCLS fallback |
| Yahoo OHLCV source | ✅ **Done** | `sources.yahoo` | Daily primary; hourly fallback when no TD key |
| Twelve Data 1h source | ✅ **Done** | `sources.twelvedata` | Loader auto-routes `yahoo`+`1h` for ETF/FX; 6yr history |
| FX 24/5 calendar | ✅ **Done** | `cryocore.calendars` | Full Sun 21:00 UTC open; London/NY/Tokyo sessions |
| Instrument registry (yahoo, CBOE) | ✅ **Done** | `cryocore.instruments` | 40+ instruments; FX quote_convention metadata |
| Audit threshold tuning | ✅ **Partial** | `data.cleaning` | FX stale 8 bars; futures spike 35%; daily gaps unchanged |
| QA ingest reports (JSON) | **⬜ Low** | `data/qa/` | Per-run JSON; not blocking research |
| Feature primitives (EMA, RSI, ATR, RV…) | **Present** | — | `cryoquant.features.primitives` |
| Multi-TF alignment | **Present** | — | `resample`, `htf_align` |
| Calendar features | **Present** | — | `cryoquant.features.calendar_features` |
| BoolSignal / StateSignal | **Present** | — | `cryoquant.signals.base` |
| LightGBM model + walk-forward CV | **Present** | — | `cryoquant.models.tabular`, `.cv` |
| Spot backtest | **Present** | — | `cryoquant.backtest.spot_pnl.simulate` |
| Deflated Sharpe | **Present** | — | `cryoquant.backtest.robustness.deflated_sharpe` |
| HTML reports | **Present** | — | `cryoquant.backtest.reports.render_spot_result` |
| Portfolio-level trade-frequency governor | **Missing** | **Framework** (if needed) | Phase 3A: per-instrument workaround first |
| Candidate sweep orchestration | N/A | **Analysis** | `backtest.py`, `candidates.py` |
