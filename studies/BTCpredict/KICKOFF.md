---
name: BTCpredict — Crypto Price Prediction (Kick-off Research Brief)
overview: >
  State-of-the-art research brief and reference document for a supervised
  ML system that predicts short- and medium-term price/return of BTCUSD,
  ETHUSD, SOLUSD (horizons: 1-day, 5-day, 1–3 weeks). Dual goal: (1) a
  directional prediction machine; (2) PRIMARY — a calibrated signal engine
  for a short-volatility option-selling book (sell low-delta OTM options on
  Deribit and sharpen the edge). This is NOT a spec; it is the upstream
  reference a later SPEC.md and implementation derive from. Audience: human
  researchers + AI coding agents.
status: draft / pre-spec
goals: ["directional forecast", "short-vol option-selling signal (primary)"]
horizons: ["T+1d", "T+5d", "T+10..21d"]
assets: ["BTCUSD", "ETHUSD", "SOLUSD"]
options_venue: Deribit (BTC, ETH; SOL deferred)
isProject: false
---

# BTCpredict — Kick-off Research Brief

> **What this document is.** A curated, opinionated map of the problem space
> for predicting crypto prices with machine learning, grounded in (a) recent
> literature, (b) the two input design docs in [`input/`](input/), and (c) the
> existing CryoQuant codebase. It walks a reader through every stage of a
> candidate pipeline, flags the decisions that matter, and lists the pros/cons
> of each fork.
>
> **What this document is NOT.** It is not a specification, not an
> implementation plan with file-level tasks, and not a final architecture. The
> next artifact (`SPEC.md`) will commit to concrete choices; this brief gives
> that spec the menu, the rationale, and the guardrails.

---

## 0. How to read this document

**If you are a human researcher:** read §1–§4 for framing and the literature
position, then skim §5 (the pipeline) and stop at every **Decision** callout —
those are yours to make. §11 collects the open decisions in one place.

**If you are an AI agent writing the SPEC:** treat §6 (Principles) as
*non-negotiable invariants*, §5 (Pipeline) as the stage contract you must
preserve, and §9 (CryoQuant reuse map) as the integration surface. Do not
invent new infra where the table in §9 says "reuse". Where it says "build",
that is net-new and must be specified. Resolve every **Decision** callout with
the human's answers (§11) before committing the spec.

**Conventions used here:**

- **Decision** callouts mark forks where a human (or an explicit, recorded
  rationale) must choose. They look like: `> **Decision D-x:** …`.
- **Principle** callouts are invariants. Violating one is a bug, not a
  trade-off.
- Code blocks are *illustrative*, not copy-paste-ready. They show intent and
  the relevant CryoQuant API surface.
- Links point to papers, books, repos, and data sources. Prefer primary
  sources (the listed papers/books) over blog restatements.

---

## 1. Problem statement & objectives

This project has **two goals**, and the second is the one that drives the design:

1. **A directional prediction machine** for three liquid crypto assets —
   **BTCUSD, ETHUSD, SOLUSD** — at short and medium horizons. Valuable in its
   own right.
2. **(Primary) A signal engine for a short-volatility option-selling book.** We
   sell **low-delta options** (calls/puts/strangles with a high prior
   probability of expiring out-of-the-money), and use the model to *improve that
   edge* — better entry timing, side/skew tilt, strike selection, and tail
   avoidance. See **§1.2** — this reframes what we actually predict.

Horizons map onto option tenors:

| Horizon | Use case (directional) | Option tenor it feeds | Bar cadence |
|---|---|---|---|
| **T+1 day** | tactical, next-day direction | 1–2 DTE (daily/short weekly) | daily (intraday features allowed) |
| **T+5 days** | weekly swing | ~weekly expiry | daily |
| **T+10–21 days (~1–3 weeks)** | position/allocation tilt | bi-weekly / monthly expiry | daily / weekly |

The training data is mostly **public time-series**: OHLC(V) price data, derived
technical indicators, macro series, crypto-specific data (on-chain metrics,
flows, funding/open interest, cross-asset prices), **and the options surface
itself** (implied vol, skew, term structure — already available via Deribit in
CryoQuant; see §1.2 and §9).

**The objective is not raw predictive accuracy.** It is *robust, out-of-sample,
economically meaningful* prediction. For the option book specifically (§1.2),
the deliverable is **well-calibrated tail/exceedance probabilities**, not a
point forecast. A model with a lower R² that survives purged walk-forward and a
deflated-Sharpe test is worth more than a flashier model that overfits. This
single sentence drives almost every decision below.

### 1.1 What "predict the price" actually means (framing)

Predicting the *level* of price is the wrong default. Prices are non-stationary
(unit-root / near-random-walk), so a model that "predicts price" is usually just
relearning "tomorrow ≈ today" and posting a deceptively high R². We instead
predict a **stationary transform of price** and choose a *task framing*:

| Framing | Target | Eval metrics | When to use |
|---|---|---|---|
| **Regression** | log-return at T+N | MAE, RMSE, R², IC | continuous sizing, vol targeting |
| **Classification** | direction (up/down) or up/flat/down | Accuracy, F1, **MCC**, AUC | directional trading (Goal 1) |
| **Probabilistic** | P(return > threshold), P(barrier hit) | log-loss, **Brier**, calibration (ECE) | risk-managed sizing, ensembling |
| **Distributional / quantile** | conditional return *distribution* (quantiles) at T+N | pinball/quantile loss, coverage, CRPS | **P(OTM) at any strike → option selling (Goal 2)** |
| **Volatility** | realized vol over horizon (vs implied) | QLIKE, MAE on vol, IV−RV sign | vol-premium timing (Goal 2) |
| **Barrier / exceedance** | P(touch / terminal beyond strike K) | Brier, calibration, MCC | does a sold option finish OTM? (Goal 2) |
| **Triple-barrier** | which of {profit, stop, timeout} hits first | MCC, precision@fire | event/trade-centric labels |

> **Decision D-1 (Target framing). ✅ Resolved (2026-06-28):**
> run **two coupled heads**:
> (a) a **probabilistic directional** head (direction + magnitude) for Goal 1
> and to choose *which side* to sell; and
> (b) a **distributional / exceedance** head — conditional return quantiles
> and/or realized-vol forecast — for Goal 2, since selling a low-delta option is
> fundamentally a bet on the **tails of the return distribution**, not the
> central direction. Keep a **log-return regression** head as a sanity
> benchmark. See §1.2, §5.4.

### 1.2 Primary application — the short-volatility option-selling book

This is the goal that should shape the spec. We sell **low-delta options**
(e.g., 10–20Δ puts, calls, or strangles) that have a high prior probability of
expiring OTM, and we want the model to *sharpen and protect* that edge.

#### 1.2.1 Where the edge comes from (and what the model adds)

The base edge is **structural**: the **Variance Risk Premium (VRP)** — implied
volatility is, on average, richer than subsequently realized volatility, so
sellers of options are paid a premium for bearing variance/jump risk. Crypto
historically has a *large* VRP. CryoQuant already computes this directly:
`features/options.iv_minus_rv` (ATM IV − realized vol).

A naive "always sell a 15Δ strangle" book already harvests VRP. **The model's
job is to beat that naive book** along four levers:

| Lever | What the model predicts | CryoQuant hook |
|---|---|---|
| **1. Entry timing** | Will realized vol over the option's life be *below* implied? Is VRP rich now? | `iv_minus_rv`, vol forecast head |
| **2. Tail / regime avoidance** | Probability of a vol-expansion / jump / crash during the option's life (the thing that blows up short vol) | vol-regime, `vol_of_vol`, distributional tails |
| **3. Side & skew tilt** | Which side is safer to sell — sell puts in uptrend, calls in downtrend, or symmetric strangle? Is skew mispriced? | directional head, `risk_reversal_25d` |
| **4. Strike / delta selection** | At what delta is the *physical* P(finish OTM) materially better than the *market-implied* P(OTM)? | distributional/exceedance head vs option `delta` |

> **The crux (read this twice).** An option's **delta ≈ the market-implied
> (risk-neutral) probability of finishing ITM.** Selling a 10Δ option means the
> market prices ~10% chance of being ITM. Our model produces a **physical
> (real-world) probability** of finishing ITM. **Edge exists precisely where our
> well-calibrated physical P(ITM) is *lower* than the option's delta** — i.e.,
> the market is overpaying for that tail. The entire strategy is a bet on the
> gap between the physical and risk-neutral distributions. Therefore:

> **Principle P-0b — Calibration is the product.** For the option book, a
> *calibrated* probability is worth more than an *accurate* point forecast. If
> the model says "8% chance ITM" it must be ITM ~8% of the time. Miscalibration
> = systematic option mispricing = blow-up risk. Brier score, reliability
> diagrams, and ECE (already in `models/metrics.py`) are first-class success
> metrics here, not afterthoughts. See §7.4b.

#### 1.2.2 Payoff shape changes everything about evaluation

Short vol has a **negatively skewed** payoff: many small wins (premium kept),
rare large losses (a strike breached in a crash). Consequences the spec must
encode:

- **Win-rate is not edge.** A 90%-OTM book can still be hugely unprofitable if
  the 10% losses are large enough. Evaluate **expectancy and tail risk** (CVaR,
  max loss per trade, worst-week), not just hit-rate.
- **Sharpe flatters short vol.** Negative skew/kurtosis inflate naive Sharpe;
  use **Probabilistic/Deflated Sharpe** (skew/kurtosis-aware — already in
  `robustness.deflated_sharpe`) and report drawdown/CVaR alongside.
- **The benchmark is the naive seller**, not cash. We must prove the model beats
  an unconditional "sell δ-delta strangle every period" baseline on *risk-
  adjusted, after-cost* terms — otherwise the ML adds nothing over harvesting
  raw VRP.
- **Management rules matter as much as the signal.** Roll/close-early/stop
  policies (e.g., close at 50% of max profit, stop at N× credit) change the P&L
  distribution materially. Treat them as part of the strategy, validated, not
  hard-coded guesses.

#### 1.2.2b Naked vs defined-risk (the structural tail decision)

The single biggest risk-architecture choice is whether the sold options are
**naked** (undefined risk) or **defined-risk** (the position's worst-case loss
is capped):

| | Naked short (sell a bare δ-delta option) | Defined-risk (credit spread / iron condor) |
|---|---|---|
| Tail | **Unbounded** (gap/crash can dwarf all premium collected) | **Capped** at (spread width − credit) |
| Premium / edge | Higher (full VRP) | Lower (pay for the long wing) |
| Margin | Large, mark-to-market, **liquidation risk** | Small, fixed |
| Failure mode | One bad day erases months (the short-vol blow-up) | Bounded, survivable |

> **Decision D-16 (Tail-risk structure). ✅ Resolved (2026-06-28):** **Build both
> naked and defined-risk variants and compare; treat defined-risk
> (spreads/condors) as the tail-safe default.** Rationale: the negative-skew
> blow-up is the dominant failure mode for short vol; we want to *measure* how
> much edge the long-wing insurance costs rather than assume. The backtester
> must therefore support both a bare short leg and a vertical spread (two legs:
> short δ-delta + long further-OTM wing). This is a modest extension of the
> delta-targeted leg selection already in `option_lookup`.

#### 1.2.3 Instruments, venue, and data reality

- **Venue:** **Deribit** is the dominant crypto options venue and is already
  wired (read-only) in CryoQuant (`data/sources/deribit_options.py`,
  `backtest/option_lookup.py`). Chains carry `strike, is_call, bid/ask/mark
  price, delta, mark_iv` — everything we need for delta-targeted leg selection.
- **Settlement:** Deribit options are **European, cash-settled** → the *terminal*
  price vs strike at expiry determines OTM/ITM (favoring terminal-exceedance
  labels). But if we *manage* positions (close early), the *path* (max adverse
  excursion / touch) also matters → keep both terminal and path labels (§5.4).
- **Liquidity by asset:** **BTC and ETH** options are liquid with multi-year
  history. **SOL options are newer and thinner** — short history and wider
  spreads. This compounds the SOL data problem (D-4/D-7/D-10): the SOL *options*
  book may not be backtestable with the same fidelity. Flag explicitly.

> **Decision D-13 (Option structure). ✅ Resolved (2026-06-28):**
> **Model-tilted structures** — sell strangles by default, and lean to one side
> (or weight the legs) when the directional head is confident. At a target delta,
> reusing `option_lookup.evaluate`'s delta-targeted call+put leg selection,
> inverted from *buy* to *sell*.

> **Decision D-14 (Tenor / DTE & management). ✅ Resolved (2026-06-28):**
> **Parameterize and sweep** DTE targets per horizon (~1–2 / 7 / 14–30 DTE) and
> the management policy (hold-to-expiry vs early-close TP vs stop) via
> `ExitRule(hold_h, tp_multiple, stop_multiple)`; let the (deflated, after-cost)
> backtest pick. Sweep size counts toward the trial budget for DSR.

> **Decision D-15 (Underlying for the options book). ✅ Resolved (2026-06-28):**
> **BTC + ETH only** for the v1 *options* book; the SOL *directional* model may
> still ship (D-10), but the **SOL options book is deferred** (thin/short market,
> not backtestable with fidelity).

### 1.3 Realistic expectations (set them now)

Both input docs and the literature agree: this is a **high-noise, low-signal**
problem.

- Daily directional accuracy of a *good* model is ~**53–57%**, not 70%+. Any
  OOS directional accuracy ≥ 60% sustained across regimes should be treated as
  a **leakage alarm**, not a triumph.
- OOS R² on daily returns of **0.01–0.05** is meaningful in finance. OOS R² >
  0.2–0.3 almost always means lookahead/leakage.
- The edge, if real, is *small and statistical*. It is realized through
  consistency, position sizing, and cost discipline — not through a single
  oracle prediction.

> **Principle P-0 — Calibrated humility.** Treat every "too good" result as a
> bug until proven otherwise (permutation test, leakage audit, regime split).
> The default prior is "no edge".

---

## 2. State of the art (literature position)

This section summarizes what the current research consensus says, so the spec
doesn't relitigate settled questions. Citations in §10.

### 2.1 Which model family wins on this kind of data?

**Gradient-boosted decision trees (GBDT) are the default winner for tabular,
feature-engineered financial data**, and crypto is no exception:

- Multiple 2022–2025 tabular-ML benchmarks (Grinsztajn et al. 2022; "Is Deep
  Learning finally better…" 2024; TabArena 2025; OmniTabBench 2026) find
  **tree ensembles (XGBoost/LightGBM/CatBoost) remain state-of-the-art on
  medium-sized tabular data (~10K rows)** even after heavy NN tuning. Deep nets
  "catch up" only with large data + long compute budgets + ensembling. Our
  per-asset daily history is *small* (≈ thousands of rows), which strongly
  favors trees.
- Crypto-specific comparative studies (2023–2025) are mixed but lean the same
  way: Gradient Boosting / XGBoost frequently **outperform LSTMs** in accuracy
  and robustness on crypto return prediction; LSTMs are sensitive to
  hyperparameters and noise. A minority (e.g., the MDPI *Forecast* 2023 study)
  finds LSTM best — but often on *price-level* targets, which is exactly the
  framing we distrust (§1.1).
- **Hybrid LSTM→XGBoost** stacks (LSTM extracts temporal features, XGBoost does
  nonlinear regression on them + auxiliary features) are a recurring
  "best-performing" pattern in recent crypto papers (e.g., arXiv 2506.22055).
  Useful as a *later* experiment, not a v1.

**Time-series deep learning (TFT, PatchTST, N-HiTS, N-BEATS, TimesNet,
TimeMixer, TCN)** and **time-series foundation models (TimesFM, Chronos)** are
worth knowing but are **not** the v1 recommendation:

- They shine with abundant data, multivariate panels, and stable/seasonal
  structure. Crypto daily data is short, noisy, and regime-switching — their
  weak spot. Foundation models are strong *zero-shot* on stable series but
  "remain sensitive to noisy, high-entropy financial data."
- They are appropriate as **Phase 2 challengers** once the tree baseline,
  validation harness, and labels are trustworthy.

> **Decision D-2 (Model roadmap).** *Recommendation:* **Phase 1 = GBDT
> (LightGBM primary, XGBoost/CatBoost as ensemble members) + linear/naive
> baselines.** **Phase 2 (optional) = sequence models** (TFT / PatchTST / N-HiTS
> via `darts` / `neuralforecast` / `pytorch-forecasting`) and **hybrid
> LSTM→GBDT**, gated on Phase-1 results. Don't start with deep learning.

### 2.2 Why simple baselines matter

The naive "tomorrow = today" (random-walk) and "rolling-mean return" baselines
are **hard to beat in log-return terms**. ARIMA/GARCH are classical references
(GARCH captures volatility clustering well, which matters if a horizon target
is realized volatility). **A model that cannot beat the naive baseline OOS has
no edge — full stop.**

### 2.3 The methodological core (this is where edge is won or lost)

The strongest signal from the literature is **not** about model choice; it is
about *validation discipline*. The canonical framework is Marcos López de
Prado's *Advances in Financial Machine Learning* (AFML, 2018):

- **Purged K-Fold + Embargo** (AFML ch. 7): when labels are forward-looking and
  overlapping, neighboring train/test samples share information. Purge
  overlapping samples and embargo a buffer after each test fold.
- **Combinatorial Purged Cross-Validation (CPCV)** (AFML ch. 12): instead of a
  single walk-forward path, evaluate over many train/test combinations to get a
  *distribution* of OOS outcomes → enables **PBO** (Probability of Backtest
  Overfitting).
- **Deflated Sharpe Ratio / Probabilistic Sharpe Ratio** (Bailey & López de
  Prado 2012/2014): correct the Sharpe for the number of trials tested, plus
  skew/kurtosis. Essential because we *will* test many configurations.
- A 2024 *Knowledge-Based Systems* study ("Backtest overfitting in the ML era")
  finds CPCV ahead of k-fold / purged-kfold / walk-forward on both PBO and DSR.

> **Principle P-1 — The harness outranks the model.** Build and trust the
> validation harness (purging, embargo, walk-forward, DSR/PBO) *before* chasing
> model performance. Most "edges" are validation artifacts.

---

## 3. The two input documents (synthesis)

Two prior design docs live in [`input/`](input/). They agree strongly; this
brief reconciles and extends them.

**`crypto_ml_pipeline.docx` — "ML-based Crypto Price Prediction Pipeline".**
The crypto-specific, code-heavy doc. Strengths: concrete feature lists
(technical, macro, on-chain, cross-asset), explicit leakage traps, XGBoost/
LightGBM/Optuna recipes, SHAP feature selection, walk-forward backtest loop,
regime analysis, ensembling (blend/stack), per-asset model portfolio, drift
monitoring (IC, PSI). Realistic-expectations section (53–57% directional).

**`Machine Learning Pipeline for Financial Time Series Prediction.docx` —
"Design Document".** The general, architecture-level doc aimed at AI coding
agents. Strengths: immutable raw data, modular package layout
(`data/cleaning/features/labels/models/training/validation/statistics/
backtesting/paper_trading/deployment/monitoring`), triple-barrier labeling,
purged CV + embargo, PBO/DSR/White's Reality Check/SPA, final untouched
hold-out, paper trading before deployment, continuous retraining, strong
"guiding principles" list, and a thorough reference bibliography.

**Where they converge (treat as settled):**

1. Model **log-returns / stationary transforms**, never raw price.
2. **Tree ensembles first**; deep learning later.
3. **No data leakage**, ever — fit all transforms on train only; shift targets.
4. **Walk-forward / purged CV with embargo**; never shuffle time series.
5. **Statistical validation** (DSR/PBO) and a **final hold-out**.
6. **Economic evaluation** (costs, Sharpe) over pure error metrics.
7. **Reproducibility** and **immutable raw data**.

**Where this brief adds / sharpens:**

- Maps every stage onto **existing CryoQuant modules** (§9) so we build less.
- Adds the **2024–2026 SOTA position** (§2) and explicit free-vs-paid data
  sourcing (§5.0).
- Forces the **multi-horizon (1d/5d/1–3wk)** and **3-asset** structure into the
  label and validation design.
- Calls out **CPCV/PBO** as a *gap to build* in CryoQuant (currently only DSR +
  bootstrap CI exist).

---

## 4. What CryoQuant already gives us (snapshot)

This study lives in `studies/BTCpredict/` and should **import the framework, not
re-implement it**. CryoQuant is a *library, not a pipeline runner*
(`data → features → labels → models → signals → backtest`). Relevant existing
capabilities (full reuse/build map in §9):

- **Data:** `load_track` / `load_tracks` (`cryoquant/data/resolve.py`),
  partitioned parquet store + DuckDB catalog, sources for Binance spot/perp,
  Yahoo, Twelve Data, FRED, CBOE, Deribit (read-only). Registered symbols incl.
  `binance.spot:BTCUSDT`, `ETHUSDT`, `SOLUSDT`. On-chain (Coin Metrics G1–G4) wired in
  Phase 1 + feature panel.
- **Features:** 40+ tier-1 primitives (`rsi`, `ema`, `atr`, `macd`, `bb`,
  `donchian`, `adx`, `supertrend`, `realised_vol`, …) and tier-2 builders
  (`SpotFeatures`, `TrendFeatures`, `MacroFeatures`, `CrossAssetFeatures`),
  `DataPanel` for multi-track alignment, `align_series` (`merge_asof` backward,
  staleness cap).
- **Labels:** `ForwardReturnLabeler(horizon_h, threshold, direction)`. **No
  triple-barrier, no regression labeler, no multi-horizon helper yet.**
- **Models:** `TabularModel` (LightGBM + isotonic calibration), CV utilities
  `purged_kfold(embargo_bars)` and `walk_forward`, `walk_forward_fit(...)`,
  `metrics.compute_metrics` (AUC/Brier/logloss/ECE), DuckDB model registry.
- **Signals:** `BoolSignal / ScoreSignal / StateSignal / ProbSignal`,
  `prob_from_model`, threshold picker.
- **Backtest:** `simulate` (spot), `breakout_sim`, metrics, **`deflated_sharpe`
  and `bootstrap_ci` (robustness.py)**, sweep/bundle/leaderboard infra,
  HTML reports + study manifests.
- **Reference scripts:** `scripts/ml_multi_source.py` (canonical Path C demo:
  `DataPanel → TrendFeatures+MacroFeatures → ForwardReturnLabeler →
  walk_forward_fit(TabularModel) → prob_from_model → simulate`) and the live
  BTC ML test `tests/live/test_phase3_live.py`.

**Known gaps we will likely build:** SOL + on-chain/funding data wiring,
triple-barrier and regression labels, multi-horizon label helper, CPCV + PBO,
permutation/leakage test harness, regression model wrapper, optional sequence
models.

---

## 5. The pipeline, stage by stage

The end-to-end research pipeline both input docs converge on, annotated with
decisions, pros/cons, and CryoQuant hooks:

```text
(0) Data sourcing/inventory
        ↓
(1) Raw data — immutable, versioned
        ↓
(2) Cleaning & alignment (UTC, calendars, forward-fill rules)
        ↓
(3) Feature engineering (causal only)
        ↓
(4) Labeling / target design (multi-horizon, multi-asset)
        ↓
(5) Model selection (baselines → GBDT → optional deep)
        ↓
(6) Validation (purged walk-forward / CPCV, embargo)
        ↓
(7) Overfitting defenses + statistical verification (DSR/PBO/permutation)
        ↓
(8) Economic backtest (costs, sizing, regime split)
        ↓
(9) Final frozen hold-out (touch once)
        ↓
(10) Paper trading → monitoring → retraining   [future scope]
```

> **Principle P-2 — Each stage is independently testable and reproducible from
> raw.** Every stage reads versioned inputs and writes versioned outputs. No
> stage mutates an upstream artifact. Any result must be reconstructable from
> immutable raw data + code + config.

### 5.0 Stage 0 — Data sourcing & inventory

Decide *what data*, *from where*, and *free vs paid* before anything else.
Crypto on-chain/flow data is where cost and complexity explode, so scope it
deliberately.

> **Per-source review (not locked):** D-3 locks *free-only*; the specific ingest
> list is a **proposal** until reviewed in
> **[`DATA_SOURCES.md`](DATA_SOURCES.md)**. `universe.yaml` is generated from
> approved rows there — **signed off 2026-06-28**; Phase 1 ingest **complete**;
> Phase 2 features **complete** (see `data/features.parquet`).

**Price / OHLCV (core, free):**

| Data | Source | In CryoQuant? |
|---|---|---|
| BTC/ETH/SOL daily+hourly OHLCV | Binance (`ccxt`/`python-binance`), CoinGecko, CryptoCompare | BTC/ETH/SOL ✅ |
| BTC dominance (BTC.D), total mktcap | CoinGecko, TradingView | build |
| Funding rate, open interest (perps) | Binance perp API (`fetch_funding` exists) | partial (not wired to loader) |

**Macro (free, mostly already wired):** DXY, 2s10s spread, SOFR (FRED),
S&P500 (SPY), Gold (GLD), VIX (CBOE), **FOMC decision-day flags** (Fed calendar).
Expanded regime series (Nasdaq/QQQ, Fed balance sheet, HY spread, CPI/PCE, MOVE) are
**excluded** from v1 — see `DATA_SOURCES.md` §D. FRED + Yahoo + CBOE sources already exist.

**Crypto-specific / on-chain (mix of free + paid — scope carefully):**

| Signal | Free source | Paid / richer |
|---|---|---|
| Fear & Greed Index | alternative.me (free API) | — |
| Stablecoin supply (USDT+USDC), DeFi TVL | **DefiLlama** (free API) | — |
| ETH/BTC, SOL/BTC ratios | derive from OHLCV | — |
| Active addresses, NVT, exchange net-flow, realized cap, SOPR, MVRV | blockchain.com charts (BTC, free), **Coin Metrics community** (free, limited), Dune (free queries) | **Glassnode, CryptoQuant, Nansen** (paid) |
| Hash rate / difficulty (BTC) | blockchain.com (free) | — |
| ETH gas, staking yield; SOL TPS, validators, ecosystem TVL | public RPC / DefiLlama / Dune | paid dashboards |

> **Decision D-3 (Data scope for v1). ✅ Resolved (2026-06-28):** **v1 = free
> sources only** — Binance OHLCV (daily + hourly), macro minimal pack (FRED/Yahoo/CBOE
> D1–D6), **FOMC decision-day calendar**, Binance perp funding + OI, Fear & Greed,
> DefiLlama stablecoin supply, Coin Metrics BTC network metrics (G1–G4), **Farside
> ETF flows + Strategy.com MSTR** (E1–E2, E4–E5), Deribit DVOL + forward chains,
> derived cross-asset ratios. Defer paid on-chain (Glassnode/CryptoQuant) and expanded
> macro (D7–D13). Full register: **`DATA_SOURCES.md`** (signed off 2026-06-28).

> **Decision D-4 (History depth & SOL).** Need **≥3 years** daily history (more
> is better for regime coverage; BTC has ~2014+, ETH ~2017+, **SOL only ~2020+**).
> SOL's short, single-cycle history is a real limitation — decide whether to (a)
> train SOL standalone, (b) **transfer-learn / pool** with BTC/ETH features, or
> (c) defer SOL to a later phase. See D-7.

### 5.1 Stage 1 — Raw data (immutable)

> **Principle P-3 — Raw data is immutable.** Never overwrite source data. Store
> exactly as received, timestamped, versioned. All cleaning happens downstream
> into *new* artifacts. CryoQuant's partitioned parquet store +
> `catalog.duckdb` already enforce this pattern
> (`STORE_ROOT/<source>/<venue>_<ticker>/<tf>/year=YYYY/month=MM.parquet`).

- Use `cryoquant.data.ingest.run_ingest(universe.yaml)` to batch-pull a defined
  universe; pre-inception months get `.empty` sentinels (no silent gaps).
- Keep a `universe.yaml` under `studies/BTCpredict/` listing every symbol,
  timeframe, and start date. That file *is* the dataset version manifest.
- Record provenance: source, fetch timestamp, API version. The catalog stores a
  schema hash per dataset — extend it with a data manifest for this study.

### 5.2 Stage 2 — Cleaning & alignment

The single most common failure here is **mis-aligned timestamps causing
silent lookahead** (e.g., using a macro print before it was released).

- **UTC, closed-bar safety:** CryoQuant is UTC-first and bar-open indexed
  (`cryocore/time.py`); features must use only *closed* bars. Honor this.
- **Calendars:** crypto trades 24/7 (`crypto_24_7`); equities/macro do not
  (`nyse`, `cme_futures`, `fx_24_5`). Align lower-frequency series to the daily
  crypto close with **backward `merge_asof`** (`align_series`) so each crypto
  bar sees only the *most recent already-published* macro value. Cap staleness
  (existing 35-day cap) to avoid forward-filling dead series forever.
- **Release-time realism (subtle, important):** Macro data (CPI, NFP) is
  *reported with a lag and at a specific time*. Aligning on the *reference date*
  instead of the *release date* is lookahead. For event series, prefer
  **release-date timestamps** or encode as **event flags** (e.g.,
  `is_fomc_week`, `days_since_cpi`) rather than levels.
- **Cleaning ops:** `clean_ohlcv` / `normalize_ohlcv` / `audit_bars` exist for
  spike/stale-bar removal and QA warnings. Winsorize/clip outliers using
  **training-split statistics only** (see leakage, §7).

> **Decision D-5 (Bar cadence).** *Recommendation:* **daily bars as the primary
> modeling cadence** for all three horizons (1d/5d/1–3wk are daily-or-coarser),
> with **hourly bars used only to engineer daily features** (e.g., intraday
> realized vol, overnight gaps, session returns). Pure-daily keeps the sample
> size honest and macro alignment clean. Reconsider hourly modeling only if a
> short-horizon intraday variant is later desired.

### 5.3 Stage 3 — Feature engineering

Goal: convert raw prices/series into **causal, predominantly stationary**
inputs. Technical indicators add no new information in the
information-theoretic sense, but they encode nonlinear lag structure that trees
exploit cheaply, so they are worth computing.

> **Principle P-4 — Every feature is causal.** A feature at time *t* may use
> only information available at or before *t*'s bar close. Any rolling window or
> indicator must be computed without peeking forward; targets are `shift()`ed
> by the horizon, never features. No statistic (scaler, winsor bound, target
> encoding) may be fit on anything but the training split.

**Feature families (start broad, then prune — see §7.3):**

| Family | Examples | CryoQuant primitive/builder |
|---|---|---|
| Returns | log-return 1/5/10d, overnight gap, cumulative | derive; `SpotFeatures` ret_* |
| Trend | SMA/EMA distances, MACD, ADX, supertrend, Donchian pos, linreg slope | `ema/sma/macd/adx/supertrend/donchian/linear_reg_slope`, `TrendFeatures` |
| Momentum | RSI 7/14, ROC, Stoch, Williams %R | `rsi/roc`, add others |
| Volatility | ATR%, Bollinger width/%B, realized vol (Parkinson/Garman-Klass), RV rank, vol regime | `atr_pct/bb/bb_width/realised_vol/rv_rank` |
| Volume/flow | OBV, volume z-score, VWAP deviation, funding rate, OI change | `obv/vwap/vol_z`; funding/OI = build |
| Cross-asset | ETH/BTC, SOL/BTC, RS vs SPY, DXY regime, gold ratio | `relative_strength`, `CrossAssetFeatures` |
| Macro | DXY, 2s10s, rates, HY spread, VIX, MOVE, CPI YoY | `MacroFeatures` |
| On-chain | active addresses, NVT, exchange net-flow, stablecoin supply, hashrate, MVRV/SOPR | build (Stage 0 scope) |
| **Options surface (Goal 2)** | **ATM IV, IV−RV (VRP), IV percentile rank, term-structure slope, 25Δ risk-reversal (skew), vol-of-vol (extended)** | **`features/options.py`: `dvol_30d`, `iv_minus_rv`, `dvol_rank_252`, `term_slope`, `risk_reversal_25d`, `vol_of_vol`** |
| Calendar/regime | day-of-week, month, is_fomc_week, days_since_cpi, vol regime, trend regime | `calendar_features`, `trend_regime`, `vol_regime` |
| Lags & rolling stats | lag {1,2,3,5,10} of key features; rolling mean/std/skew over {5,10,20} | derive |

> **Note (Goal 2 features).** The options surface is both an *input* (IV/skew/
> term structure are powerful predictors of forward realized vol and direction)
> and the *thing we trade against*. Using IV-derived features to predict an
> option-selling outcome is legitimate **as long as** the feature uses only the
> surface observed at/before entry (no peeking at the expiry-window surface).

**Engineering decisions to record:**

- **Returns over prices** (P-4 corollary): `log_return = ln(close/close.shift(1))`.
- **Normalization choice:** trees are scale-invariant (don't strictly need
  scaling), but linear/NN baselines and SHAP comparability benefit from
  `RobustScaler`/`StandardScaler` **fit on train only**. Prefer ratio/z-score
  features (e.g., `close / rolling_mean`, distance-to-EMA in ATR units) that are
  *already* roughly stationary and regime-portable.
- **Automatic feature generation** (`tsfresh`, `featuretools`) is allowed but
  *dangerous* for leakage and dimensionality — defer; hand-engineered + selected
  features are the v1 path.

> **Decision D-6 (Feature budget).** *Recommendation:* start with a curated set
> and **keep the final model to ~30–100 selected features** (both docs and the
> literature converge here). More features ⇒ more variance and more spurious
> correlations on a small sample. Selection method in §7.3.

### 5.4 Stage 4 — Labeling / target design (this matters more than the model)

> **Principle P-5 — Label choice dominates model choice.** Spend
> disproportionate care here. A leak-free, economically meaningful label with a
> mediocre model beats a great model on a sloppy label.

We must produce labels for **3 assets × 3 horizons**. Options:

1. **Forward return (regression):** `y = ln(close[t+H]/close[t])`. Simple, but
   high-variance and dominated by noise at short horizons.
   CryoQuant: needs a small regression labeler (build) — current
   `ForwardReturnLabeler` is binary.
2. **Direction / magnitude (classification, probabilistic):** `y = 1[forward
   return > τ]` (with a dead-band `±τ` for up/flat/down). Calibratable, the most
   actionable. CryoQuant: `ForwardReturnLabeler(horizon_h, threshold, direction)`
   does exactly this (max-high/min-low vs threshold over the window).
3. **Triple-barrier (López de Prado):** label by which barrier (profit τ_up /
   stop τ_dn / time H) is hit first, with barriers scaled by realized vol.
   Trade-centric, vol-adaptive, the modern standard for *event* labels. **Build
   needed** (not in CryoQuant). Pairs naturally with **meta-labeling** (a second
   model predicts whether to *act* on the primary signal).
4. **Forward realized volatility (regression):** predict vol, not direction —
   useful for sizing and often *more* predictable than direction. A strong
   complementary target.

**Labels specific to the short-vol option book (Goal 2 — these are the ones that
matter most):**

5. **Terminal exceedance / OTM-expiry (binary, the strategy outcome):**
   `y = 1[ S_{t+H} crosses strike K ]` for a strike at target delta δ. Directly
   answers "would a δ-delta short option have finished OTM?" Build per (side,
   δ, H). This is what the model must predict *better than the option's own
   delta* (§1.2.1). **Build needed.**
6. **Distributional / quantile of H-day return:** predict conditional quantiles
   (e.g., 5/10/25/50/75/90/95%) of the H-day return → yields **P(OTM at *any*
   strike)** and lets us pick the delta where physical P(OTM) > market-implied.
   The most general Goal-2 target. **Build needed** (quantile labels are just
   the forward return; the *model* does the distributional work — §5.5).
7. **Path / max-adverse-excursion (for managed positions):** `max |return|` or
   touch of barrier over (t, t+H]. Needed if we close early / stop out rather
   than hold to expiry. CryoQuant's `ForwardReturnLabeler` already uses
   max-high/min-low over the window — close to this.
8. **VRP-realization (regression):** `y = IV_entry − RV_realized over option life`
   — did selling vol pay? Trains the "is vol rich now?" timing head directly.

**Horizon handling — two structural choices:**

- **Separate model per horizon** (3× models per asset) — simplest, cleanest
  validation, recommended for v1.
- **Multi-horizon / multi-output** (one model predicts the vector
  [1d,5d,1–3wk]) — shares signal, but couples errors and complicates
  purging (overlap window = longest horizon). Phase 2.

> **Decision D-1 revisited / D-2b (Label spec).** Resolve with D-1. *Concrete
> recommendation for v1:* per (asset, horizon), train a **probabilistic
> direction-with-magnitude classifier** (`ForwardReturnLabeler`,
> `direction="up"`/`"down"`/`"magnitude"`, vol-scaled `threshold`) **plus** an
> auxiliary **log-return regressor**, and **prototype triple-barrier** as the
> trade-centric alternative. Set the magnitude threshold from rolling realized
> vol, not a fixed %.

### 5.5 Stage 5 — Model selection

Order of experimentation (mirrors both docs and §2):

1. **Baselines (mandatory gate):** naive random-walk (`ŷ[t+1]=y[t]`), rolling-
   mean return, Ridge/OLS on the full feature matrix, ARIMA/GARCH (GARCH for the
   vol target). *No ML model graduates until it beats these OOS.* CryoQuant has
   `baselines.RuleModel`; add naive/linear/ARIMA reference predictors.
2. **GBDT (primary):** **LightGBM** (fast iteration), **XGBoost**, **CatBoost**.
   Keep them **regularized and shallow** for noisy data: `max_depth ≤ 4–5`,
   strong `min_child_samples`/`min_data_in_leaf`, `subsample`/`colsample ≈ 0.7`,
   `reg_alpha`/`reg_lambda > 0`, early stopping on a *validation* fold.
   CryoQuant: `TabularModel` wraps `LGBMClassifier` + isotonic calibration; add
   a regression variant + XGB/CatBoost members.
3. **Probability calibration:** isotonic or Platt/sigmoid (`CalibratedClassifierCV`
   already used). Report **Brier + reliability diagram + ECE** — calibration is
   what makes probabilistic outputs usable for sizing, and **for the option book
   it is the headline metric** (§1.2.1, §7.4b). After calibration, plot physical
   P(OTM) against option-implied P(OTM)≈δ to locate edge.
3b. **Distributional / volatility models (Goal 2):** to get the conditional
   return distribution and P(OTM) at any strike, use **quantile regression**
   (LightGBM `objective="quantile"` per quantile), **NGBoost** (predicts a full
   parametric distribution), or **conformal prediction** for calibrated
   intervals. For the vol head, **GARCH / EGARCH / HAR-RV** are strong, cheap
   baselines (and naturally capture volatility clustering). **Build needed**
   (CryoQuant ships only a calibrated classifier today).
4. **Ensemble:** simple average / variance-weighted blend, or **stacking** a
   Ridge meta-model on **out-of-fold** base predictions (avoid leakage by using
   OOF only). Ensembles usually improve Sharpe and tail behavior more than any
   single model.
5. **(Phase 2) Sequence / deep models:** TFT, PatchTST, N-HiTS, TimeMixer via
   `darts` / `neuralforecast` / `pytorch-forecasting`; **hybrid LSTM→GBDT**.
   Gate strictly on Phase-1 OOS results and added complexity cost.

> **Decision D-7 (Per-asset vs pooled).** Three forks:
> (a) **separate model per asset** (max specificity; SOL suffers from short
> history); (b) **single pooled multi-asset model** with an asset embedding/
> dummy + per-asset normalized features (more data, shared structure, helps SOL);
> (c) **anchor + transfer** (train on BTC, fine-tune on ETH/SOL).
> *Recommendation:* start **(a) for BTC & ETH** (they have history) and use
> **(b) pooling or (c) transfer to rescue SOL**. Decide explicitly.

> **Decision D-8 (Hyperparameter search).** Use **random search → Bayesian
> (Optuna)**, *never* exhaustive grids, and run it **inside nested validation**
> (tuning on inner folds, evaluation on outer/untouched folds) so tuning doesn't
> leak into the test estimate. Budget the number of trials — it feeds the DSR
> deflation (§7.4).

### 5.6 Stage 6 — Validation (the heart)

> **Principle P-6 — Validation must simulate live deployment.** Chronological
> only. Never shuffle. The model at prediction time *t* may have been trained
> only on data fully available before *t* (minus purge/embargo).

Layers, weakest→strongest:

1. **Walk-forward (rolling/expanding origin):** train [.., t], predict (t, t+k],
   slide. CryoQuant: `walk_forward` + `walk_forward_fit(..., embargo_bars=…)`
   already returns per-fold metrics + OOS probs (`concat_oos_probs`).
2. **Purged K-Fold + embargo:** for overlapping forward labels, purge train
   samples whose label window overlaps the test fold, and embargo a buffer
   after each test fold. CryoQuant: `purged_kfold(n, n_splits, embargo_bars)`
   exists but is **not yet wired into `walk_forward_fit`** — wire it.
   **Embargo length ≈ the label horizon** (e.g., ≥5 bars for a 5-day target;
   for 1–3wk targets, ≥15–21 bars).
3. **Combinatorial Purged CV (CPCV):** evaluate over `C(N,k)` test-group
   combinations to get a *distribution* of OOS paths → directly enables PBO.
   **Not in CryoQuant — build (§9).** References & open-source implementations
   in §10 (`purged-cross-validation` (MIT), `mlfinpy`; avoid the now-commercial
   `mlfinlab` as a dependency).

```python
# Illustrative: purged walk-forward with CryoQuant
from cryoquant.models.fit_loop import walk_forward_fit, concat_oos_probs
from cryoquant.models.tabular import TabularModel

results = walk_forward_fit(
    lambda: TabularModel(calibration_cv=3),
    X, y,
    train_window_bars=750,    # ~3y daily expanding/rolling
    test_window_bars=90,
    step_bars=90,
    embargo_bars=21,          # ≈ longest horizon (1–3 weeks)
)
oos = concat_oos_probs(results)   # stitched OOS probabilities for honest metrics
```

> **Decision D-9 (Validation protocol).** *Recommendation:* **purged
> walk-forward with horizon-scaled embargo for primary reporting**, and **build
> CPCV → PBO** as the overfitting referee before any "promote to paper trading"
> decision. CPCV is the 2024+ best practice but is heavier; phase it in.

### 5.7 Stage 7 — Overfitting defenses & statistical verification

See the dedicated deep-dive in **§7** (this is the project's core risk). In
pipeline terms, this stage = leakage audit + regularization + feature
selection + DSR/PBO + permutation test, run *before* trusting any backtest.

### 5.8 Stage 8 — Economic backtest

A good prediction metric is necessary but not sufficient; the model must
survive a **cost-aware, regime-aware** economic simulation.

- **Convert prediction → position** (threshold for classification, sized by
  calibrated probability or predicted vol for regression). CryoQuant:
  `prob_from_model` → `ProbSignal`; `pick_threshold` to choose the operating
  point on a *validation* fold, not the test fold.
- **Simulate with costs:** `simulate(signal, bars, hold_h, fee_bps=…)`. Use
  realistic crypto **fees + slippage** (e.g., 5–10 bps round trip is a starting
  assumption; widen for size). Execution at **next bar open**, never same-bar
  close (lookahead).
- **Metrics:** CAGR, Sharpe/Sortino/Calmar, max drawdown, profit factor,
  hit-rate, turnover, **Information Coefficient (IC) and ICIR**
  (`backtest/metrics.py`).
- **Regime decomposition:** split OOS into bull/bear (e.g., price vs 50/200-day
  MA), high/low vol, pre/post major events. A model that only works in one
  regime is not robust — report per-regime metrics.
- **Robustness:** `deflated_sharpe(...)` and `bootstrap_ci(...)` already exist;
  add **PBO** from CPCV paths.

> **Principle P-7 — Optimize economic outcomes, not error metrics.** Final
> selection is on risk-adjusted, cost-after returns and robustness statistics,
> not on MAE/AUC alone.

#### 5.8b The option-selling backtest (Goal 2 — the real economic test)

The spot `simulate` above tests the *directional* model. The option book needs a
**short-option P&L simulation against real Deribit chains**, which CryoQuant
*almost* has: `backtest/option_lookup.evaluate(signal, bars, dte, delta,
exit_rule, chains_dir)` already loads chains, selects **delta-targeted** call+put
legs, and marks P&L to exit — but it models a **long** straddle/strangle (entry
at ask, exit at bid). For Goal 2 we **invert it to a seller**: credit received at
**bid** at entry, debit paid at **ask** to close (or intrinsic at expiry), P&L =
`credit − cost`. **Build: a short-vol variant of `evaluate`** (or a `side="sell"`
flag) — small, high-leverage change.

Backtest design points specific to short vol:

- **Signal → action mapping.** The model's calibrated P(OTM) and directional
  tilt decide: *whether* to sell this period (entry-timing gate), *which side(s)*
  (put / call / strangle), and *which delta* (where physical P(OTM) > implied).
  `ProbSignal` + `pick_threshold` choose the gate; `delta` and `dte` come from
  the distributional head.
- **Costs & frictions.** Deribit fees, **bid/ask spread** (already in the chain),
  and slippage. Low-delta options have wide relative spreads — model this
  honestly or the edge is illusory.
- **Management.** Encode roll/close-early/stop via `ExitRule(hold_h, tp_multiple,
  stop_multiple)`. Sweep these as strategy parameters (counts toward trial
  budget for DSR).
- **Margin / liquidation.** Short options require margin; a naive backtest that
  ignores margin calls overstates capacity. At minimum, cap position size and
  report worst-case mark-to-market drawdown.

**Metrics that decide success (short-vol-specific):**

| Metric | Why |
|---|---|
| **Realized OTM-rate vs predicted** | calibration of the core bet (§7.4b) |
| **Realized OTM-rate vs option δ** | did we beat the market-implied probability? |
| **Premium captured / expectancy per trade** | gross edge |
| **CVaR / max loss per trade / worst-week** | the negative-skew tail that kills short vol |
| **Deflated / Probabilistic Sharpe (skew-aware)** | honest risk-adjusted edge |
| **vs naive seller baseline** | does the ML add value over raw VRP harvesting? |

> **Principle P-7b — Beat the naive seller, after costs and tails.** The promotion
> bar for Goal 2 is not "profitable" — it is "**beats an unconditional δ-delta
> seller on deflated, after-cost, tail-aware terms**, with calibrated P(OTM)".

### 5.9 Stage 9 — Final frozen hold-out

> **Principle P-8 — The hold-out is sacred.** Reserve the most recent slice
> (e.g., last 12–18 months) as a **completely untouched** hold-out. It is
> evaluated **once**, after the entire research pipeline (features, labels,
> models, hyperparameters, thresholds) is **frozen**. If you peek, it's burned —
> cut a new one or accept the optimism bias.

Suggested split skeleton (adjust per asset history):

```text
Development (train + CV + tuning):   inception → ~2024-06
Final hold-out (touch once):         ~2024-06 → present
```

**BTCpredict v1 (SPEC §13, `holdout.yaml`):** Phase 7 runs in two layers before
chain P&L: **(7A)** refit all 48 models once on full dev and predict hold-out
bars (no new HPO); **(7B)** chain backtest on **Apr 2025+** only where Deribit
parquets exist. Signal policy frozen from Phase 6 dev proxy; chain `δ × DTE ×
structure` grid is **report-all** (no hold-out selection). **Primary gate:**
physical P(OTM) vs market δ (G2′); economic Sharpe gates are secondary. A null
hold-out result reported honestly still completes the study.

### 5.10 Stage 10 — Paper trading, monitoring, retraining  [future scope]

Out of scope for v1 implementation but specify the seams now so we don't paint
ourselves into a corner:

- **Paper trading:** run the frozen system forward on live data with no capital;
  validate execution, slippage, latency, signal stability before any real use.
- **Drift monitoring:** rolling IC on live predictions (alert if < ~0.02);
  feature drift via **PSI** (> 0.2 = shift); concept-drift libs (`river`,
  `evidently`).
- **Retraining cadence:** rolling-window retrain (e.g., last 365–750d) every
  ~30 days; too frequent overfits recent noise, too rare goes stale. This is
  itself a hyperparameter to validate, not a guess.

---

## 6. Guiding principles (invariants for the spec & implementation)

These are the non-negotiables. The SPEC must encode them as checks/tests, not
just prose. (Consolidated from both input docs and the López de Prado canon.)

- **P-0 Calibrated humility** — default prior is "no edge"; treat too-good
  results as bugs until disproven.
- **P-0b Calibration is the product (Goal 2)** — for the option book, a
  calibrated probability beats an accurate point forecast; the edge is the gap
  between physical and risk-neutral (delta-implied) P(OTM).
- **P-1 The harness outranks the model** — build/trust validation before
  chasing performance.
- **P-2 Reproducible & stage-isolated** — every result reconstructable from
  immutable raw + code + config; stages don't mutate upstream.
- **P-3 Raw data is immutable** — store as received; clean into new artifacts.
- **P-4 Causality / no leakage** — features use only past data; targets are
  shifted; transforms fit on train only.
- **P-5 Labels dominate models** — invest in label design; make them
  economically meaningful and vol-aware.
- **P-6 Validation simulates deployment** — chronological, purged, embargoed;
  never shuffle time.
- **P-7 Economic objective** — select on risk-adjusted, cost-after returns +
  robustness, not error metrics alone.
- **P-7b Beat the naive seller (Goal 2)** — the option book must beat an
  unconditional δ-delta seller on deflated, after-cost, tail-aware terms.
- **P-8 Sacred hold-out** — touch the final hold-out exactly once.
- **P-9 Account for multiple testing** — track the number of trials; deflate
  Sharpe; estimate PBO; report White's Reality Check / SPA where applicable.
- **P-10 Simpler beats fancier** — a simple model with rigorous validation
  outperforms a sophisticated one with weak validation. Prefer the parsimonious
  model that survives.

---

## 7. Overfitting & verification — deep dive

This is *the* place this project lives or dies. Two failure modes dominate:
**data leakage** (optimistic in-sample that collapses OOS) and **selection bias
/ backtest overfitting** (picking the luckiest of many trials).

### 7.1 Leakage taxonomy (audit each one explicitly)

| Leak | How it sneaks in | Mitigation |
|---|---|---|
| **Lookahead in features** | rolling/indicator without proper shift; using current-bar close to predict same bar | compute on closed bars; shift target by horizon |
| **Scaler/winsor on full data** | `fit_transform` on all rows | fit on train split only, transform others |
| **Hyperparameter/threshold on test** | tuning or picking operating point on the test fold | inner validation fold; nested CV |
| **Target encoding on full data** | category means computed over all rows | compute from train only |
| **Overlapping labels across folds** | T+H label at *t* correlates with neighbors | **purge + embargo** |
| **Macro release-time** | aligning on reference date not release date | release-date timestamps / event flags |
| **Survivorship / symbol selection** | choosing assets that did well ex-post | fix the universe a priori |

### 7.2 Regularization

- **Trees:** shallow `max_depth` (≤4–5), `min_child_samples`/`min_data_in_leaf`
  high, `subsample`/`colsample_bytree` < 1, L1/L2 (`reg_alpha`/`reg_lambda`),
  early stopping on validation loss.
- **Linear:** Ridge/Lasso/ElasticNet.
- **NN (Phase 2):** dropout, weight decay, layer norm, early stopping, gradient
  clipping.

### 7.3 Feature selection (cut variance)

- Start < 30, add only if OOS improves.
- Drop pairwise-correlated features (|ρ| > 0.95; keep one per cluster).
- **Permutation importance** and **SHAP** (`shap.TreeExplainer`) to rank; drop
  near-zero / unstable-across-folds features.
- **Stability check:** top-10 feature importances should be roughly stable
  across temporal folds; unstable rankings = noise-fitting.

### 7.4 Statistical verification (the multiple-testing referee)

- **Deflated Sharpe Ratio (DSR) / Probabilistic Sharpe Ratio (PSR)** — correct
  the Sharpe for #trials, skew, kurtosis. CryoQuant: `deflated_sharpe(sharpe,
  n_trials, n_obs, skew, kurt)` **already exists** — feed it the *true* trial
  count (every config you tried).
- **Probability of Backtest Overfitting (PBO)** — fraction of CPCV paths where
  the in-sample-best config underperforms OOS. PBO < 0.25 = strong; 0.25–0.5 =
  uncertain; > 0.5 = reject. **Build (needs CPCV paths).**
- **White's Reality Check / Hansen's SPA** — test whether the best of many
  strategies beats a benchmark beyond chance.
- **Bootstrap CIs** on trade metrics — `bootstrap_ci(...)` exists.

### 7.4b Calibration verification (the Goal-2 crux)

Because the option book sells based on probabilities, calibration is a
*first-class* verification step, not a nicety:

- **Reliability diagram + ECE + Brier** on the OOS exceedance/OTM predictions
  (`models/metrics.reliability_diagram`, `compute_metrics` give ECE/Brier).
  Predicted 10% must realize ~10%.
- **Physical vs risk-neutral overlay:** for each (δ, H), compare the model's
  calibrated physical P(OTM) to the option-implied P(OTM)≈δ. Edge lives where
  physical > implied by more than costs. Plot it; it *is* the strategy thesis.
- **Calibration stability across regimes/time:** a model calibrated only in calm
  regimes will mis-size tails in stress. Check reliability per regime and per
  OOS sub-period — short vol fails exactly when calibration drifts.
- **Tail focus:** standard calibration metrics average over the whole
  distribution; weight or stratify on the *tail bins* (low-delta region) we
  actually trade.

### 7.5 Diagnostic checks (run every model)

1. **Train-vs-val gap:** train error ≪ val error (e.g., >2×) ⇒ overfit; add
   regularization / reduce depth.
2. **Degradation over time:** compare early vs late OOS halves; large decay ⇒
   non-stationarity not handled.
3. **IC stability:** IC roughly stable month-to-month; high variance ⇒ noise.
4. **Permutation test (leakage smoke alarm):** shuffle the target, retrain;
   performance must collapse to ~0. If a shuffled-target model still "works",
   there is leakage.
5. **Regime split:** report metrics per bull/bear/high-vol/low-vol.

> **Principle P-9 (restated operationally).** The number you report as "edge"
> must be a *deflated*, *purged*, *out-of-sample*, *cost-after*, *trial-count-
> aware* number. Anything else is marketing.

---

## 8. Risks & failure modes (and how we'll know)

| Risk | Symptom | Guard |
|---|---|---|
| **Leakage** | OOS R² > 0.2, dir. acc. > 60% sustained | permutation test, leakage audit (§7.1) |
| **Backtest overfitting** | great IS, poor OOS; best config fragile | CPCV + PBO, DSR with true trial count |
| **Non-stationarity / regime shift** | late-period decay, bull-only edge | regime split, rolling retrain, walk-forward |
| **SOL short history** | unstable SOL model, few cycles | pool/transfer (D-7), or defer SOL |
| **Tiny sample, many features** | high variance, unstable importances | feature budget (D-6), regularization |
| **Cost blindness** | profitable gross, negative net | fees+slippage in every backtest |
| **Macro alignment lookahead** | macro "predicts" suspiciously well | release-date alignment, event flags |
| **Survivorship/scope creep** | universe chosen ex-post | freeze universe a priori |
| **Data vendor cost/licensing** | paid on-chain dependency creep | free-only v1 (D-3) |
| **Multi-testing inflation** | many configs, one "winner" | log every trial; deflate |
| **(Goal 2) Miscalibration** | predicted P(OTM) ≠ realized | reliability/ECE per regime (§7.4b); recalibrate |
| **(Goal 2) Negative-skew blow-up** | high win-rate, rare huge loss | **defined-risk default (D-16)**, CVaR/max-loss caps, tail-aware DSR, position sizing |
| **(Goal 2) Vol/jump regime** | short vol sold into a crash | vol-expansion forecast head, regime gate |
| **(Goal 2) Option illiquidity / wide spreads** | gross edge vanishes net of spread | model bid/ask honestly; BTC/ETH only; cap size |
| **(Goal 2) SOL options thin/short** | not backtestable with fidelity | defer SOL options book (D-15) |
| **(Goal 2) Margin / liquidation** | ignored in naive backtest → overstated capacity | margin model, size caps, MtM drawdown |
| **(Goal 2) Surface lookahead** | IV features peek at expiry-window surface | use only entry-time surface |

---

## 9. CryoQuant reuse map (build vs. reuse)

The spec must respect this table. **Reuse** = import existing API; **Build** =
net-new, must be specified; **Extend** = add to an existing module.

| Pipeline need | CryoQuant status | Action |
|---|---|---|
| OHLCV ingest/cache (BTC, ETH) | `data.ingest`, `load_track`, parquet+DuckDB | **Reuse** |
| SOL OHLCV | not registered | **Extend** (`cryocore/instruments.py` + ingest) |
| Funding rate / open interest | `binance_perp.fetch_funding` exists, not wired to loader | **Extend** |
| On-chain / Fear&Greed / DefiLlama | none | **Build** (new sources + macro_store) |
| **Deribit option chains (BTC/ETH)** | `data/sources/deribit_options.py` (read-only parquets) | **Reuse** |
| **SOL option chains** | thin/short or absent | **Defer** (D-15) |
| Macro (DXY, rates, VIX, …) | FRED/CBOE/Yahoo sources + `MacroFeatures` | **Reuse** |
| Multi-track alignment | `DataPanel`, `align_series` | **Reuse** |
| Technical features | 40+ primitives + builders | **Reuse** |
| Crypto on-chain features | none | **Build** (new tier-2 builder) |
| **Options-surface features (IV/skew/term/VRP/IV rank)** | `features/options.py` (`dvol_30d`, `iv_minus_rv`, `dvol_rank_252`, `dvol_rank_90`, `dvol_chg_7d`, `term_slope`, `risk_reversal_25d`, `vol_of_vol`) | **Reuse** |
| Binary direction/magnitude label | `ForwardReturnLabeler` | **Reuse** |
| Regression (forward-return / vol) label | none | **Build** |
| **Exceedance / OTM-expiry label (per δ, H)** | none | **Build** (Goal 2) |
| Triple-barrier (+ meta-label) | none | **Build** |
| Multi-horizon label helper | none | **Build** (thin) |
| GBDT classifier + calibration | `TabularModel` (LightGBM+isotonic) | **Reuse** |
| GBDT regressor / XGB / CatBoost members | none | **Extend** |
| **Distributional / quantile / vol model (NGBoost, quantile-LGBM, GARCH/HAR)** | none | **Build** (Goal 2) |
| Naive / linear / ARIMA-GARCH baselines | `baselines.RuleModel` only | **Build** (reference predictors) |
| Walk-forward fit + OOS stitching | `walk_forward_fit`, `concat_oos_probs` | **Reuse** |
| Purged k-fold + embargo | `purged_kfold` exists, not wired into fit loop | **Extend** (wire in) |
| CPCV + PBO | none | **Build** |
| Permutation/leakage test harness | none | **Build** |
| Calibration metrics (Brier/ECE/reliability) | `metrics.compute_metrics`, `reliability_diagram` | **Reuse** |
| Deflated Sharpe, bootstrap CI | `robustness.py` | **Reuse** |
| Prob→signal→spot backtest (costs) | `prob_from_model`, `simulate`, `pick_threshold` | **Reuse** |
| **Option-leg P&L vs Deribit chains (delta-targeted)** | `backtest/option_lookup.evaluate` + `ExitRule` (models a *buyer*) | **Extend** (add `side="sell"` short variant) |
| **Short-vol metrics (OTM-rate vs δ, CVaR, premium)** | partial (`win_rate`, `expectancy` in `OptionResult`) | **Build** |
| Regime-split / IC reporting | `backtest/metrics.py` (IC), partial | **Extend** |
| Model registry + artifacts | DuckDB registry, joblib save | **Reuse** |
| HTML reports + study manifest/index | `reporting/`, `backtest/reports.py` | **Reuse** |
| Drift monitoring (PSI/IC), paper trading | none | **Build** (future phase) |

**Canonical starting references:** `scripts/ml_multi_source.py` and
`tests/live/test_phase3_live.py` show the `DataPanel → builders →
ForwardReturnLabeler → walk_forward_fit(TabularModel) → prob_from_model →
simulate` flow (Goal 1). **`scripts/ema_cross_options_backtest.py` +
`backtest/option_lookup.py`** show the signal→Deribit-option-leg flow we invert
for the short-vol book (Goal 2). The `reference/long_tradable_options/` tree is a
*long*-strangle precedent — same infra, opposite sign.

---

## 10. References

### Books (the canon)

- **Marcos López de Prado — _Advances in Financial Machine Learning_** (Wiley,
  2018). The core methodology source: labeling (ch.3, triple-barrier),
  cross-validation in finance (ch.7, purging+embargo), backtesting via CV
  (ch.12, CPCV), feature importance (ch.8).
- Ernest Chan — _Algorithmic Trading_ and _Machine Trading_.
- Hastie, Tibshirani & Friedman — _The Elements of Statistical Learning_.
- Goodfellow, Bengio & Courville — _Deep Learning_.
- Martin Kleppmann — _Designing Data-Intensive Applications_ (data layer
  discipline / immutability).

### Key papers — methodology

- Bailey, Borwein, López de Prado & Zhu (2017), *The Probability of Backtest
  Overfitting*, J. Computational Finance 20(4). [DOI 10.21314/JCF.2016.322]
- Bailey & López de Prado (2014), *The Deflated Sharpe Ratio*, J. Portfolio
  Management. (and 2012 *Probabilistic Sharpe Ratio*).
- White (2000), *A Reality Check for Data Snooping*, Econometrica.
- Hansen (2005), *A Test for Superior Predictive Ability (SPA)*.
- Bergstra & Bengio (2012), *Random Search for Hyper-Parameter Optimization*,
  JMLR.
- Lundberg & Lee (2017), *A Unified Approach to Interpreting Model Predictions*
  (SHAP), NeurIPS.
- *Backtest overfitting in the machine-learning era* (2024), Knowledge-Based
  Systems — CPCV vs k-fold/purged-kfold/walk-forward on PBO & DSR.

### Key papers — tabular & time-series model evidence

- Grinsztajn, Oyallon & Varoquaux (2022), *Why do tree-based models still
  outperform deep learning on typical tabular data?*, NeurIPS D&B —
  <https://arxiv.org/abs/2207.08815>
- *Is Deep Learning finally better than Decision Trees on Tabular Data?* (2024)
  — <https://arxiv.org/html/2402.03970v2>
- *TabArena: A Living Benchmark for ML on Tabular Data* (2025) —
  <https://arxiv.org/pdf/2506.16791> · <https://tabarena.ai>
- *OmniTabBench* (2026) — <https://arxiv.org/html/2604.06814v1>
- Time-series DL/foundation: TFT (Lim et al. 2019), N-BEATS (Oreshkin 2019),
  N-HiTS (2022), PatchTST (2022), TimesNet (2023), TimeMixer (2024); foundation:
  **TimesFM** (Google), **Chronos** (Amazon).

### Key papers — crypto-specific

- *On Forecasting Cryptocurrency Prices: ML, DL, and Ensembles* (MDPI Forecast,
  2023) — <https://doi.org/10.3390/forecast5010010> (first TFT on this task).
- *ML approaches to cryptocurrency trading optimization* (2025) —
  <https://doi.org/10.1007/s44163-025-00519-y> (GBDT > LSTM evidence).
- *Crypto Price Prediction using LSTM+XGBoost* (arXiv 2506.22055, 2025) —
  <https://arxiv.org/html/2506.22055v1> (hybrid pattern).
- *Survey of NN methods for token price prediction* (PeerJ CS, 2025) —
  <https://peerj.com/articles/cs-3702>
- *Cryptocurrency Time Series Forecasting … Ensemble & DL: A Review* (ARO, 2024)
  — <https://aro.koyauniversity.org/index.php/aro/article/view/2280>

### Libraries & open-source repos

- ML / boosting: `scikit-learn`, `lightgbm`, `xgboost`, `catboost`.
- Financial ML: **`mlfinpy`** / `eslazarev/purged-cross-validation` (MIT, purged
  CV + CPCV + DSR/PSR — <https://github.com/eslazarev/purged-cross-validation>).
  Note: `mlfinlab` (Hudson & Thames) is now **commercial/closed** — do *not*
  take it as an open dependency.
- Time series DL: `darts`, `neuralforecast`, `pytorch-forecasting`, `gluonts`.
- Features: `pandas-ta`, `TA-Lib`, `tsfresh`, `featuretools`.
- HPO: `optuna`, `hyperopt`, `ray[tune]`. Explainability: `shap`.
- Drift/monitoring: `river`, `evidently`. Experiment tracking: `mlflow`,
  `wandb`. Backtest: `vectorbt`, `backtrader` (CryoQuant has its own `simulate`).

### Data sources (free unless noted)

- **OHLCV:** Binance (`ccxt`/`python-binance`), CoinGecko, CryptoCompare.
- **Macro:** FRED (`fredapi`), Yahoo (`yfinance`), CBOE (VIX/MOVE).
- **Derivatives:** Binance/Bybit perp funding & open interest APIs.
- **Sentiment:** alternative.me Crypto **Fear & Greed Index**.
- **On-chain/flows:** **DefiLlama** (stablecoins, TVL — free), blockchain.com
  charts (BTC, free), **Coin Metrics community** (free tier), **Dune** (free
  queries). Paid/richer: **Glassnode, CryptoQuant, Nansen**.

---

## 11. Decision register

**Status legend:** ✅ Locked (decided 2026-06-28) · ⚙️ Technical default
(accepted; revisit only if needed). Locked decisions reflect the principal's
explicit choices and are binding inputs to `SPEC.md`.

| # | Decision | Resolution | Status |
|---|---|---|---|
| **D-1** | Target framing | **Two heads:** probabilistic **direction+magnitude** (Goal 1 / side) **+** **distributional/exceedance + vol** (Goal 2 / P(OTM)); log-return regression as benchmark | ✅ |
| **D-2** | Model roadmap | Phase 1 **GBDT + quantile/vol heads + baselines**; Phase 2 sequence/hybrid + NGBoost/conformal | ⚙️ |
| **D-3** | Data scope for v1 | **Free sources only**; defer paid on-chain. **+ Deribit options surface** (already wired) for Goal 2 | ✅ |
| **D-4** | History depth & start | **≥3y** daily; per-asset since inception | ⚙️ |
| **D-5** | Bar cadence | **Daily** primary; hourly only to build daily features | ⚙️ |
| **D-6** | Feature budget | **~30–100** selected features (+ options-surface features for Goal 2) | ⚙️ |
| **D-7** | Per-asset vs pooled vs transfer | Separate for **BTC/ETH**; **pool or transfer** for **SOL** | ⚙️ |
| **D-8** | HPO method | **Random→Optuna** inside **nested** validation; log trial count | ⚙️ |
| **D-9** | Validation protocol | **Purged walk-forward + embargo** now; **build CPCV→PBO** as referee | ⚙️ |
| **D-10** | SOL in v1? | **SOL directional model: yes** (pooled/transfer). SOL options book: deferred (see D-15) | ✅ |
| **D-11** | End goal | **Dual:** (1) directional forecast machine; (2) **primary** = signal for a short-vol option book. Goal 2 drives label/eval/costs | ✅ |
| **D-12** | Success criteria / promotion bar | **Maximize risk-adjusted return (deflated Sharpe) with a hard CVaR/tail-loss cap.** Goal 1: OOS dir-acc > naive, IC > 0.03. Goal 2: low-ECE calibrated P(OTM), realized-OTM beats δ, **beats naive seller** after costs. Both: **DSR > 0**, **PBO < 0.25** | ✅ |
| **D-13** | Option structure to sell | **Model-tilted strangles** (lean to a side when the directional head is confident) at target δ | ✅ |
| **D-14** | Tenor / DTE & management | **Parameterize & sweep** DTE per horizon (~1–2/7/14–30) + `ExitRule` (hold/TP/stop); backtest decides | ✅ |
| **D-15** | Underlying for options book | **BTC + ETH** for v1; **defer SOL options** (thin/short) | ✅ |
| **D-16** | Tail-risk structure | **Build naked AND defined-risk (spreads/condors); defined-risk is the tail-safe default** | ✅ |
| **D-17** | Near-term intended use | **Research deliverable / signal engine** now; live trading later. Bake in honest costs/spreads, but full margin/latency realism is Phase 2 | ✅ |

### Locked v1 scope

> **Use:** research signal engine (live later, D-17). **Cadence:** daily. **Assets:**
> BTC + ETH (SOL **directional** via pooling/transfer; **SOL options deferred**).
> **Data:** free sources + Deribit options surface (DVOL + chains ~Apr 2025+).
> **Heads:** probabilistic
> **direction+magnitude** (Goal 1 / which side) **+** **distributional/exceedance +
> realized-vol** (Goal 2 / P(OTM) & VRP timing), at **T+1 / T+5 / T+10–21**.
> **Models:** LightGBM (+ quantile/GARCH) vs naive/Ridge **+ naive-seller**
> baselines. **Option book:** model-tilted short strangles, **both naked and
> defined-risk** variants compared, DTE/management **swept**, evaluated against
> **real Deribit chains on hold-out only** (~Apr 2025+; dev uses DVOL + calibration). **Objective:** risk-adjusted return (deflated Sharpe) with
> a **hard CVaR/tail cap**. **Validation:** purged walk-forward + embargo;
> **calibration (ECE/reliability) is a headline metric**; **DSR + permutation
> test**; **frozen hold-out touched once**. **Phase 2:** CPCV/PBO,
> NGBoost/conformal, sequence/hybrid models, full execution/margin realism.

---

## 12. Next steps

The §11 decision register is **resolved** as of 2026-06-28 (D-1, D-3, D-10–D-17
locked; D-2, D-4–D-9 accepted as technical defaults). Remaining work:

1. **Agent:** turn the locked decisions into `SPEC.md` (file-level tasks, module
   contracts, the §9 build items, test plan, success gates). Cite specific
   sections of this brief. ✅ Done.
2. **Agent:** scaffold `studies/BTCpredict/` (`universe.yaml`, `config.yaml`,
   `src/`, `tests/`) following the `studies/cdx/` precedent. ✅ Phase 0 done;
   **`DATA_SOURCES.md` signed off 2026-06-28**; `universe.yaml` generated.
3. ✅ **Phase 1 (data ingest + QA)** complete 2026-06-28 — connectors per SPEC §7;
   manifest frozen (`data/ingest_manifest.json`, **33 series ok**, H1/H2 skipped);
   QA gate passed (`run_phase1_qa.py`, 0 errors).
4. ✅ **Phase 2 (feature engineering)** complete 2026-06-28 — [`FEATURE_CATALOG.md`](FEATURE_CATALOG.md)
   implemented; `data/features.parquet` + QA pass (`run_phase2_qa.py`, 0 errors);
   `phase2_complete: true`. See SPEC §8.4 for implementation notes (chain schema,
   datetime alignment, BTC-only chain parquets).
5. ✅ **Phase 3 (labels)** complete 2026-06-28 — [`LABEL_CATALOG.md`](LABEL_CATALOG.md)
   families 1–6 (family 7 path/touch deferred Phase 6); `data/labels.parquet` +
   QA pass (`run_phase3_qa.py`, 0 errors, 1 warning); `phase3_complete: true`.
   See SPEC §9.4.
6. **Phase 4 (models)** — next per SPEC §10.
7. **Maintenance (ongoing, not blocking):** re-run `run_phase1_ingest.py` for forward
   collection (Farside ETF, Xoomar OI, Deribit chains); re-run `run_phase2_features.py`
   and `run_phase3_labels.py` after material ingest; re-run QA after rebuild.
8. **Open for later (not blocking):** exact CVaR/tail-loss cap level and target
   capital scale (D-12/D-17 left qualitative); naked-vs-defined-risk delta and
   wing-width grid (D-16); retraining cadence (D-9/Stage 10).

---

*This brief is a living reference. The decision register (§11) is the source of
truth for locked choices; update it (with dates) as decisions evolve. The SPEC
and implementation should cite specific sections of this document.*













