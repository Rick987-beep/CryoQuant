# CDX.NA.IG Multi-Overlay — Results

> **Reporting reference:** This study implements the full artifact layout described in
> [`docs/how_to_report.md`](../../docs/how_to_report.md) — bundles, phase JSON, manifest,
> index HTML, narrative and pitch reports.

**Last updated:** 2026-06-24  
**Data policy:** Manual `cdx_na_ig_clean.csv` (no live API).

**Backtest sample (all full-sample runs):** **2011-09-09 → 2026-03-15** · 3,622 business days · aligned panel (CDX.NA.IG + QQQ + TLT + VIX).

**Walk-forward OOS** (`tail_y8_mutex`): stitched OOS test windows only — first test block starts **2019-09-10** (after 8y train origin); see `reports/manifest.json` → `backtest_windows.walk_forward_oos`.

## Status at a glance

| Phase | Status | Artifact |
|-------|--------|----------|
| 1 — Data | ✅ | `data/features_daily.parquet`, `data/panel_daily.parquet` |
| 2 — Cost model | ✅ | `src/cds_cost_model.py`, `reports/phase2_cost_model.json` |
| 3 — Overlay sweeps | ✅ | `data/phase3_overlay_results.csv`, `reports/phase3_overlay_sweeps.json` |
| 4 — Portfolio | ✅ | `data/phase4_portfolio_results.csv`, `reports/phase4_portfolio.json` |
| 5 — Report | ✅ | `reports/manifest.json`, `reports/report.html`, `bundles/primary/` |

**Tests:** 63/63 (`pytest studies/cdx/tests/ -q`)

```bash
.venv/bin/python studies/cdx/run_phase1_data.py
.venv/bin/python studies/cdx/run_phase2_cost_model.py
.venv/bin/python studies/cdx/run_phase3_overlay_sweeps.py
.venv/bin/python studies/cdx/run_phase4_portfolio.py
.venv/bin/python studies/cdx/run_phase5_report.py
.venv/bin/pytest studies/cdx/tests/ -q
```

## Code map

| Module | Role |
|--------|------|
| `src/ingest.py` | CDX.NA.IG → macro_store + parquet |
| `src/features.py` | Regimes, 1d velocity σ, roll flags |
| `src/cds_cost_model.py` | Carry, MTM, bid-ask, roll, financing |
| `src/yield_gates.py` | Calm gates, tail mutex, causal helpers |
| `src/signals_tail.py` | Overlay 1 — standing insurance, tail_hold |
| `src/signals_yield.py` | Overlay 2 — Y1–Y14 + `YIELD_STRATEGY_REGISTRY` |
| `src/backtest_cds.py` | Per-overlay backtest → `CdsOverlayResult` |
| `src/portfolio_backtest.py` | Tail + yield composition, mutex, walk-forward OOS |
| `src/metrics_portfolio.py` | Funding ratio, episode PnL, regime correlation |
| `run_phase3_overlay_sweeps.py` | Tail grid + full yield leaderboard |
| `run_phase4_portfolio.py` | Portfolio variants + walk-forward |
| `run_phase5_report.py` | Manifest, index HTML, primary portfolio bundle |
| `src/cds_to_spot.py` | CDX → SpotResult adapter for framework bundles |
| `src/bundle_export.py` | RunBundle export for phase 3/4 sweeps |
| `src/primary_bundle.py` | Primary portfolio deep-dive artifacts |
| `src/report_manifest.py` | `manifest.json` + index page builder |
| `scoring_config.py` | CDX leaderboard scoring weights |

**Not built yet:** `signals_proxy.py`

---

## Phase 1 — Data

- **CDX.NA.IG:** 3,622 rows, 2011-09-09 → 2026-03-15
- **Spread range:** 43.75 – 151.80 bps
- **macro_store:** `manual/CDX_NA_IG_5Y`
- **Aligned panel:** spread + QQQ + TLT + VIX (daily)
- **Features:** `regime_level`, `regime_velocity` (1d σ), roll flags, carry_per_1m
- **QA:** 0 duplicate dates, 1 gap > 4 days

Artifacts: `data/panel_daily.parquet`, `data/features_daily.parquet`, `reports/phase1_data.json`

---

## Phase 2 — CDS cost model

**COVID replay** (long protection, $100M notional, $5M collateral):
- Entry 2020-02-24 @ 53.1 bps → Exit 2020-03-23 @ 121.6 bps
- Total PnL: **+$3.35M** (+67% on collateral)
- Carry: -$57k | MTM: +$3.75M | Financing: -$19k

**Annual carry at $100M notional (% of $5M collateral):**

| Spread | Annual carry | % collateral |
|--------|-------------|--------------|
| 50 bps | $500k | 10% |
| 60 bps | $600k | 12% |
| 70 bps | $700k | 14% |
| 80 bps | $800k | 16% |

Unit tests: 4/4 (`test_cds_cost_model.py`)

Artifacts: `reports/phase2_cost_model.json`

---

## Phase 3 — Per-overlay sweeps

**Economics:** $5M total collateral; tail slice $2.5M ($100M notional), yield slice $1.75M ($50M notional). Full CDS cost model on all runs.

**Sample:** 2011-09-09 → 2026-03-15. Yield overlays run **in isolation** (tail mutex only for Y14 handoff).

### Tail overlay

| Config | NAV end | COVID PnL |
|--------|---------|-----------|
| Standing entry&lt;60, exit≥100 | **1.92** | +$2.97M |
| Standing entry&lt;60, exit≥120 | 1.58 | +$4.36M |
| tail_hold spike (reactive) | 0.62 | +$2.63M |

### Yield overlay — full leaderboard

| ID | Strategy | NAV end | vs Y1 | Carry funding | COVID PnL |
|----|----------|---------|-------|---------------|-----------|
| **Y8** | Velocity-filtered underwriter | **5.43** | 2.43× | **2.50** | +$80k |
| Y10 | Risk-on underwriter | 5.04 | 2.26× | 2.27 | -$9k |
| Y6 | Peak-confirmed fade | 4.30 | 1.93× | 1.87 | +$67k |
| Y13 | Roll-season carry | 3.15 | 1.41× | 1.26 | -$578k |
| Y2 | Band trader | 2.63 | 1.18× | 0.96 | -$205k |
| Y3 | Compression rider | 2.29 | 1.03× | 0.78 | +$29k |
| **Y1** | Calm underwriter (benchmark) | **2.23** | 1.00× | **0.76** | -$578k |
| Y11 | Equity–credit divergence | 1.62 | 0.72× | 0.40 | +$107k |
| Y9 | Partial notional | 1.56 | 0.70× | 0.39 | -$548k |
| v1 | zscore fade (IndicatorBench) | 0.77 | 0.34× | -0.05 | -$293k |
| Y14 | Handoff to tail | 0.50 | 0.22× | -0.21 | -$15k |
| Y7 | Fade the rip | -0.43 | — | — | -$49k |
| Y12 | Rates-aware | -1.17 | — | — | -$285k |

*Carry funding ratio = yield calm PnL / |tail calm carry| (reference tail: standing e60/x100).*

### Takeaways

1. **Carry-first beats fades** — Y1/Y8/Y10 dramatically outperform IndicatorBench `zscore_fade` once CDS economics apply.
2. **Y8 is Phase 4 front-runner** — velocity grind filter improves COVID PnL (+$80k vs Y1 −$578k) while lifting funding ratio to 2.50.
3. **Y1 hits 76% funding** — close to the 0.7 portfolio target in isolation.
4. **Tail still bleeds in calm** — standing tail NAV 1.92× but calm PnL negative on tail slice; portfolio must net tail + yield.
5. **Y12/Y7 fail** — cross-asset and rip-fade variants not viable standalone.

### Engineering notes

- **`regime_velocity` bug fixed:** was classifying 100% of bars as `high` (3d σ vs decimal buckets). Now uses 1d expanding σ; calm = low ∪ moderate.
- **Causal tests:** every registered yield strategy verified for no lookahead bias.
- **Gate conservatism:** NaN spread or missing velocity → flat.

Artifacts: `data/phase3_overlay_results.csv`, `reports/phase3_overlay_sweeps.json`

---

## Phase 4 — Portfolio composition

**Setup:** Tail standing `e60/x100` + yield strategy on $5M total collateral (tail slice $2.5M, yield slice $1.75M). Full CDS economics.

### Full-sample variants

| Variant | Yield | Mutex | NAV end | Carry funding | COVID PnL | Overlap days |
|---------|-------|-------|---------|---------------|-----------|--------------|
| **tail_y8_mutex** | Y8 | yes | **1.94** | 0.83 | **+$2.96M** | **0** |
| tail_y10_mutex | Y10 | yes | 1.91 | 0.78 | +$2.96M | 0 |
| tail_y1_mutex | Y1 | yes | 1.85 | 0.69 | +$2.96M | 0 |
| tail_y8_no_mutex | Y8 | no | 3.01 | 2.50 | +$3.05M | 1296 ⚠️ |

### Walk-forward OOS (`tail_y8_mutex`)

- 3 test blocks (8y train origin → 3y test windows)
- Stitched OOS NAV end: **1.65×**

### Takeaways

1. **Mutex is mandatory** — without it, tail long + yield short run simultaneously 1,296 days; NAV is misleadingly high.
2. **With mutex, portfolio NAV 1.94×** — tail COVID gain (+$2.96M) dominates; yield contributes in calm windows when tail is flat.
3. **Y8 + mutex** is the recommended Phase 4 config — best mutex NAV and same crisis payoff as tail-only.
4. **Carry funding 0.83** in portfolio (vs 2.50 for Y8 alone) — mutex caps yield time-in-market to ~11% vs 46% isolated.

Artifacts: `data/phase4_portfolio_results.csv`, `reports/phase4_portfolio.json`, `reports/bundles/phase4_portfolio/`

Unit tests: 9 portfolio tests (attribution sum, mutex zero overlap, causal positions, walk-forward blocks).

---

## Phase 5 — Reports

**Entry point:** `run_phase5_report.py` (or open `reports/report.html` after phase 3+4 have run)

| Artifact | Contents |
|----------|----------|
| `reports/manifest.json` | Machine-readable index: highlights, bundle paths, walk-forward |
| `reports/report.html` | Index page linking all study reports |
| `reports/bundles/phase3_overlay_sweep/` | Scored yield+tail sweep (from phase 3) |
| `reports/bundles/phase4_portfolio/` | Portfolio variant comparison (from phase 4) |
| `reports/bundles/primary/` | `tail_y8_mutex` deep dive: equity, attribution, trades |

Primary bundle extras (not in standard `RunBundle` schema):
- `attribution_daily.parquet` — `pnl_tail`, `pnl_yield`, costs, `total`
- `equity_daily.parquet` — `equity`, `nav_usd`

```bash
.venv/bin/python studies/cdx/run_phase5_report.py
# optional: --refresh-bundles  # re-run phase 3+4 first
.venv/bin/python studies/cdx/run_study_report_html.py   # narrative report only
```

**Narrative report (self-contained):** `reports/cdx_na_ig_study_report.html` — formal write-up for external readers.

---

## Next

- CDS-specific HTML template (attribution charts, calm vs stress panels)
- `signals_proxy.py` + Overlay 3
- Robustness checklist (cost sensitivity, subsample drops, block bootstrap)
