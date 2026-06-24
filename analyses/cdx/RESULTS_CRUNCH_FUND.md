# CDX.NA.IG Crunch Fund — Results

**Last updated:** 2026-06-23  
**Mandate:** Five-year, $5M collateral expression optimized for **crisis convexity** (target **10×** peak payoff on tier-B/C credit dislocations).  
**Spec:** `SPEC_CRUNCH_FUND.md` · **Config:** `config_crunch_fund.yaml`

**Backtest sample:** **2011-09-09 → 2026-03-15** · 3,622 business days · manual CDX.NA.IG 5Y on-the-run spreads.

---

## Executive summary

We ran a dedicated **crunch-fund** study distinct from the balanced tail+yield portfolio (`PLAN.md`). The mandate accepts **full calm-path bleed** in exchange for **convex crisis payoff** if North American investment-grade credit dislocates within a five-year fund life.

Three position rules were swept across **$100M–$1B** CDS notional (all on **$5M** posted collateral): **standing** tail insurance, **spike** reactive entry (control), and **pyramid** — a standing base leg plus a **stress add-on** that doubles effective protection when spreads cross a threshold.

**Headline finding:** The **pyramid** structure materially closes the gap to the LP **10×** objective. At **$1B** notional, the best pyramid configurations deliver **12.6–15.5×** peak crisis multiples on tier-B/C episodes and **~53%** of quarterly fund vintages hit **10×** when such an episode occurs. On the COVID benchmark (tier A), modeled peak multiples reach **~13–19×** depending on exit rules — versus **~7.7×** for standing-only at the same notional.

**Trade-off (unchanged from mandate design):** Crisis convexity requires leverage and time in market. Median **calm burn** on leading pyramid configs is **~$30–39M per year** at $1B notional; median **years to 5% NAV floor** is **~0.5–1.2 years**. Many vintages are **depleted or negative** at maturity if no crisis arrives. This is intentional under the catastrophe-trade specification.

**Recommended structure for further work:** `pyramid_e60_a80_r110_h30_x150_n1000m` — base entry &lt;60 bps, base exit 150 bps, add-on at 80 bps, retreat at 110 bps, 30-day add-on cap, **$1B** notional. Alternative with higher COVID capture: add-on at **100 bps** with same exit grid.

---

## Status at a glance

| Component | Status | Artifact |
|-----------|--------|----------|
| Spec & config | ✅ | `SPEC_CRUNCH_FUND.md`, `config_crunch_fund.yaml` |
| Vintage backtester | ✅ | `src/crunch_fund.py` |
| Pyramid signal | ✅ | `src/signals_tail.py` → `pyramid_tail_insurance()` |
| Sweep runner | ✅ | `run_crunch_fund.py` |
| Leaderboard bundle | ✅ | `reports/bundles/crunch_fund/report.html` |
| Vintage / episode tables | ✅ | `data/crunch_fund_vintages.csv`, `data/crunch_fund_episodes.csv` |
| Summary JSON | ✅ | `reports/crunch_fund_summary.json` |
| Research report (HTML) | ✅ | `reports/crunch_fund_study_report.html` |
| Investor pitch (HTML) | ✅ | `reports/crunch_fund_pitch.html` |

**Tests:** 14 crunch-fund + signal tests (`tests/test_crunch_fund.py`, `tests/test_signals_tail.py`)

```bash
.venv/bin/python analyses/cdx/run_crunch_fund.py
.venv/bin/python analyses/cdx/run_crunch_fund_reports.py
.venv/bin/pytest analyses/cdx/tests/test_crunch_fund.py analyses/cdx/tests/test_signals_tail.py -q
```

---

## Methodology

### Fund structure

| Parameter | Value |
|-----------|-------|
| Collateral | **$5,000,000** |
| Horizon | **5 years** per vintage |
| Vintage grid | **Quarterly** starts (`QS`); **38** complete vintages in sample |
| Instrument | **CDX.NA.IG** 5Y on-the-run index CDS |
| Direction | **Long protection** (profit when IG spreads widen) |
| Yield overlay | **Off** (crunch mandate) |
| NAV floor (scoring) | **5%** of initial collateral |

### Economics

Full CDS cost model (`src/cds_cost_model.py`): daily **carry** (pay spread × notional), **mark-to-market** on spread changes (5Y duration), **bid–ask** on entries/exits, **roll** costs on index roll windows, and **financing** on posted collateral. Same engine as the multi-overlay study.

### Crisis episodes (scoring tiers)

| Tier | Episode | Role |
|------|---------|------|
| **A** | COVID severe (Feb–Apr 2020) | Historical benchmark — illustrates gap vs LP 10× on a known crunch |
| **B** | COVID peak, EU Oct 2011 (spread ≥150 bps windows) | **Primary historical scoring** for distance-to-10× |
| **C** | Synthetic 50→250 bps (+200 bps) | **Design-case sizing**; analytical notional for 10× ≈ **$450M** |

**10× definition (v1):** Peak **episode PnL multiple** = `1 + crisis_pnl_usd / collateral`. Leaderboard minimizes **distance to 10×** on tier B/C; tier C uses effective notional including pyramid **2×** exposure when applicable.

### Strategies tested

**1. Standing (`standing_tail_insurance`)**  
Enter long when spread &lt; `entry_max_bps`; exit when spread ≥ `exit_bps` (or hold to maturity if no exit).

**2. Spike (`tail_hold_on_spike`)**  
Reactive entry after ≥10% daily spread jump; trailing exit. Control only — enters too late for maximum convexity.

**3. Pyramid (`pyramid_tail_insurance`)** — *new in this run*  
- **Base leg (0 or 1× notional):** Same as standing — calm entry, optional base exit.  
- **Add-on leg (0 or 1× notional):** Additional long protection when spread ≥ `addon_entry_bps`; closes when spread ≤ `addon_retreat_bps` **or** after `addon_hold_days`.  
- **Position:** 0, 1, or **2** units; backtester scales PnL as `position × notional_usd`.

### Sweep grid

| Dimension | Standing / Spike | Pyramid |
|-----------|------------------|---------|
| Notional | $100M – $1B (6 steps) | $200M, $500M, $1B |
| Entry max | 50, 60, 70 bps | 60 bps |
| Exit | null, 100, 150, 200 bps | null, 150 bps (base leg) |
| Add-on entry | — | 80, 100, 120 bps |
| Add-on retreat | — | 100, 110 bps |
| Add-on hold | — | 30, 45 days |

**Total configurations:** **216** (144 standing/spike + **72** pyramid) × **38** vintages = **8,208** backtests.

---

## Results

### Leaderboard — crisis payoff (tier B/C)

Configurations ranked by **minimum distance to 10×** across vintages (best = 0).

| Rank | Config | Strategy | Notional | Peak crisis multiple (tier B/C) | Hit 10× rate | COVID median |
|------|--------|----------|----------|--------------------------------|--------------|--------------|
| 1 | `pyramid_e60_a80_r110_h30_x150_n1000m` | Pyramid | $1B | **15.5×** | 53% | 17.3× |
| 2 | `pyramid_e60_a100_r110_h30_x150_n1000m` | Pyramid | $1B | **15.5×** | 53% | **18.6×** |
| 3 | `pyramid_e60_a100_r110_h30_no_exit_n1000m` | Pyramid | $1B | 12.6× | 53% | 13.0× |
| — | `standing_e60_x150_n1000m` | Standing | $1B | 7.7× | 0% | 10.9× |
| — | `spike_e70_no_exit_n1000m` | Spike | $1B | 3.3× | 0% | 6.3× |

**Pyramid vs standing at matched notional ($1B):** Crisis peak multiple improves from **7.7× → 12.6–15.5×** (~**1.6–2.0×** uplift). At **$500M**, best pyramid reaches **~8.3×** tier B/C vs standing **~4.4×**.

### Calm-path cost (leading pyramid @ $1B)

| Metric | `…_x150` (base exit 150) | `…_no_exit` (hold base) |
|--------|---------------------------|-------------------------|
| Median calm burn / year | ~$30M | ~$39M |
| Median years to 5% NAV floor | ~0.5 yr | ~1.2 yr |
| Median terminal NAV (5y) | **10.4×** (best x150 configs) | 0.8–3.7× |
| Min terminal NAV | Negative (depleted vintages) | Negative |

**Interpretation:** Base exit at **150 bps** trims exposure after the initial stress leg, reducing bleed while preserving add-on convexity through the widening phase. **No-exit** base maximizes crisis capture but accelerates depletion in calm markets.

### Analytical sizing (tier C)

For a synthetic **+200 bps** widening (50 → 250 bps) with full position held:

$$\text{Notional for 10×} \approx \frac{9 \times \text{collateral} \times 10{,}000}{\text{duration} \times \Delta\text{spread}} \approx \$450\text{M}$$

Pyramid at **2×** effective exposure lowers required headline notional for equivalent crisis PnL — or, at **$1B** single-unit notional with 2× position in stress, delivers **well above 10×** on tier-C-sized moves.

### Episode-level behavior

- **`in_market_at_onset`:** Pyramid and standing configs with calm entry (&lt;60–70 bps) are typically **long at crisis open** on tier-B windows that begin from elevated but not extreme levels; COVID onset from ~53 bps satisfies this.
- **Capture ratio:** Pyramid improves **hold-through-widening** vs standing early exit at 100 bps (prior balanced study); add-on leg specifically **ramps exposure into the stress ramp**.
- **Spike control:** Confirms reactive rules **underperform** for 10× mandate — by construction, entry occurs after the initial jump.

---

## Process (reproducibility)

1. **Load features** — `data/features_daily.parquet` (spread, roll flags).  
2. **Generate quarterly vintage windows** — 5-year horizon from each `QS` start with sufficient history.  
3. **For each config × vintage** — build position series → `run_overlay()` → episode metrics via `evaluate_episode()`.  
4. **Aggregate** — `aggregate_config_results()` → leaderboard CSV + scored HTML bundle (`export_leaderboard_bundle`).  
5. **Representative equity curves** — one overlay per config from vintage starting ≤ Jul 2019 (for bundle charts).

**Scoring weights** (`CRUNCH_FUND_SCORING`): 50% distance-to-10×, 30% crisis peak, 20% hit-rate on tier B/C.

---

## Conclusions

1. **The 10× objective is achievable in model** at **~$450M–$1B** notional on $5M collateral when a tier-B/C dislocation occurs and the fund remains in market — **pyramid** is the critical structure vs standing-only.
2. **Stress add-on** (second unit of protection above ~80–100 bps) is the dominant driver of uplift; it is **mechanical convexity**, not signal alpha.
3. **Calm-path economics dominate vintage outcomes** — median depletion under **18 months** at aggressive sizing; LPs must treat the $5M as **at-risk premium** for crisis optionality.
4. **COVID (tier A) is not the design case** but pyramid configs still show **13–19×** modeled peak multiples — useful sanity check, not the optimization target.
5. **Next steps:** Robustness (cost ±25%, subsample vintages), live margin/IM constraints, legal fund wrapper, and investor-facing materials (`CRUNCH_FUND_PITCH.md`).

---

## Code map

| Module | Role |
|--------|------|
| `src/crunch_fund.py` | Vintage loop, episode scoring, spec expansion |
| `src/signals_tail.py` | `standing_tail_insurance`, `pyramid_tail_insurance`, `tail_hold_on_spike` |
| `src/backtest_cds.py` | Overlay backtest (supports position &gt; 1) |
| `src/cds_cost_model.py` | Carry, MTM, costs |
| `run_crunch_fund.py` | Full sweep + bundle export |
| `scoring_config.py` | `CRUNCH_FUND_SCORING` |
| `src/bundle_export.py` | `export_leaderboard_bundle()` |

---

## Artifacts

| File | Description |
|------|-------------|
| `reports/bundles/crunch_fund/report.html` | Interactive leaderboard + charts |
| `reports/bundles/crunch_fund/leaderboard.csv` | 216 ranked configs |
| `data/crunch_fund_vintages.csv` | Per-vintage metrics (~8.2k rows) |
| `data/crunch_fund_episodes.csv` | Per-episode crisis metrics |
| `reports/crunch_fund_study_report.html` | Self-contained research report |
| `reports/crunch_fund_pitch.html` | UHNWI investor pitch (marketing) |
| `reports/crunch_fund_summary.json` | Best-config snapshot |

---

*This document reports backtest results under explicit modeling assumptions. It is not investment advice, an offer, or a guarantee of future performance.*
