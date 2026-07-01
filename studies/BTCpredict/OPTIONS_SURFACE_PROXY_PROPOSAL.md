---
name: BTCpredict — Options Data (Minimal Reliable Scope)
status: locked (2026-06-28); Phase 1 ingest complete (2026-06-28); Phase 2 features complete (2026-06-28)
upstream: DATA_SOURCES.md §C, KICKOFF D-3, SPEC Phases 1–2 & 6
principle: >
  Options-derived data is one signal among many (price, macro, funding, RV).
  Include only series we reliably have. No backfill, no paid vendors, no
  synthetic substitutes for missing chain history.
---

# Options data — minimal reliable scope

## 1. Principle (locked)

Options market structure is **one input** to the forecast engine, not the spine of the study.

| Do | Don't |
|---|---|
| Ingest **verified, live sources** we can maintain | Chase historical chain backfill (Tardis, CDD Plus+, etc.) |
| Use **DVOL** as the only long-history implied-vol signal | Fabricate skew, term structure, max pain, or OI from proxies |
| Compute chain features **only where parquets exist** | Run synthetic Black–Scholes vol-sell backtests on missing eras |
| Train models primarily on **reliable core data** (§A/B/D/G) | Let Goal 2 options requirements block Goal 1 |

**Locked decisions (2026-06-28):**

| ID | Decision |
|---|---|
| **P-1** | ✅ DVOL is the ATM IV signal for 2021–2025-04 (BTC), 2022+ (ETH) |
| **P-2** | ✅ Defer skew, term slope, max pain, options OI — **exclude** unless computed from local chains |
| **P-3** | ✅ **No backfill.** Chain backtest only on dates we have parquets (~Apr 2025+). Accept short N. |
| **P-4** | ✅ Forward daily chain ingest from Deribit API (stop gap widening) |

---

## 2. What we reliably have

| Series | Source | Coverage | Reliable? |
|---|---|---|---|
| **BTC DVOL** (30d IV index) | Deribit `get_volatility_index_data` | 2021-03-31 → present | ✅ API verified |
| **ETH DVOL** | Same | ~2022-01-01 → present | ✅ API verified |
| **BTC/ETH option chains** | CryoBacktester parquets | ~2025-04-01 → present | ✅ Local files |
| **Forward chains** | Deribit API daily snapshot | Phase 1+ → growing | ✅ Ingested (forward snapshot active) |

**Not reliable — excluded from v1:**

| Series | Why excluded |
|---|---|
| Historical chains (pre-Apr 2025) | Not in our store; Tardis **unavailable** |
| Skew / term slope (pre-chain) | No free historical source; **no proxy substitutes** |
| Max pain, options OI aggregates | Same |
| Deribit `get_historical_volatility` | Only ~384-day rolling window — not a backfill |
| Glassnode / Laevitas / CoinGlass | Paid; out of scope (D-3) |
| Synthetic BS vol-sell backtest | Not real chain data — **out of scope** |

---

## 3. Coverage vs frozen splits

```
Dev:      2018-01-01 ──────────────────────── 2024-05-31
Hold-out:                    2024-06-01 ──────────────────── present
DVOL:              2021-03 ───────────────────────────────── present
Chains:                                          ~2025-04 ── present
```

| Era | Options features available | Chain backtest |
|---|---|---|
| 2018–2021-03 | **None** (model uses RV, VIX, macro, funding — not options) | ❌ |
| 2021-03–2025-04 | **DVOL only** (+ derived VRP, vol-of-vol) | ❌ |
| 2025-04+ | DVOL + **chain features** where parquets exist | ✅ |

All chain parquets fall in **hold-out** (after 2024-06-01). Phase 6 dev validation for Goal 2 uses **model calibration and exceedance metrics**, not chain P&L. Phase 7 is the first chain-accurate short-vol backtest.

---

## 4. Options feature set (small, explicit)

### 4.1 From DVOL (include in v1)

| Feature | Input | Start (BTC) | Tier | Notes |
|---|---|---|---|---|
| `dvol_30d` | DVOL close | 2021-03-31 | core | Primary implied-vol level |
| `iv_minus_rv` | DVOL − HAR-RV | 2021-03-31 | core | VRP; RV from Binance OHLCV (§G3) |
| `dvol_rank_252` | Rolling pct rank(DVOL, 252d) | 2021-12-08 | core | IV percentile (Deribit IVR convention; 0–1) |
| `vol_of_vol` | Rolling std(DVOL) | 2021-04-30 | extended | IV instability |
| `dvol_chg_7d` | pct_change(DVOL, 7d) | 2021-04-07 | extended | 7-day IV change (CryoTrader) |
| `dvol_rank_90` | Rolling pct rank(DVOL, 90d) | 2021-06-29 | extended | Short-window IV percentile |

ETH: same six DVOL features from ~2022-01-01.

These replace chain-derived `atm_iv` pre-Apr 2025. Do **not** alias them silently — tag `source=dvol` in the feature manifest.

### 4.2 From chains only (Apr 2025+)

Compute with existing `cryoquant/features/options.py` **only on dates with parquets**:

| Feature | When |
|---|---|
| `atm_iv` (chain) | Apr 2025+ |
| `term_slope` | Apr 2025+ |
| `risk_reversal_25d` | Apr 2025+ |

On overlap (Apr 2025+), prefer **chain** `atm_iv` for backtest features; keep DVOL for cross-check / ablation.

### 4.3 Explicitly excluded from v1

- Max pain
- Options open interest (aggregate or by strike)
- Skew / term structure **before** Apr 2025
- Any “options proxy” built from funding, spot skew, etc. (those live in §B/D if included — they are **not** options features)

**Target:** ≤ **6 options-tagged columns** in the full feature matrix (~30–100 total per D-6). Options are a minority slice.

---

## 5. Goal 1 vs Goal 2 implications

### Goal 1 (directional forecast)

- Full dev window 2018–2024 with **no options dependency**.
- DVOL-era rows (2021+) optionally add 3 vol columns; earlier rows simply omit them (NaN + model handles missingness).
- Primary signals: price/trend, macro, funding, cross-asset, RV.

### Goal 2 (short-vol book)

**Training / signal (Phases 2–5):**

- Vol and exceedance heads trained on DVOL + RV + core features on dev (2021–2024 subset for vol-rich era).
- Chain-only features unavailable on dev — **by design**, not a bug.

**Backtest (Phases 6–7):**

| Phase | Chain P&L backtest | Acceptable evidence |
|---|---|---|
| Phase 6 (dev) | ❌ No chains in dev | Calibration (ECE), exceedance Brier, vs HAR-RV/GARCH baselines |
| Phase 7 (hold-out) | ✅ Apr 2025+ only | **G2′ primary:** physical P(OTM) vs market δ; report-all chain grid (no hold-out selection); G1′ economic gates secondary; report N explicitly |

Do **not** headline dev-period Sharpe from synthetic options P&L. If hold-out chain N is too small for significance, report that honestly — do not backfill.

---

## 6. `universe.yaml` options block

```yaml
options:
  indices:   # reliable long-history IV
    - {venue: deribit, series: DVOL, underlying: BTC, source: api, start: 2021-03-31}
    - {venue: deribit, series: DVOL, underlying: ETH, source: api, start: 2022-01-01}

  chains:    # local parquets only — no backfill
    - {venue: deribit, underlying: BTC, source: cryobacktester_parquet, start: 2025-04-01}
    - {venue: deribit, underlying: ETH, source: cryobacktester_parquet, start: 2025-04-01}

  forward:   # P-4: grow chain window from Phase 1
    - {venue: deribit, underlying: [BTC, ETH], source: api_daily_snapshot, start: phase1_run_date}
```

---

## 7. Implementation (Phase 1+)

1. **`deribit_indices.py`** — ingest DVOL daily (BTC, ETH); idempotent cache.
2. **`deribit_chain_forward.py`** — daily API snapshot → parquet (same schema as CryoBacktester).
3. **`features/options.py`** — add `dvol_features()` helper; gate chain features on `load_chain` success.
4. **Feature manifest** — column tags (`core` / `extended`) per [`FEATURE_CATALOG.md`](FEATURE_CATALOG.md); `options_source` per row.
5. **Phase 6** — `evaluate_short_vol` runs only when chain file exists; skip with log otherwise.
6. **Phase 7 report** — (a) **7A:** refit 48 models on full dev → `holdout_predictions.parquet`; (b) calibration on hold-out bars 2024-06→2025-04; (c) chain backtest Apr 2025+ with report-all grid; separate tables in `RESULTS.md`.

---

## 8. DATA_SOURCES §C register (locked)

| ID | Series | Source | Start | Decision |
|---|---|---|---|---|
| C1 | BTC DVOL daily | Deribit API | 2021-03-31 | **include** |
| C2 | ETH DVOL daily | Deribit API | ~2022-01-01 | **include** |
| C3 | BTC option chains | CryoBacktester parquets | ~2025-04-01 | **include** |
| C4 | ETH option chains | CryoBacktester parquets | ~2025-04-01 | **include** |
| C5 | Forward daily chains | Deribit API | Phase 1+ | **include** |
| C6 | Skew / OI / max pain (any vendor) | — | — | **exclude** |
| C7 | Historical chain backfill | Tardis / CDD / etc. | — | **exclude** |
| C8 | SOL option chains | Deribit | — | **exclude** (D-15) |

---

## 9. Summary

- **Options are optional seasoning**, not the main dish. Core model runs on price, macro, funding, and RV across the full dev window.
- **Three DVOL features** are the only long-history options signal we trust.
- **Chain features and chain backtest** apply only from ~Apr 2025 — a short but **real** hold-out sample.
- **No backfill, no proxies, no synthetic P&L** for missing eras.
- Forward ingest (P-4) grows the reliable chain window over time without rewriting history.

### Phase 2 implementation (2026-06-28)

- **DVOL features** (`btc_dvol_30d`, `eth_dvol_30d`, `iv_minus_rv`, `dvol_rank_252`, `dvol_chg_7d`, `dvol_rank_90`, `vol_of_vol`) populated from Deribit index ingest (C1/C2).
- **Chain features** (C3) built from CryoBacktester parquets ≥ 2025-04-11; P2-T03 lookahead test passes (entry-time snapshot only).
- **Gap vs register:** On-disk chain parquets are **BTC-underlying only** as of build date — `eth_*` chain columns exist in `features.parquet` but are **NaN**. C4 ETH chains remain a forward-ingest item; do not backfill.
- **Performance:** Full feature rebuild ~2.4 min (single-pass chain load per date). See SPEC §8.4.
