---
name: BTCpredict v1 — Feature catalog
status: signed off (2026-06-28)
version: 1
review_date: "2026-06-28"
upstream: DATA_SOURCES.md, OPTIONS_SURFACE_PROXY_PROPOSAL.md, KICKOFF §5.3, SPEC §8.1
machine_readable: features.yaml
config_gate: config.yaml → phase2_complete: true
build_status: complete (2026-06-28)
---

# BTCpredict v1 — Feature catalog

**Purpose:** Authoritative register of every column in `data/features.parquet`. One row in this doc = one feature column. Implementation (`panel_build.py`, builders) must match this file.

**Panel shape:** wide table, one row per `(timestamp, asset)` where `asset ∈ {BTC, ETH, SOL}`. Shared/global features are **replicated** on each asset row (same value on BTC/ETH/SOL rows for a given timestamp).

**Sign-off:** ✅ **2026-06-28** — catalog: `phase2_catalog_reviewed: true` · build: `phase2_complete: true`

---

## Conventions

| Field | Meaning |
|---|---|
| **Tag** | **`core`** = default Phase 4 model candidate (KICKOFF D-6, §7.3). **`extended`** = built in Phase 2, use for ablation / selection only; drop first under budget pressure. |
| **Lag rule** | How causality is enforced at daily bar `T` (UTC midnight = bar open for interval `[T, T+1)`). |
| **Warmup** | Minimum bars before feature is finite (excluding source `available_from`). |
| **Scope** | `per_asset` = different value per BTC/ETH/SOL; `global` = same on all rows; `btc_only` = non-NaN only on BTC rows. |
| **available_from** | First UTC date feature can be non-NaN (source history + alignment + warmup). |

**Lag rules (locked):**

- **Price-derived (`TrendFeatures`):** computed on closed daily bar; `.shift(1)` so feature at `T` uses data through `T-1` close.
- **Macro (D1–D6):** `align_series(..., method="asof")` on daily index; business-day series may stale over weekends (no forward-fill from future).
- **Funding (B*):** last funding rate with `timestamp ≤ T 00:00 UTC`.
- **ETF (E1):** §E.1 — flow for US session `D` visible from `next_us_business_day(D) @ 18:00 ET`; `ffill_limit=5` calendar days after align.
- **MSTR (E4/E5):** §E.1 — events from `available_utc`; sparse acq, ffilled holdings.
- **On-chain (G*):** §G.3 — day-`D` metric available `(D+1) @ 00:00 UTC`.
- **FOMC (D14):** **calendar schedule** — no lag (public dates); see Layer D note. Do not conflate with rate *outcome*.
- **DVOL (C1/C2):** daily index close aligned as-of `T` (same-day close known at end of UTC day — conservative: optional extra `shift(1)` if we treat DVOL as EOD publication; **v1 uses asof without extra shift**, matching macro).
- **Chains (C3/C4):** entry-time snapshot only; **NaN before 2025-04-11** (hold-out era).

**UTC day vs tradfi close (v1 trade-off):**

- **Crypto bars:** ``T 00:00 UTC`` = full 24h window; close at next UTC midnight.
- **Tradfi (SPY, FRED, VIX):** same **calendar date label** at ``00:00 UTC``, but value is
  that asset's **session/reference close** (e.g. NYSE ~16:00 ET) — not the same instant as
  the crypto UTC boundary.
- **Join rule:** backward ``align_series`` onto the crypto index — causally safe, but macro
  can be **stale** over US weekends/holidays when BTC still prints daily bars.
- **Manual spot-checks (2026-06-28):** ``btc_rsi_14`` vs TradingView Binance UTC daily
  (feature at ``T`` → RSI on bar ``T-1``); ``btc_dvol_30d`` vs Deribit DVOL (same date ``T``).

---

## Era matrix (dev vs hold-out)

```
Dev:      2018-01-01 ──────────────────────── 2024-05-31
Hold-out:                    2024-06-01 ─────── present
DVOL BTC:           2021-03-31 ──────────────────────────
DVOL ETH:                    2022-01-01 ───────────────
ETF E1:                              2024-01-11 ────────  (~102 dev days)
Chains:                                              2025-04-11 ──
```

| Era | Available feature layers |
|---|---|
| 2018 – 2021-03 | A trend, B funding (2020+), D macro, F sentiment, G network, H cross |
| 2021-03 – 2024-01 | + DVOL (BTC), OI (2021+), ETH DVOL (2022+) |
| 2024-01 – 2024-05 | + ETF flows (thin) |
| 2024-06+ (hold-out) | all above + growing chain columns |
| Pre-2021 | OI columns NaN; pre-2020 SOL funding NaN |

---

---

## Tier summary (Phase 4 default)

| Tag | Count | Role |
|---|---:|---|
| **core** | **~62** | Recommended starting set per model head (~30–100 after head-specific subset + correlation prune) |
| **extended** | **~75** | Full pantry — selection, ablations, optional heads |
| **Total** | **~137** | All columns in `features.parquet` |

**Head hints (Phase 4, not build-time):**

| Head | Start from |
|---|---|
| Goal 1 directional (all assets) | core trend (×3) + B + C + D + E |
| Goal 2 vol / exceedance (BTC/ETH) | core trend + **F DVOL core** + rv_* + macro |
| SOL pooled | shared global/core + `{sol}_*` trend core only |

---

## Layer A — Price & trend (`TrendFeatures`, per asset)

**Builder:** `cryoquant.features.trend_builders.TrendFeatures` v1  
**Inputs:** A1/A3/A5 daily OHLCV + optional A2/A4/A6 hourly for HTF add-ons  
**Scope:** per_asset (column names prefixed `{asset_lower}_` in parquet, e.g. `btc_rsi_14`)

| Tag | Feature | Description | Warmup | available_from (BTC) |
|---|---|---|---:|---|
| extended | `{a}_ret_1d` | 1-day % return | 2 | dev_start + 2d |
| core | `{a}_ret_5d` | 5-day % return | 6 | + 6d |
| core | `{a}_ret_20d` | 20-day % return | 21 | + 21d |
| core | `{a}_close_vs_ema20_pct` | Distance to EMA20 | 21 | + 21d |
| extended | `{a}_close_vs_ema50_pct` | Distance to EMA50 | 51 | + 51d |
| extended | `{a}_close_vs_ema200_pct` | Distance to EMA200 | 201 | + 201d |
| core | `{a}_donchian_pos_55` | Position in 55d channel | 56 | + 56d |
| extended | `{a}_donchian_pos_20` | Position in 20d channel | 21 | + 21d |
| extended | `{a}_bb_pct_b` | Bollinger %B | 21 | + 21d |
| core | `{a}_bb_width` | Bollinger width | 21 | + 21d |
| core | `{a}_rsi_14` | RSI 14 | 15 | + 15d |
| extended | `{a}_adx_14` | ADX 14 | 28 | + 28d |
| extended | `{a}_macd_hist_norm` | MACD hist / ATR | 35 | + 35d |
| extended | `{a}_slope_10d_pct` | Linreg slope 10d | 11 | + 11d |
| core | `{a}_rv_24` | Realized vol 24d ann. | 25 | + 25d |
| core | `{a}_rv_rank` | RV percentile 252d | 276 | + 276d |
| core | `{a}_atr_pct` | ATR % of price | 15 | + 15d |
| extended | `{a}_vol_ratio` | Volume / 20d mean | 21 | + 21d |
| extended | `{a}_vol_z` | Volume z-score 24d | 25 | + 25d |
| extended | `{a}_obv_vs_ema` | OBV vs EMA20 | 21 | + 21d |
| core | `{a}_trend_regime` | Composite trend state | 200 | + 200d |
| core | `{a}_vol_expansion` | Vol expansion flag | 25 | + 25d |
| extended | `{a}_close_52w_hi_pct` | % below 52w high | 253 | + 253d |
| core | `{a}_dow` | Day of week 0–6 | 0 | dev_start |
| extended | `{a}_is_us_session` | US session flag | 0 | dev_start |
| extended | `{a}_close_vs_ema24_1h_pct` | 1h EMA24 distance (HTF) | 25 | 2020-01-01 + 25d |
| extended | `{a}_ret_4h` | 4h return aligned to daily | 5 | 2020-01-01 + 5d |
| extended | `{a}_vol_z_1h` | 1h volume z | 25 | 2020-01-01 + 25d |

**Count:** 28 cols × 3 assets = **84** (**33 core** + **51 extended** per full panel).

---

## Layer B — Cross-asset (shared, replicated on each row)

**Builder:** `CrossAssetFeatures` + study-specific ratios  
**Scope:** global (identical on BTC/ETH/SOL rows)

| Tag | Feature | Source | Formula / notes | available_from |
|---|---|---|---|---|
| core | `eth_btc_ratio` | H1 | ETH close / BTC close | 2018-01-02 |
| core | `eth_btc_ratio_chg_7d` | H1 | 7d % change of ratio | + 8d |
| core | `sol_btc_ratio` | H2 | SOL close / BTC close | 2020-08-01 (SOL listing) |
| core | `sol_btc_ratio_chg_7d` | H2 | 7d % change | SOL start + 8d |
| core | `rs_vs_spy_20d` | A1, D5 | 20d relative strength vs SPY | 2018-01-22 |
| extended | `rs_vs_spy_60d` | A1, D5 | 60d RS vs SPY | 2018-03-02 |
| extended | `gld_btc_ratio` | D6, A1 | GLD / BTC | 2018-01-02 |

**Count:** 7 (**5 core**, 2 extended)

---

## Layer C — Crypto-native (`CryptoFeatures`, new)

**Builder:** `cryoquant.features.crypto_builders.CryptoFeatures` v1  
**Scope:** mix of per_asset and global

### Per-asset (funding & OI)

| Tag | Feature | Source | Asset | available_from |
|---|---|---|---|---|
| core | `{a}_funding_rate` | B1/B2/B5 | BTC/ETH/SOL | BTC/ETH 2020-01-01; SOL 2022-01-01 |
| core | `{a}_funding_z21` | B* | same | + 22d |
| core | `{a}_oi_usd` | B3/B4 | BTC, ETH only | BTC 2021-01-02; ETH 2021-12-01 |
| extended | `{a}_oi_chg_7d` | B3/B4 | BTC, ETH | same + 8d |

### Global sentiment & liquidity

| Tag | Feature | Source | available_from |
|---|---|---|---|
| core | `fear_greed` | F1 | 2018-02-01 |
| core | `fear_greed_z21` | F1 | + 22d |
| extended | `stablecoin_supply` | F2 | 2018-01-01 |
| core | `stablecoin_chg_7d_pct` | F2 | + 8d |
| extended | `stablecoin_z30` | F2 | + 31d |

### Institutional (BTC-global, §E.1 aligned)

| Tag | Feature | Source | available_from | Dev note |
|---|---|---|---|---|
| extended | `etf_flow_1d_usd` | E1 | 2024-01-11 | **102 dev days only** |
| extended | `etf_flow_5d_usd` | E1 | 2024-01-16 | thin sample |
| extended | `etf_flow_z21` | E1 | 2024-02-01 | thin sample |
| extended | `mstr_btc_acq` | E4 | 2020-08-11 (after lag) | sparse events |
| extended | `mstr_holdings_btc` | E5 | 2020-08-11 | step function |

**Count:** ~18 (**8 core** per-asset funding/OI×3 + 4 global core + 5 extended institutional; OI core counts for BTC/ETH rows only)

---

## Layer D — Macro regime (adapted `MacroFeatures`)

**Builder:** study wrapper around `MacroFeatures` + SOFR + FOMC  
**Scope:** global

| Tag | Feature | Source ID | available_from |
|---|---|---|---|
| extended | `dxy_level` | D1 | 2018-01-02 |
| core | `dxy_ema_dir` | D1 | + 60d |
| core | `yc_sign` | D2 T10Y2Y | 2018-01-02 |
| core | `yc_trend` | D2 | + 20d |
| core | `sofr_level` | D3 | 2018-04-03 |
| extended | `sofr_chg_63d` | D3 | + 64d |
| extended | `vix_level` | D4 | 2018-01-02 |
| core | `vix_z20` | D4 | + 21d |
| core | `macro_risk_off` | D4 (+ optional D2) | + 21d |
| core | `is_fomc_decision_day` | D14 | 2018-01-01 |
| core | `days_until_fomc` | D14 derived | 2018-01-01 |
| extended | `days_since_fomc` | D14 derived | 2018-01-01 |
| extended | `is_fomc_week` | D14 derived | 2018-01-01 |

**FOMC modeling note (calendar vs time series):** D14 is a **deterministic event calendar**, not a lagged macro release like CPI or ETF flows. The Fed publishes meeting dates roughly a year ahead; at any historical bar `T` a trader could look up “next FOMC is on date X”. Using `days_until_fomc` or `is_fomc_decision_day` from that schedule is **not lookahead** — you are not using the future *rate decision*, only the future *scheduled date*.

What **would** be lookahead (excluded from v1): hike/cut/hold, dot plot, statement surprise — only known after ~2:00 PM ET on decision day. Phase 1 ingest still stores `available_utc` on sparse rows for audit; Phase 2 **derives calendar features from `decision_date` only**, ignoring announcement-time lag.

**P2-T02 exception:** generic “shift timestamp +1d” lookahead tests do not apply to pure calendar columns; test separately that calendar features at `T` match the Fed schedule known at `T`.

**Excluded (not in universe):** DGS10, HY spread, CPI, NFCI.

**Count:** 13 (**8 core**, 5 extended)

---

## Layer E — Network (`NetworkFeatures`, BTC-only values)

**Builder:** `crypto_builders` network section  
**Scope:** btc_only (NaN on ETH/SOL rows)

| Tag | Feature | Source | available_from |
|---|---|---|---|
| core | `hr_change_7d` | G1 | 2018-01-09 (+ §G.3 lag) |
| extended | `hr_zscore_90d` | G1 | + 97d |
| core | `active_addr_change_7d` | G2 | 2018-01-09 |
| extended | `active_addr_z30` | G2 | + 37d |
| extended | `tx_cnt_z21` | G3 | + 28d |
| extended | `fee_btc_z21` | G4 | + 28d |

**Count:** 6 (**2 core**, 4 extended)

---

## Layer F — Options (Goal 2 slice)

**Builder:** `options.dvol_features()` + gated `options.py` chain fns  
**Scope:** per_asset (BTC/ETH only; SOL NaN)

### Dev-trainable (DVOL)

| Tag | Feature | Source | BTC from | ETH from |
|---|---|---|---|---|
| core | `{a}_dvol_30d` | C1/C2 | 2021-03-31 | 2022-01-01 |
| core | `{a}_iv_minus_rv` | C1/C2 + `{a}_rv_24` | 2021-03-31 | 2022-01-01 |
| core | `{a}_dvol_rank_252` | C1/C2 rolling pct rank | 2021-12-08 (+252d) | 2022-09-10 (+252d) |
| extended | `{a}_vol_of_vol` | C1/C2 rolling std | 2021-04-30 | 2022-02-01 |
| extended | `{a}_dvol_chg_7d` | C1/C2 pct change | 2021-04-07 (+8d) | 2022-01-08 (+8d) |
| extended | `{a}_dvol_rank_90` | C1/C2 rolling pct rank | 2021-06-29 (+90d) | 2022-04-01 (+90d) |

**Lag (DVOL family):** asof calendar date `T` — same rule as `{a}_dvol_30d` (no extra `shift(1)` beyond ingest alignment). `{a}_dvol_rank_*` uses only DVOL observations ≤ `T` in each window; scale **0–1** (same convention as `{a}_rv_rank`).

### Hold-out only (chains — NaN on dev by design)

| Tag | Feature | Source | available_from |
|---|---|---|---|
| extended | `{a}_atm_iv_30d` | C3/C4 | **2025-04-11** |
| extended | `{a}_term_slope` | C3/C4 | **2025-04-11** |
| extended | `{a}_risk_reversal_25d` | C3/C4 | **2025-04-11** |

**Meta column (per row):** `options_source` ∈ `{none, dvol, chain}` — tag **extended** (diagnostic, not a model input).

**Count:** 9 value cols + 1 meta (**6 core** DVOL×2 assets on BTC/ETH rows + **12 extended** DVOL/chain×2 assets)

---

## Summary counts

| Layer | Total | core | extended |
|---|---:|---:|---:|
| A Trend × 3 | 84 | 33 | 51 |
| B Cross-asset | 7 | 5 | 2 |
| C Crypto-native | 18 | 8† | 10† |
| D Macro | 13 | 8 | 5 |
| E Network | 6 | 2 | 4 |
| F Options | 9 + meta | 6‡ | 13‡ |
| **Total** | **~137** | **~62** | **~75** |

† C core: funding+OI per asset (10 cols across 3 assets) + 4 global sentiment; extended: OI chg, stables level/z, ETF, MSTR.  
‡ F core: 3 DVOL features × 2 assets (BTC/ETH rows); extended: 3 DVOL (vol_of_vol, chg, rank_90) + 3 chain × 2 assets + `options_source` meta.

Phase 2 builds **all** columns. Phase 4 starts from **core** (~62), prunes correlation, adds **extended** only if OOS improves (KICKOFF §7.3).

---

## Outputs (Phase 2 deliverables)

| Artifact | Description | Status |
|---|---|:---:|
| `data/features.parquet` | Long `(timestamp, asset, …features…)` — 8,347 rows × 162 cols (2026-06-28, Layer F amended) | ✅ |
| `data/features_schema.json` | Column list, core/extended tags; 0 missing vs catalog | ✅ |
| `reports/phase2_qa_report.txt` | Warmup, finiteness, lookahead tests | ✅ |
| `data/phase2_qa_report.json` | Machine-readable QA (0 errors) | ✅ |

---

## Explicitly out of scope (v1)

- tsfresh / featuretools auto-generation
- CPI, HY spread, Nasdaq-only macro (D7–D13)
- E3 ETF AUM, ETH ETF flows (E6)
- Chain features on dev period (no backfill)
- SOL options / SOL DVOL
- Hourly bars as modeling cadence (hourly → daily aggregates only)

---

## Review checklist (signed off 2026-06-28)

- [x] Column set matches study goals (Goal 1 full dev; Goal 2 DVOL on dev, chains hold-out)
- [x] ETF thin-sample (102 dev days) acceptable as optional **extended** features
- [x] Network features BTC-only on ETH/SOL rows is acceptable
- [x] Chain features NaN on entire dev window is acceptable
- [x] FOMC modeled as public calendar (no announcement lag on schedule features)
- [x] **core / extended** tags (core ~62 as Phase 4 starting set)
- [x] Raw ~137 → select ≤100 in Phase 4 is acceptable

---

## Implementation notes (2026-06-28)

Built per SPEC §8. Noteworthy vs catalog intent:

- **Panel shape:** Long format — one row per `(timestamp, asset)`; global features replicated across BTC/ETH/SOL rows.
- **Chain columns:** Populated for **`btc_*` only** — CryoBacktester parquets on disk are BTC-underlying; `eth_*` chain features are NaN (columns present).
- **SOL options/OI:** NaN by design (no SOL DVOL/chains in v1; OI not ingested for SOL).
- **FOMC:** Calendar schedule features only (`is_fomc_decision_day`, `days_until_fomc`, etc.); sparse announcement rows from Phase 1 not used for v1 features.
- **Build time:** ~2.4 min full rebuild (439 chain dates). See SPEC §8.4 for full bug-fix log.
- **Manual validation (2026-06-28):** ``btc_rsi_14`` and ``btc_dvol_30d`` spot-checked vs
  TradingView / Deribit — confirmed.
- **Catalog amendment (2026-06-28):** Layer F — added ``dvol_rank_252`` (core),
  ``dvol_rank_90`` + ``dvol_chg_7d`` (extended); demoted ``vol_of_vol`` to extended
  (Deribit IV percentile / CryoTrader IVR convention).

---

*Signed off 2026-06-28. Implementation complete 2026-06-28 (SPEC §8 steps 2.1–2.7).*
*Catalog amendment 2026-06-28 (Layer F IV percentile features).*
