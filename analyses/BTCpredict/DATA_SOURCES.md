---
name: BTCpredict — Data Source Review
status: signed off (2026-06-28); E-series migrated to Farside + Strategy.com (2026-06-28)
purpose: >
  Per-source decision register. Approved rows are mirrored in universe.yaml.
  D-3 (free-only) is locked. E1–E2/E4–E5 ingested via Farside + Strategy.com.
upstream: KICKOFF.md §5.0, SPEC.md §5
---

# BTCpredict — Data source review

## Where decisions live (read this first)

| Layer | What it decides | Status |
|---|---|---|
| **KICKOFF D-3** | *Class* of data: free public sources + Deribit surface; no paid on-chain v1 | ✅ Locked |
| **This file (`DATA_SOURCES.md`)** | *Which* series, from *which* vendor, start dates, Goal 1 vs 2 need | ✅ **Signed off 2026-06-28** |
| **`universe.yaml`** | Machine-readable ingest manifest from approved rows | ✅ Generated |
| **Phase 1 ingest** | Pull approved universe into CryoQuant store | ✅ **Complete** 2026-06-28 |
| **Phase 1 QA** | Source-level sanity (`run_phase1_qa.py`) | ✅ **Pass** — 0 errors, 12 warnings |
| **Phase 2 features** | Causal feature matrix per catalog | ✅ **Complete** 2026-06-28 |
| **Phase 2 QA** | `run_phase2_qa.py` | ✅ **Pass** — 0 errors, 0 warnings |
| **Phase 3 labels** | Multi-horizon label store per [`LABEL_CATALOG.md`](LABEL_CATALOG.md) | ✅ **Complete** 2026-06-28 |
| **Phase 3 QA** | `run_phase3_qa.py` | ✅ **Pass** — 0 errors, 1 warning |
| **[`FEATURE_CATALOG.md`](FEATURE_CATALOG.md)** | Phase 2 column register (core / extended tags) | ✅ **Built** 2026-06-28 |
| **[`LABEL_CATALOG.md`](LABEL_CATALOG.md)** | Phase 3 label register (families 1–6) | ✅ **Signed off** 2026-06-28 |
| **`features.yaml`** | Machine-readable catalog for builders & Phase 4 selection | ✅ Generated |
| **`labels.yaml`** | Machine-readable label families | ✅ Generated |

**Workflow:** Phase 0–3 ✅ → **Phase 4** (models) → …

**Principles when reviewing:**

- **Goal 2 (short vol)** needs: daily OHLCV (BTC/ETH), **DVOL** (reliable IV index), realized vol; **option chains only where parquets exist** (~Apr 2025+) for backtest. Options are a **small** feature slice — core signals are price, macro, funding, RV (see `OPTIONS_SURFACE_PROXY_PROPOSAL.md`).
- **Goal 1 (direction)** benefits from macro, funding, cross-asset, **US institutional flows** (ETF, corporate treasury), sentiment — but each adds alignment/leakage surface area.
- **Derived** series (ratios from OHLCV) cost nothing extra once base prices are in.
- Prefer sources **already in CryoQuant** before building new connectors.
- **History gate:** ≥ **2 years** where the product exists; otherwise **`exclude`** until a replacement is wired (see History audit below).

---

## History availability audit (2026-06-28)

**Gate for backtest use:** ≥ **2 years** of history *where the product exists*, verified on disk or from canonical upstream.

**Split context:** Dev **2018-01-01 → 2024-05-31** · Hold-out **2024-06-01 → present**.

| ID | Series | Ingested range | Rows | Dev overlap | Meets 2y gate? | Verdict |
|---|---|---|---|---|---|---|
| A1–A6 | OHLCV | 2018+ / 2020+ hourly | 2.1k–56k | Full dev | ✅ | **Keep** |
| B1–B2,B5 | Funding | 2020+ | ~2.4k | Full dev from 2020 | ✅ | **Keep** |
| B3–B4 | OI (Xoomar) | 2021+ | 1.7k–2k | Partial (2021+) | ✅ from 2021 | **Keep** — pre-2021 NaN |
| C1–C2 | DVOL | 2021+ | ~1.6k–1.9k | Partial | ✅ from 2021 | **Keep** |
| C3–C4 | Option chains | ~2025-04+ only | ~439 days | **None in dev** | ⚠️ hold-out only | **Keep** — by design (P-3) |
| D1–D6,D14 | Macro / FOMC | 2010+ / 2018+ | 109–4.3k | Full dev | ✅ | **Keep** |
| F1–F2 | Fear/greed, stables | 2018+ | ~3.1k | Full dev | ✅ | **Keep** |
| G1–G4 | Network | 2018+ | ~3.1k | Full dev | ✅ | **Keep** |
| **E1–E2** | **ETF (Farside)** | **2024-01-11 → 2026-06-26** | **632 agg / 616×11 td** | **~102 td in dev** | **✅ ~2.4y** | **Keep** |
| **E4–E5** | **MSTR (Strategy.com)** | **2020-08-10 → 2026-06-22** | **114 events** | **Full dev from 2020** | **✅ ~5.8y** | **Keep** |
| E3 | ETF AUM | — | — | — | `defer` | Flows-only v1 |
| SoSoValue E* | (deprecated) | ~30d ETF / ~1y MSTR | — | — | **❌ excluded** | Replaced |

### E-series — verified API limits (live test 2026-06-28)

| Endpoint | Request | Result |
|---|---|---|
| SoSoValue `/etfs/summary-history` | `2024-01-11 → 2024-06-30` | **403** — `"date range exceeds 30 day limit"` |
| sosovalue-pandas chart | `us-btc-spot` | **300 rows**, only **2025-04-16 → 2026-06-26** (~14 mo) |
| SoSoValue MSTR | full pull | **50 events**, **2025-05-12 → 2026-06-22** only |
| **Farside** all-data page | public table | **632 trading days**, **2024-01-11 → 2026-06-26** |
| **Strategy.com** purchases | public table | **114 acquisitions**, **2020-08-10 → present** |

**ETF nuance:** US spot BTC ETFs launched **2024-01-11**. Max history ≈ **2.4 years** today. Dev set has only **~102 trading days** of ETF data (Jan–May 2024) — but hold-out walk-forward still needs full backfill from launch.

**Adopted (2026-06-28):** E1–E2 → **Farside** · E4–E5 → **Strategy.com/purchases** · E3 **`defer`** · SoSoValue → **`exclude`**

---

## Decision legend

| Decision | Meaning |
|---|---|
| `include` | In v1 universe; implement/ingest if not wired |
| `exclude` | Out of scope for this study |
| `defer` | Maybe later; do not ingest in Phase 1 |
| `pending` | Not reviewed yet (default) |

---

## A. Core price — OHLCV (required for both goals)

| ID | Series | Proposed source | TF | Start | CryoQuant | Enables | Decision | Notes |
|---|---|---|---|---|---|---|---|---|
| A1 | BTCUSDT | Binance spot | 1d | 2018-01-01 | ✅ wired | Labels, features, Goal 1+2 | **`include`** | **Canonical price** for BTC |
| A2 | BTCUSDT | Binance spot | 1h | 2020-01-01 | ✅ wired | Intraday RV, overnight gap features | **`include`** | Hourly for feature engineering (D-5) |
| A3 | ETHUSDT | Binance spot | 1d | 2018-01-01 | ✅ wired | Same | **`include`** | Canonical ETH spot |
| A4 | ETHUSDT | Binance spot | 1h | 2020-01-01 | ✅ wired | Intraday features | **`include`** | |
| A5 | SOLUSDT | Binance spot | 1d | 2020-01-01 | ❌ register + ingest | SOL directional (D-10) | **`include`** | Short history; still wanted for Goal 1 |
| A6 | SOLUSDT | Binance spot | 1h | 2020-01-01 | ❌ | Intraday features for SOL | **`include`** | |

**Locked:** Binance spot is the **sole canonical price vendor** for BTC/ETH/SOL (no secondary vendor in v1).

---

## B. Perpetuals / derivatives positioning

| ID | Series | Proposed source | Start | CryoQuant | Enables | Decision | Notes |
|---|---|---|---|---|---|---|---|
| B1 | BTC funding rate | Binance perp REST | 2020-01-01 | ✅ ingested | Sentiment, crowding | **`include`** | macro_store daily |
| B2 | ETH funding rate | Binance perp | 2020-01-01 | ✅ ingested | Same | **`include`** | |
| B3 | BTC open interest | **Xoomar Pulse** (Binance archives) | 2021-01-01 | ✅ ingested | Positioning | **`include`** | 2004 rows → 2026-06-28 |
| B4 | ETH open interest | **Xoomar Pulse** | 2021-01-01 | ✅ ingested | Same | **`include`** | 1671 rows from 2021-12-01 |
| B5 | SOL funding | Binance perp | 2022-01-01 | ✅ ingested | SOL-specific | **`include`** | |

**Locked (2026-06-28):** Full perp positioning stack — funding (B1–B2, B5) + open interest (B3–B4 via Xoomar). See §B.1.

### §B.1 Open interest — source (updated 2026-06-28)

**Rejected:** Binance `/futures/data/openInterestHist` — rolling **~30 days only**; useless for dev backtest.

**Adopted:** [Xoomar Pulse](https://xoomar.com/markets/api/open-interest) — free, no API key (D-3 compliant).

| Property | Value |
|---|---|
| Endpoint | `GET https://xoomar.com/api/markets/open-interest/{btc\|eth}?period=1d&from=&to=` |
| Exchange | Binance perp (matches our price/funding venue) |
| History | **Daily from ~Jan 2021** (Binance Vision archives) |
| Columns | `open_interest` (contracts), `open_interest_usd`, optional `long_short_ratio` |
| Rate limit | ~30 req/min/IP; cache locally |

**Gap:** No OI before 2021. Pre-2021 positioning uses **funding rates (B1/B2)** only; OI features are NaN until 2021-01.

**Alternative (not chosen):** Coinalyze free API (requires signup/key); CoinGlass paid (D-3 violation).

---

## C. Options data — minimal reliable scope (locked 2026-06-28)

> **Principle:** Options are **one signal among many**, not the study spine. Only include
> what we reliably have. Full rationale: **`OPTIONS_SURFACE_PROXY_PROPOSAL.md`**.

**Locked:** P-1 DVOL yes · P-2 defer skew/OI/max pain · P-3 no backfill · P-4 forward chains yes

| ID | Series | Proposed source | Start | CryoQuant | Enables | Decision | Notes |
|---|---|---|---|---|---|---|---|
| C1 | BTC DVOL daily | Deribit API `get_volatility_index_data` | 2021-03-31 | ✅ ingested | `dvol_30d`, VRP, vol-of-vol | `include` | ~1916 rows from 2021-03-31 |
| C2 | ETH DVOL daily | Deribit API | ~2022-01-01 | ✅ ingested | Same for ETH | `include` | |
| C3 | BTC option chains | CryoBacktester parquets | ~2025-04-01 | ✅ read-only | Chain IV/skew + **hold-out backtest** | `include` | Use only where files exist |
| C4 | ETH option chains | CryoBacktester parquets | ~2025-04-01 | ✅ read-only | Same | `include` | |
| C5 | Forward daily chains | Deribit API → parquet | Phase 1+ | ✅ ingested | Growing chain window | `include` | P-4 forward snapshot active |
| C6 | Skew / OI / max pain | Any vendor | — | ❌ | — | `exclude` | No reliable history; no proxies |
| C7 | Historical chain backfill | Tardis / CDD / etc. | — | ❌ | — | `exclude` | Unavailable |
| C8 | SOL option chains | Deribit | — | ⚠️ thin/short | — | `exclude` | D-15 |

**v1 options features (≤9 DVOL + 3 chain columns):** from DVOL — `dvol_30d`, `iv_minus_rv`, `dvol_rank_252` (core); `vol_of_vol`, `dvol_chg_7d`, `dvol_rank_90` (extended); from chains (Apr 2025+ only) — `atm_iv`, `term_slope`, `risk_reversal_25d` via `cryoquant/features/options.py`.

**Pre-2021 / pre-DVOL rows:** no options columns (NaN). Model relies on §A/B/D/H. **No synthetic vol-sell backtest** on missing chain dates.

---

## D. Macro — rates, FX, risk appetite (Goal 1; optional for Goal 2)

Already available via FRED / Yahoo / CBOE in CryoQuant. Proposal in SPEC is a **subset**; KICKOFF lists more.

### D.1 Proposed in SPEC (review each)

| ID | Series | Source | FRED alias / ticker | Start | CryoQuant | Decision | Notes |
|---|---|---|---|---|---|---|---|
| D1 | US Dollar (broad) | FRED | `DXY` → DTWEXBGS | 2010-01-01 | ✅ | **`include`** | Often negatively correlated with BTC |
| D2 | Yield curve 10Y-2Y | FRED | `YIELD_CURVE` / T10Y2Y | 2010-01-01 | ✅ | **`include`** | Recession / risk signal |
| D3 | SOFR | FRED | `SOFR` | 2018-04-01 | ✅ | **`include`** | Short-rate anchor post-LIBOR |
| D4 | VIX close | CBOE | `VIX_CLOSE` | 2010-01-01 | ✅ | **`include`** | Prefer CBOE over FRED VIXCLS for OHLC |
| D5 | S&P 500 proxy | Yahoo | `SPY` 1d | 2010-01-01 | ✅ | **`include`** | Risk-on/off |
| D6 | Gold proxy | Yahoo | `GLD` 1d | 2010-01-01 | ✅ | **`include`** | Alternative store of value |

### D.2 In KICKOFF but not in SPEC proposal — review if wanted

| ID | Series | Source | CryoQuant | Decision | Notes |
|---|---|---|---|---|---|
| D7 | US2Y / US10Y levels | FRED `US2Y`, `US10Y` | ✅ | **`exclude`** | Redundant with D2 spread |
| D8 | Fed balance sheet | FRED WALCL | ✅ (add alias) | **`exclude`** | Liquidity proxy — out of v1 macro pack |
| D9 | Nasdaq | Yahoo `QQQ` 1d | ✅ | **`exclude`** | Redundant with SPY risk-on signal |
| D10 | HY spread | FRED `HY_SPREAD` | ✅ | **`exclude`** | 2023+ history gap on FRED |
| D11 | NFCI / financial stress | FRED `NFCI`, `FIN_STRESS` | ✅ | **`exclude`** | Weekly regime — deferred complexity |
| D12 | CPI / PCE | FRED `CPI`, `PCE` | ✅ | **`exclude`** | Monthly release-date alignment burden |
| D13 | MOVE (bond vol) | External / Yahoo proxy | ❌ | **`exclude`** | No first-class connector |
| D14 | **FOMC decision days** | Fed published calendar → daily flags | ✅ ingested | **`include`** | **Event flags** on rate-decision days; see §D.3 |

**Locked (2026-06-28):** Minimal macro pack **D1–D6** + **D14 FOMC calendar**. Expanded regime series (D7–D13) excluded.

### §D.3 FOMC decision calendar (D14)

**Source:** Federal Reserve published FOMC calendars (`federalreserve.gov/monetarypolicy/fomccalendars.htm`), parsed into a static/refreshable calendar artifact.

**Output series (daily, UTC index aligned to BTC bars):**

| Column | Meaning |
|---|---|
| `is_fomc_decision_day` | `1` on the US session when the FOMC **announces** its rate decision (typically day 2 of a 2-day meeting, ~2:00 PM ET) |
| `days_until_fomc` | Calendar days to next decision day (optional derived in Phase 2) |
| `days_since_fomc` | Calendar days since last decision day (optional derived in Phase 2) |

**Alignment (two feature types):**

| Feature type | Examples | Lag rule |
|---|---|---|
| **Calendar schedule** | `is_fomc_decision_day`, `days_until_fomc`, `days_since_fomc`, `is_fomc_week` | **None.** Derived from Fed published `decision_date` list. Scheduled dates are public ≥1y ahead — not a lagged time series. Flag active from **00:00 UTC** on the decision date (captures pre-event + event-day regime). |
| **Outcome / surprise** (not in v1) | rate change, statement tone | Would require `available_utc` ≥ announcement (~2:00 PM ET). |

Phase 1 ingest stores sparse rows with `available_utc` for audit and optional post-announcement features later. **Phase 2 uses calendar semantics only.**

**Rationale:** FOMC *dates* are like holidays on a calendar; FOMC *decisions* are like earnings surprises. v1 uses only the calendar.

---

## E. US institutional demand — BTC ETF & corporate treasury (Goal 1)

> **Context:** US spot Bitcoin ETFs launched **2024-01-11**. Post-2024, a meaningful slice of BTC
> price discovery is US institutional flow (Creations/redemptions via IBIT, FBTC, GBTC, etc.).
> **Strategy, Inc.** (ticker `MSTR`, formerly MicroStrategy) is the largest public corporate BTC
> holder — purchases/sales are discrete demand shocks, usually disclosed via 8-K.

**Status (2026-06-28):** E1–E2, E4–E5 **`include`** and **ingested** via Farside + Strategy.com. E3 **`defer`**. SoSoValue **`exclude`**. E6–E8 `defer`/`exclude`.

**Alignment:** See **§E.1** — ingest stores `available_utc`; features use `align_series` backward
merge. Never join on raw trade/purchase dates.

### Platform survey (updated 2026-06-28)

| Platform | BTC ETF flows | MSTR / Strategy BTC txs | Cost | History depth | Verdict |
|---|---|---|---|---|---|
| **[Farside Investors](https://farside.co.uk/bitcoin-etf-flow-all-data/)** | ✅ daily table + per-ticker | ❌ | Free (website) | **632 td from 2024-01-11** | **✅ Ingested E1–E2** |
| **[Strategy.com/purchases](https://www.strategy.com/purchases)** | ❌ | ✅ official disclosure table | Free | **114 events from 2020-08-10** | **✅ Ingested E4–E5** |
| **[Parse.bot Farside API](https://parse.bot/marketplace/d1af202b-4969-4869-bcf2-d16d71525d36/farside-co-uk-api)** | ✅ wraps Farside | ❌ | Free 100 credits/mo | Full Jan 2024→ | Backup if scrape blocked (Cloudflare) |
| **[SoSoValue OpenAPI](https://sosovalue.gitbook.io/soso-value-api-doc)** | ⚠️ aggregate + per-ETF | ⚠️ MSTR endpoint | Free API key | **ETF: 30d hard cap** · MSTR: ~1y | **❌ Exclude** for backtest |
| **[CoinGlass](https://docs.coinglass.com/reference/etf-flows-history)** | ✅ flow-history API | ❌ | Paid ~$29/mo | Full | `defer` (D-3 override option) |
| **[DefiLlama Pro API](https://api-docs.defillama.com/)** | ✅ `/etfs/flows` | ✅ DAT/MSTR | $300/mo | Full | `defer` (D-3) |

**Recommendation:** **Farside** (E1–E3) + **Strategy.com** (E4–E5). Drop SoSoValue for institutional series. Keep §E.1 alignment rules unchanged.

### Proposed series

| ID | Series | Source | Start | CryoQuant | Enables | Decision | Notes |
|---|---|---|---|---|---|---|---|
| E1 | US BTC spot ETF **aggregate** daily net flow (USD) | **Farside** | 2024-01-11 | ✅ ingested | `total_net_inflow`, cum flow | **`include`** | 632 rows in `macro/farside/` |
| E2 | US BTC spot ETF **per-ticker** daily flows | **Farside** | 2024-01-11 | ✅ ingested | Issuer mix | **`include`** | 12 tickers incl. `BTC` (Grayscale mini); MSBT from 2025-04 |
| E3 | US BTC spot ETF AUM / net assets | — | 2024-01-11 | — | Level + Δ | **`defer`** | Farside is flows-only |
| E4 | **Strategy Inc (`MSTR`)** BTC acquisition events | **Strategy.com/purchases** | 2020-08-10 | ✅ ingested | `btc_acq`, `acq_cost` shocks | **`include`** | 114 events in `macro/strategy/` |
| E5 | **Strategy Inc** total BTC holdings (level) | **Strategy.com/purchases** | 2020-08-10 | ✅ ingested | Slow positioning | **`include`** | Step function from E4 |
| E6 | ETH spot ETF flows | SoSoValue `symbol=ETH` | 2024-07-23 | ❌ build | ETH institutional | `defer` | BTC-first |
| E7 | CoinGlass ETF bundle | CoinGlass API | 2024-01-11 | ❌ | — | `defer` | Paid (D-3) |
| E8 | DefiLlama ETF + DAT | DefiLlama Pro API | varies | ❌ | — | `defer` | $300/mo |

**Ingest (2026-06-28):**

- ✅ `cryoquant/data/sources/farside_etf.py` — scrape + Parse.bot fallback (`PARSE_API_KEY` optional).
- ✅ `cryoquant/data/sources/strategy_treasury.py` — `__NEXT_DATA__.bitcoinData`.
- Store: `macro/farside/etf_flow_*`, `macro/strategy/mstr_btc_*`.
- SoSoValue connector retained but **not in universe** (30d ETF cap).

### §E.1 Alignment specification (anti-lookahead)

**Bar convention (matches CryoQuant daily BTC):**

- Binance 1d bar **date** `T` = interval `[T 00:00 UTC, T+1 00:00 UTC)`.
- Feature at index `T` may use only data with **`available_utc ≤ T 00:00 UTC`**.
- Join via `cryoquant.features.align.align_series(..., method="asof")` (backward `merge_asof`).

**US calendar:** use `pandas_market_calendars` **NYSE** for US trading/business days (ETF flows skip US holidays/weekends).

#### ETF flows (E1–E3)

| Step | Rule |
|---|---|
| Raw `trade_date` | Farside / aggregator `date` = **US ETF session** the flow belongs to (not publication date). |
| Publication lag | Aggregators (Farside) publish day-*D* flow on the **next US business day**, typically after US cash close. |
| **`available_utc`** | `next_us_business_day(trade_date)` at **18:00 America/New_York** → convert to UTC. |
| Effect | Flow for US session Mon is **not** on BTC bar Tue 00:00 UTC; earliest BTC bar **Wed** 00:00 UTC (conservative). |
| Weekends | BTC bars Sat/Sun carry last known flow (stale); no fake same-day US flow on non-US days. |
| Staleness cap | `ffill_limit=5` calendar days on aligned ETF features (no ancient flow forward-filled forever). |

**Do not** shift by “lag 1 calendar day” only — that leaks on Mon/Fri boundaries. Always use **US business-day + 18:00 ET** rule above.

#### MSTR / Strategy treasury (E4–E5)

| Step | Rule |
|---|---|
| Raw `event_date` | Strategy.com `date` = **purchase/acquisition date** (may precede 8-K). |
| **`available_utc`** | `next_us_business_day(event_date)` at **14:00 America/New_York** → UTC. (Assumes disclosure next US session; conservative vs same-day.) |
| E4 event amounts | `btc_acq`, `acq_cost` are **sparse** — non-zero only on the bar at/after `available_utc`; **never** on raw `event_date`. |
| E5 holdings level | `btc_holding` forward-filled from each event's `available_utc`; **not** from purchase date. |
| Sales | If `btc_acq < 0` or API adds sale type, treat as outflow on same `available_utc` rule. Validate in Phase 1 QA. |

#### Derived features (H5–H6)

- Rolling sums / z-scores (H5) computed **after** alignment onto BTC bars — never roll on raw trade dates.
- MSTR dummies (H6) derived from aligned E4 only.

#### Phase 1 tests (required)

| Test | Assert |
|---|---|
| P1-T08a | ETF flow for `trade_date=Fri` not present on BTC bar `Sat/Sun/Mon` 00:00 UTC if Mon is next biz day |
| P1-T08b | MSTR `btc_acq` for event not on bar before `available_utc` |
| P1-T08c | `align_series` backward — no future `available_utc` on any bar |
| P2-T08 | Rolling `etf_flow_5d` at *t* uses only flows knowable ≤ *t* 00:00 UTC |

### v1 feature sketch (E1–E5 included)

| Feature | From | Notes |
|---|---|---|
| `etf_flow_1d_usd` | E1 (aligned) | Already lag-safe via §E.1 |
| `etf_flow_5d_usd` | H5 | Sum of aligned daily flows |
| `etf_flow_zscore_21d` | H5 | On aligned series |
| `etf_aum_usd` / `etf_aum_chg_1d` | E3 (aligned) | Level from lag-safe AUM |
| `mstr_btc_acq_1d` | E4 (aligned) | Sparse; includes sales if negative |
| `mstr_holdings_btc` | E5 (aligned) | Forward-filled post-event |

Pre-**2024-01-11** ETF columns are NaN. Pre-**~2020-08** MSTR columns are NaN. Not a backfill gap.

---

## F. Crypto-native sentiment & flows (free)

| ID | Series | Proposed source | CryoQuant | Enables | Decision | Notes |
|---|---|---|---|---|---|---|
| F1 | Fear & Greed Index | alternative.me API | ✅ ingested | Sentiment | **`include`** | Daily; easy API |
| F2 | Stablecoin supply (USDT+USDC) | DefiLlama **free** API | ✅ ingested | On-chain liquidity | **`include`** | Free stablecoin endpoint (not Pro ETF/DAT) |
| F3 | Total DeFi TVL | DefiLlama free API | ❌ build | Risk appetite | `defer` | Noisy; deferred |
| F4 | BTC dominance | CoinGecko / derive | ❌ | Regime | `defer` | Extra vendor |
| F5 | Total crypto market cap | CoinGecko | ❌ | Regime | `defer` | Extra vendor |

**Locked (2026-06-28):** F1 + F2 **include**; F3–F5 **defer**.

---

## G. Bitcoin network metrics (on-chain / L1)

> **Scope:** BTC only for v1. These are **L1 blockchain** metrics (not Lightning, not ETF/custodial
> flows — see §E for institutional demand). Goal 1 feature slice; optional for Goal 2.

**Locked (2026-06-28):** G1–G4 **`include`** via Coin Metrics Community API. G5–G6 `defer`; G7–G10 `exclude`/`defer`.

### G.0 What traders actually use (and what we should skip)

Professional on-chain analysis treats metrics as **regime / health context**, not T+1 price
triggers. Composite frameworks (e.g. [Bitcoin Barometer](https://www.themarketsunplugged.com/bitcoin-barometer-explained/),
CheckOnChain) combine 20+ series for **cycle positioning**, explicitly *not* directional
forecasting.

| Metric family | Trader use | Predictive value for daily ML | Free? |
|---|---|---|---|
| **Hash rate / difficulty** | Miner conviction, network security; rising HR through drawdowns = long-term commitment | **Slow** (weeks–months); weak for T+1d | ✅ |
| **Active / unique addresses** | “Network usage” proxy; historically correlated with adoption | **Degraded** — batching, Ordinals spikes, exchange batching, L2/off-chain activity | ✅ |
| **Transaction count / fees** | Congestion, usage intensity, fee market | **Moderate** short-term (fee spikes); noisy | ✅ |
| **NVT / transfer volume** | Valuation vs usage (“crypto P/E”); regime extremes | Regime only; thresholds **drift** post-ETF | ❌ free (needs adjusted USD volume) |
| **MVRV / SOPR / realized cap** | Cycle tops/bottoms, profit-taking | Regime; **paid** on Glassnode/CryptoQuant | ❌ D-3 |
| **Exchange net flow** | Sell-side pressure | Popular but **free data unreliable**; entity labeling hard | ❌ defer |
| **“New accounts”** | N/A on Bitcoin — proxies are **new/active addresses** | Very noisy; entity clustering errors | partial |

**Implication for BTCpredict:** include a **small free L1 pack** (miner + usage), not a full
on-chain valuation stack. Post-2024, **US ETF flows (§E)** are the primary institutional demand
signal; L1 metrics complement, not replace.

### G.1 Source survey (verified)

| Platform | Metrics | History | Cost | Notes |
|---|---|---|---|---|
| **[Coin Metrics Community API](https://docs.coinmetrics.io/access-our-data/api)** | `HashRate`, `AdrActCnt`, `TxCnt`, `FeeTotNtv`, `BlkCnt`, `SplyCur`, `AdrBalCnt` | **2018+** (verified live) | Free, no key; `community-api.coinmetrics.io`; CC license | **Recommended primary** |
| **[blockchain.com Charts API](https://www.blockchain.com/api/charts_api)** | hash-rate, n-transactions, n-unique-addresses, difficulty, miners-revenue, est. tx volume USD | **2009+** (`timespan=all`) | Free, no key | Good backfill / cross-check; chart JSON less normalized than CM |
| **mempool.space API** | Mempool vsize, fee estimates, pool hashrate | Real-time + weeks | Free | **Poor daily history** — defer for v1 backtest |
| **Glassnode / CryptoQuant** | MVRV, SOPR, NVT, exchange flows, entity-adjusted active addresses | Long | Paid | `exclude` (D-3) |

**Coin Metrics community — confirmed working (2026-06-28):** `HashRate`, `AdrActCnt`, `TxCnt`,
`FeeTotNtv`, `BlkCnt`. **Not** on free tier: `TxTfrValAdjUSD` (NVT denominator), `FeeTotUSD`,
`AdrNewCnt`, `DiffMean`.

### G.2 Series register

| ID | Series | Source | Start | CryoQuant | Enables | Decision | Notes |
|---|---|---|---|---|---|---|---|
| G1 | **Hash rate** (TH/s) | Coin Metrics `HashRate` | 2018-01-01 | ✅ ingested | Miner security / conviction | **`include`** | Slow; use Δ and z-score, not raw level |
| G2 | **Active addresses** (daily) | Coin Metrics `AdrActCnt` | 2018-01-01 | ✅ ingested | Usage / adoption proxy | **`include`** | Not “new accounts”; see G.0 caveats |
| G3 | **Transaction count** | Coin Metrics `TxCnt` | 2018-01-01 | ✅ ingested | Network activity | **`include`** | Includes non-economic txs |
| G4 | **Total fees (BTC)** | Coin Metrics `FeeTotNtv` | 2018-01-01 | ✅ ingested | Congestion / fee-market pressure | **`include`** | Usage intensity |
| G5 | **Difficulty** | blockchain.com `difficulty` chart | 2018-01-01 | ❌ build | Redundant with G1 | `defer` | High corr with hash rate |
| G6 | **Unique addresses** | blockchain.com `n-unique-addresses` | 2018-01-01 | ❌ | Alt to G2 | `defer` | Correlated with G2 |
| G7 | NVT / adjusted transfer volume | CM Pro / Glassnode | — | ❌ | Valuation regime | `exclude` | Needs paid `TxTfrValAdjUSD` |
| G8 | MVRV, SOPR, realized cap | Glassnode / CryptoQuant | — | ❌ | Cycle positioning | `exclude` | D-3 |
| G9 | Exchange net flow | Glassnode / CM Pro | — | ❌ | Positioning | `exclude` | Free tier unreliable |
| G10 | Mempool / fee oracle | mempool.space | — | ❌ | Real-time only | `defer` | No long daily history |

**Ingest:** `https://community-api.coinmetrics.io/v4/timeseries/asset-metrics` — no API key;
rate limit 10 req / 6 s. Apply §G.3 lag on ingest (`chain_date` → `available_utc`).

### G.3 Alignment (anti-lookahead)

Daily L1 metrics aggregate **confirmed blocks over UTC calendar day *D***. That day is not
complete until **D+1 00:00 UTC**.

| Step | Rule |
|---|---|
| Raw `chain_date` | Coin Metrics `time` field = UTC day the metric covers |
| **`available_utc`** | `(chain_date + 1 day) @ 00:00 UTC` — earliest moment the day-*D* aggregate is final |
| Join to BTC bars | `align_series(btc_daily_index, series, method="asof")` on `available_utc` |
| Effect | Feature on BTC bar **2024-06-02** uses on-chain stats for **2024-06-01** at earliest |
| Derived rolls | Rolling means / z-scores computed **after** lag shift (same pattern as §E.1 H5) |

No intraday mempool data in v1 — avoids mixed-frequency leakage.

### G.4 v1 feature sketch (G1–G4 locked)

| Feature | From | Notes |
|---|---|---|
| `hr_change_7d`, `hr_zscore_90d` | G1 | Miner trend / regime |
| `active_addr_change_7d`, `active_addr_zscore_30d` | G2 | Usage momentum |
| `tx_cnt_zscore_21d` | G3 | Activity spike detection |
| `fee_btc_zscore_21d` | G4 | Congestion proxy |
| `price_vs_usage_divergence` | H7 derived | e.g. price Δ minus active-addr Δ (optional) |

Target: **≤8 network-tagged columns** (4 base + up to 4 derived). Do not forward-fill more than **7 days** (`ffill_limit=7`).

---

## H. Derived (no extra ingest)

| ID | Series | From | Decision | Notes |
|---|---|---|---|---|
| H1 | ETH/BTC ratio | A3 ÷ A1 | **`include`** | Trivial once OHLCV exists |
| H2 | SOL/BTC ratio | A5 ÷ A1 | **`include`** | |
| H3 | Realized vol features | OHLCV | **`include`** | Via `cryoquant.features.primitives` |
| H4 | IV − RV (VRP) | C1/C2 (DVOL) + H3 | **`include`** | `iv_minus_rv` from DVOL − RV |
| H5 | ETF flow momentum | E1 | **`include`** | e.g. 5d sum, 21d z-score (derived) |
| H6 | MSTR event / holdings features | E4, E5 | **`include`** | Sparse acq + ffilled holdings; **after** §E.1 lag |
| H7 | Network momentum / divergence | G1–G4 | **`include`** | z-scores, Δ7d; **after** §G.3 lag |

Derived rows follow base series automatically — no separate ingest decision unless you want to exclude from features.

---

## I. Explicitly out of scope (D-3 / D-15)

| Item | Reason |
|---|---|
| Glassnode, CryptoQuant, Nansen | Paid; deferred unless you override D-3 |
| Tardis / CDD options backfill | Unavailable; not in scope |
| Options skew/OI/max-pain proxies | No reliable source; excluded per P-2 |
| Synthetic BS vol-sell backtest | Not real chain data; excluded |
| SOL Deribit options | D-15; thin market |
| Intraday macro | Misalignment risk; daily macro only |
| CoinGlass API (ETF/options) | Paid from ~$29/mo; D-3 |
| DefiLlama Pro API (ETF/DAT) | $300/mo; free DefiLlama API lacks ETF/DAT endpoints |
| Paid equity/options data (Bloomberg, etc.) | Not in mandate |

---

## J. Review checklist (sign-off — completed 2026-06-28)

Phase 1 sign-off criteria (all met):

- [x] Every row in sections A–G has Decision ≠ `pending`
- [x] A1–A6 (Binance canonical OHLCV daily + hourly); C1–C5 locked for Goal 2 options slice
- [x] A1, A3, A5 approved for Goal 1 SOL directional (D-10)
- [x] B1–B5 perp funding + OI (OI subject to §B.1 API window)
- [x] Macro D1–D6 + D14 FOMC; D7–D13 excluded
- [x] Institutional pack **E1–E5** locked; network pack **G1–G4** locked; §E.1 / §G.3 alignment tests in Phase 1/2
- [x] F1–F2 include; F3–F5 defer
- [x] Start dates consciously chosen (not copy-pasted)
- [x] Release-date / §E.1 / §G.3 / §D.3 alignment documented
- [x] `universe.yaml` regenerated from approved rows only
- [x] `config.yaml`: `data_sources_reviewed: true` and `data_sources_review_date: 2026-06-28`

### Phase 1 completion (2026-06-28)

- [x] Full backfill via `run_phase1_ingest.py` — **33 series ok**, H1/H2 skipped, E3 deferred
- [x] B3/B4 OI from **Xoomar Pulse** — BTC from 2021-01-02, ETH from 2021-12-01
- [x] **E1–E2** ETF flows from **Farside** — 632 aggregate rows (2024-01-11 → 2026-06-26)
- [x] **E4–E5** MSTR from **Strategy.com** — 114 events (2020-08-10 → 2026-06-22)
- [x] SoSoValue **excluded** (30d ETF API cap); connectors: `farside_etf.py`, `strategy_treasury.py`
- [x] Unit tests: `test_phase1_ingest.py` (25 passed)
- [x] **Phase 1 QA:** `run_phase1_qa.py` — 0 errors, 12 warnings (see `reports/phase1_qa_report.txt`)
- [x] E2 ticker list includes **`BTC`** (Grayscale mini) — 12 tickers ingested; `etf_flow_BTC` from 2024-07-31
- [x] **Phase 2 catalog:** `FEATURE_CATALOG.md` + `features.yaml` signed off 2026-06-28
- [x] **Phase 2 build:** `features.parquet` + `features_schema.json` on disk; QA pass 2026-06-28
- [x] **Phase 2 manual spot-check:** `btc_rsi_14`, `btc_dvol_30d` vs TradingView/Deribit (2026-06-28)

---

## K. Review decisions (resolved 2026-06-28)

1. **Canonical price:** ✅ Binance spot only (A1–A6).
2. **Hourly bars:** ✅ Include A2, A4, A6 now (intraday feature engineering).
3. **Macro footprint:** ✅ D1–D6 + D14 FOMC calendar; D7–D13 excluded (D9 Nasdaq redundant with SPY).
4. **Institutional flows:** ✅ E1–E2 Farside + E4–E5 Strategy.com ingested; SoSoValue excluded; E3 deferred.
5. **Funding vs OI:** ✅ Full stack B1–B5; OI via **Xoomar Pulse** from 2021 (§B.1); pre-2021 use funding only.
6. **Bitcoin network metrics:** ✅ G1–G4 locked (Coin Metrics Community API).
7. **Crypto-alt connectors:** ✅ F1 + F2 in Phase 1; F3–F5 deferred.
8. **History start:** ✅ Align OHLCV/network with `dev_start: 2018-01-01`; macro from 2010 where free history exists.

*(Options C1–C8 locked 2026-06-28; institutional E1–E5 locked; network G1–G4 locked.)*

---

*Signed off 2026-06-28. Phase 1 ingest + QA complete 2026-06-28. Phase 2 feature build complete 2026-06-28. `universe.yaml` + `FEATURE_CATALOG.md` + `data/ingest_manifest.json` are authoritative.*
