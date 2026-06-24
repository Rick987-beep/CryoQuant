# CDX.NA.IG Crunch Fund — Run Specification

**Mandate codename:** `crunch_fund`  
**Instrument:** Markit CDX.NA.IG, 5-year on-the-run  
**Status:** Spec only — distinct from the balanced multi-overlay study (`PLAN.md`)

---

## 1. Investment thesis (plain language)

We are designing a **five-year, $5 million expression** on a single hypothesis:

> North American investment-grade credit will experience a **severe dislocation** within the fund’s life — a “credit crunch” in which CDX.NA.IG spreads move from compressed levels to a **large widening** — and we want to be **long protection** when that happens.

This is not a balanced carry book. It is closer to a **term catastrophe trade**: accept that calm years are a cost of doing business, and optimize for **convex payoff** if spreads “explode.” Any yield or funding overlay is **optional cost mitigation**, not the objective function.

---

## 2. Fund parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| **AUM / collateral** | **$5,000,000** | Total posted collateral for the fund |
| **Horizon** | **5 years** (max) | Hard stop at fund maturity; positions flattened or expired |
| **Instrument** | **CDX.NA.IG** (5Y on-the-run) | Index CDS; long protection = long spread |
| **Primary direction** | **Long protection** | Profit when IG spreads widen |
| **Loss tolerance** | **High** | Fund may approach **full collateral depletion** if no crunch occurs |
| **Minimum collateral** | **Practical floor** (TBD in sim) | Real desks need margin to hold lines; we model a small residual (e.g. 1–5% of initial) rather than literal zero |

**Interpretation of “we can spend the entire $5M”:**  
Over five calm years, cumulative carry, financing, and roll costs may consume most or all of the fund. That outcome is **acceptable** under this mandate. Success is **not** measured by ending NAV above par in benign markets.

---

## 3. Objectives (ranked)

### 3.1 Primary — crisis payoff (investor target: **10×**)

**Investor expectation.** If a serious credit crunch occurs during the fund’s life, LPs expect roughly a **10× return on capital** — i.e. **$50M back on $5M posted** (NAV peak **10.0×** in the crisis, or equivalently **+$45M** crisis PnL on collateral). This is the mandate’s defining KPI. Anything that optimizes calm-path NAV at the expense of crisis magnitude is mis-specified.

**Reality check (prior backtests, same cost model).** Our balanced study never approached 10× on COVID-scale moves:

| Configuration | COVID episode PnL | Implied crisis NAV bump (on $5M) |
|---------------|-------------------|----------------------------------|
| Long protection, $100M notional, full collateral | +$3.35M | **~1.67×** (peak during episode) |
| Tail slice only ($2.5M slice, $100M N) | +$2.97M | **~1.59×** on $5M if attributed to fund |
| Portfolio mutex (tail + Y8) | +$2.96M | **~1.59×** |

COVID in our data is roughly **+69 bps** (53 → 122) on a standing long. A **10×** outcome requires a much larger widening, higher notional, holding through the peak (no early exit at 100 bps), or a combination. The crunch-fund run must **measure distance to 10×** explicitly, not treat “+$3M in COVID” as success.

**Episode tiers** (different bars for “crisis happened”):

| Tier | Label | Definition | 10× feasible? |
|------|-------|------------|---------------|
| **A** | `severe` | Observed COVID window (Feb–Apr 2020) | Unlikely at prudent leverage; **benchmark only** |
| **B** | `explosion` | Spread ≥ 150 bps **or** Δspread ≥ +100 bps in 90d | Plausible at high notional / no early exit |
| **C** | `hypothetical_10x` | Synthetic path: entry 50 bps → 250+ bps (stress envelope) | **Target design case** for structure sizing |

Scoring uses **Tier B and C** for the 10× target; Tier A reports how far we fall short of LP expectations on a known historical crunch.

---

#### Primary metrics (revised)

Metrics are computed **per fund vintage** and **per crisis episode**, then aggregated. Leaderboard ranks configurations that get **closest to 10×** when a tier-B/C event occurs.

| # | Metric | Definition | Role |
|---|--------|------------|------|
| **1** | `crisis_nav_peak_multiple` | max(NAV) during episode ÷ NAV at episode start | **Headline KPI** — direct mapping to “10×” |
| **2** | `crisis_pnl_usd` | Sum of daily PnL over episode window | Dollar payoff; must be ≥ **$45M** for 10× |
| **3** | `crisis_return_on_capital` | `crisis_pnl_usd / initial_collateral` | Same as (multiple − 1); target **≥ 9.0** (i.e. 10× total) |
| **4** | `distance_to_10x` | `10.0 − crisis_nav_peak_multiple` (0 = hit target) | Primary **sort key** (minimize) |
| **5** | `hit_10x` | Boolean: `crisis_nav_peak_multiple ≥ 10.0` | Pass/fail per episode |
| **6** | `notional_for_10x` | Smallest notional such that modelled Tier-C path reaches 10× (holding exit rule fixed) | Feasibility / leverage frontier |

**Hard gates (not weighted — must pass):**

| Gate | Rule |
|------|------|
| `in_market_at_onset` | Long protection open on first day of episode (else crisis payoff = 0 by construction) |
| `no_early_exit_penalty` | If exit rule fires before episode peak, report `capture_ratio` = realized peak NAV / theoretical peak NAV |

**Demoted / reporting only** (removed from primary composite score):

| Metric | Why demoted |
|--------|-------------|
| `time_in_protection` | Necessary condition, not sufficient — binary gate instead |
| `max_spread_capture` | Absorbed into `crisis_nav_peak_multiple` |
| Full-sample NAV / CAGR | Wrong objective for this mandate |

**Proposed composite score** (for ranking configs among those that pass gates):

| Component | Weight |
|-----------|--------|
| `distance_to_10x` (inverted percentile) | **50%** |
| `crisis_nav_peak_multiple` on Tier-B/C episodes | **30%** |
| `hit_10x` rate across tier-B/C vintages | **20%** |

*Tier-A (COVID) reported separately as “historical benchmark” — not used to declare victory.*

---

#### Payoff feasibility (order-of-magnitude)

For long protection, crisis MTM scales approximately as:

```
crisis_pnl ≈ notional × duration × Δspread(bps) / 10,000
```

On **$5M collateral**, reaching **+$45M** (10×) requires:

| Δspread (bps) | Notional required (duration = 5) |
|---------------|----------------------------------|
| 70 (COVID-scale) | **~$1.3B** — not credible on $5M IM |
| 100 | **~$900M** |
| 150 (“explosion”) | **~$600M** |
| 200 | **~$450M** |

Carry bleed scales linearly with the same notional. The backtest must trace this **convexity–bleed frontier**: the highest notional that (a) still leaves the fund alive until a tier-B event and (b) delivers the largest `crisis_nav_peak_multiple`.

**Implication for the run:** extend notional sweep to **$100M – $1B** (or solve for max notional given 5y burn budget) and prioritize **no early exit** variants in Tier B/C scoring. Early exit at 100 bps caps upside and makes 10× impossible on COVID-like paths.

### 3.2 Secondary — carry mitigation (optional)

If a **yield overlay** or **light short-protection** rule reduces bleed without materially cutting crisis upside, include it — but only as a **tie-breaker** or **constraint**, not as a co-equal goal.

**Secondary metrics (low weight or hard filters only):**

| Metric | Role |
|--------|------|
| `calm_burn_usd` | Total PnL on spread &lt; 80 bps — minimize, but not at expense of crisis PnL |
| `years_to_depletion` | Years until NAV hits floor — report, do not optimize for NAV preservation |
| `carry_funding_ratio` | Relevant only if yield overlay is enabled |

**Design rule:** Any overlay that reduces crisis PnL by more than **X%** (e.g. 10%) versus pure tail is **rejected**, regardless of calm savings.

---

## 4. What we are *not* trying to do

| Prior study (`PLAN.md`) | This run (`crunch_fund`) |
|-------------------------|--------------------------|
| Net calm + stress into a “portfolio shape” | **Stress-only** payoff profile |
| Carry funding ratio as a first-class KPI | Carry is a **budget constraint**, not a goal |
| Mutex tail + yield as co-equal legs | Tail (or max convexity) **dominates**; yield is optional subsidy |
| Maximize full-sample NAV / CAGR | Accept **sub-1.0×** or near-zero terminal NAV in no-event paths |
| 14-year full history as primary horizon | **Rolling 5-year fund vintages** as the unit of analysis |

---

## 5. Positioning & leverage envelope

The fund should explore **how much protection** $5M can support and for how long.

**Sweep dimensions:**

| Dimension | Range (initial) | Question |
|-----------|-----------------|----------|
| **Notional (long protection)** | $100M – $1,000M | Locate notional needed for 10× on tier-B/C paths |
| **Entry regime** | Spread &lt; 50 / 60 / 70 bps | Enter only in compression |
| **Hold rule** | Standing vs event-triggered | Always on vs re-enter after exits |
| **Exit rule** | **No exit** (hold to maturity) / exit ≥ 150 / 200 bps only | Early exit at 100 bps **caps** 10× — deprioritize in primary sweep |
| **Fund maturity** | Exactly 5y from inception | Force flat at T+5y |
| **Yield subsidy** | Off / Y8-lite / Y1 | Secondary only |

**Leverage framing (Ackman-style):**  
At 60 bps entry, 5Y duration, $100M notional ≈ $600k/year gross carry ≈ **12% of $5M collateral per year**. Five calm years ≈ **60% bleed** before MTM — consistent with “fund can be largely depleted.”

---

## 6. Backtest protocol

### 6.1 Sample construction

**Unit of analysis:** a **5-year fund vintage** starting on date *t₀*.

- Roll forward *t₀* across the historical panel (e.g. monthly or quarterly starts).
- Each vintage: **exactly 1,260 business days** (or calendar 5y) unless data ends sooner.
- Report distribution of outcomes across vintages, not only one full-history path.

**Reference data:** existing `features_daily.parquet` (2011-09-09 → 2026-03-15).  
Enables ~10 overlapping 5y windows in-sample; COVID contained in several vintages.

### 6.2 Economics

Reuse `cds_cost_model.py` unchanged:

- Carry, MTM, bid–ask, roll, financing on posted collateral
- Collateral = **$5M** (100% allocated to the crunch expression; no multi-slice portfolio)
- `force_delever: false` initially — track NAV; add **NAV floor** rule in v2 if margin calls matter

### 6.3 Strategies to run

**Tier A — pure crunch (primary):**

1. **Standing long protection** — enter when spread &lt; entry_max; hold until maturity or exit rule fires  
2. **Max-notional standing** — largest notional such that 5y calm carry ≤ ~95% of collateral (binary search)  
3. **No-exit ride** — hold through crisis, exit only at fund maturity (max convexity)  
4. **Reactive spike** — baseline contrast (expected to underperform standing)

**Tier B — optional subsidy (secondary):**

5. **Tail + yield mutex** — reuse Y8 or minimal Y1; score with crisis-first composite  
6. **Yield off** — explicit control

### 6.4 Termination rules

| Event | Action |
|-------|--------|
| **Fund maturity (T + 5y)** | Flat all CDX; realize final PnL |
| **NAV ≤ floor** (e.g. 5% of initial) | Stop trading; record `years_to_depletion` |
| **Spread exit trigger** (if configured) | Flat protection; remain in cash until re-entry rule |

---

## 7. Reporting & success criteria

### 7.1 Deliverables

| Artifact | Content |
|----------|---------|
| `data/crunch_fund_vintages.csv` | One row per (vintage, strategy, params) |
| `data/crunch_fund_episodes.csv` | Crisis-window PnL by episode |
| `reports/bundles/crunch_fund/` | Standard `RunBundle` + HTML leaderboard |
| `reports/crunch_fund_study_report.html` | Narrative: “what if you bet on a crunch?” |

### 7.2 Success criteria (research, not investment advice)

**Tier B/C (explosion — primary):** a configuration **passes** if:

1. **`hit_10x = true`** in at least one tier-B or tier-C episode **or** `crisis_nav_peak_multiple ≥ 7.0` with documented path to 10× at higher notional, *and*
2. `in_market_at_onset = true` for that episode, *and*
3. Secondary yield overlay (if any) reduces tier-B/C peak NAV by **≤ 10%** vs pure tail.

**Tier A (COVID — benchmark only):** report `crisis_nav_peak_multiple` and `distance_to_10x`; **do not** treat COVID-scale PnL (~1.5–2×) as mandate success. Expected finding: COVID alone is **insufficient** for LP 10× expectation at realistic leverage.

A configuration **fails** if:

- Full-sample NAV is high but tier-B/C crisis peak multiple &lt; 3× (wrong objective — looks like carry book)
- Calm bleed depletes fund below NAV floor **before** first tier-B event in &gt; 50% of relevant vintages
- Early exit rule caps `capture_ratio` &lt; 50% of theoretical peak in tier-B episodes

**Reporting requirement:** every leaderboard row must show **`distance_to_10x`** and **`notional_for_10x`** so investors see the leverage required to meet the promise.

### 7.3 Figures (required)

1. **Terminal NAV distribution** across 5y vintages (histogram — expect mass near zero)
2. **Crisis peak NAV multiple vs notional** — frontier toward 10× (tier B/C)
3. **`distance_to_10x` heatmap** — entry rule × notional × exit rule
4. **COVID benchmark panel** — same chart with tier-A episodes, showing ~1.5–2× gap vs target
5. **Calm burn rate** vs notional (years until depletion at 60 bps)

---

## 8. Implementation sketch

```
analyses/cdx/
├── SPEC_CRUNCH_FUND.md          # this document
├── config_crunch_fund.yaml      # collateral, sweeps, scoring, episodes
├── run_crunch_fund.py           # vintage loop + sweeps + bundle export
└── src/
    └── crunch_fund.py           # vintage backtester, depletion floor, maturity flat
```

**Reuse without modification:** `cds_cost_model.py`, `signals_tail.py`, `backtest_cds.py`, `bundle_export.py`, `scoring_config.py` (new `CRUNCH_FUND_SCORING`).

**New logic:** 5y vintage iterator, fund-maturity forced exit, NAV floor, crisis-first leaderboard.

---

## 9. One-paragraph mandate (for reports)

> The **CDX.NA.IG Crunch Fund** is a five-year, $5 million mandate that treats investment-grade credit protection as a **binary macro bet**: bleed carry in calm markets, and deliver roughly **10× on capital** if a severe credit crunch occurs. Terminal NAV below initial capital is acceptable when no crunch materializes. Evaluation centres on **crisis peak NAV multiple** and **distance to 10×**, not full-sample Sharpe or carry funding. Historical COVID-scale moves (~1.5–2× at prior leverage) are a **benchmark**, not the success bar.

---

## 10. Open questions (to resolve before coding)

1. **NAV floor for “depleted”** — 0%, 1%, or 5% of initial collateral?  
2. **Exit rule default** — **no exit** (max 10× capture) vs profit-taking — strongly favour no-exit for primary sweep  
3. **10× definition** — peak NAV multiple during episode vs terminal NAV at episode end (recommend **peak**)  
4. **Tier-C synthetic paths** — fixed 50→250 bps shock vs replay of worst 90d move in sample  
5. **Notional cap** — sweep to $1B vs solve `notional_for_10x` analytically then simulate nearest grid point  
6. **Yield in v1** — Tier A only first; yield only if it does not reduce tier-B/C peak by &gt;10%

---

*Spec version 1.1 · 2026-06-24 · CryoQuant `analyses/cdx`*
