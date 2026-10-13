# france_sovereign_stress

CryoQuant **project** study (path B): will the OAT–Bund 10-year spread reach ≥240 bp before
1 July 2027, and how does a FOAT/FGBL spread sleeve (plus optional CAC short) pay if it does?

v6 rebuild of the misc v5 job. Research only — no orders.

| Doc | Role |
|-----|------|
| [`HANDOVER.md`](HANDOVER.md) | **Start here** — how v5 works, reference numbers, CryoQuant mapping |
| [`KICKOFF.md`](KICKOFF.md) | Purpose, locked decisions |
| [`PLAN.md`](PLAN.md) | Phases / exit criteria / status |
| [`RESULTS.md`](RESULTS.md) | Phase 5 (v6) results for the active snapshot, sensitivities |
| [`RESULTS_V7.md`](RESULTS_V7.md) | **v7** low-ops / convex compare (options, fixed futures, naked FOAT, banks) |
| [`TRADES_V7_GUIDE.md`](TRADES_V7_GUIDE.md) | Plain-language guide to three v7 trades for hobby traders |
| [`TRADES_V7_GUIDE.html`](TRADES_V7_GUIDE.html) | Same guide, self-contained Aureas HTML (`run_trades_guide_html.py`) |
| [`HANDOVER_V7.md`](HANDOVER_V7.md) | v7 brief (no pyramid; reuse v6 worlds) |
| [`EXPLORE.md`](EXPLORE.md) | Scenario explorer notes (fine exit grid, costs, fees) |
| [`explore.html`](explore.html) | Branded static explorer (mean + quantiles vs exit level) |
| [`explore_interactive.html`](explore_interactive.html) | Self-contained interactive book (Chart.js + embedded MC data) |
| [`config.yaml`](config.yaml) | Horizon, levels, simulation, instruments, costs, rules |
| [`universe.yaml`](universe.yaml) | Study symbols |

**Status: concluded (13 Oct 2026).** v6 phases 0–5 complete (phase 6 pitch HTML deferred; use the
explore report). v7 low-ops compare complete; three trades written up in `TRADES_V7_GUIDE` and sent
out. No positions taken from this study.

| Output | Snapshot |
|--------|----------|
| v6: `RESULTS.md`, `EXPLORE.md`, `explore.html`, `explore_interactive.html` | `2026-10-12T0941` (entry 137.34 bp) |
| v7: `RESULTS_V7.md`, `TRADES_V7_GUIDE.*` | `2026-10-13T1010` (entry 140.72 bp; active in `config.yaml`) |

Rerunning v6 phases now uses the 13 Oct snapshot; set `FSS_SNAPSHOT=2026-10-12T0941` to reproduce
the v6 numbers above.

## Layout

```text
studies/france_sovereign_stress/
  run_refresh.py                 # snapshot + activate + archive + full rerun, one command
  run_snapshot.py                # take a live snapshot (quote now, history to last close)
  run_phase1_data.py … run_phase5_evaluate.py
  run_explore_report.py          # explorer data + EXPLORE.md + explore.html
  run_explore_interactive.py     # explore_interactive.html
  run_v7_evaluate.py             # v7 low-ops / options / bank scorecard → RESULTS_V7.md
  run_trades_guide_html.py       # TRADES_V7_GUIDE.md → self-contained Aureas HTML
  src/                           # study-local only
    data/  calibrate.py  instruments.py  scenarios.py  rules.py  evaluate.py
    options.py  vol_fit.py  v7_sleeves.py  bank_rank.py  paths.py
  tests/
  input/v5_reference/            # frozen v5 data, scripts, HTML (read-only)
  input/snapshots/<stamp>/       # live snapshots: data/ (v5 layout) + manifest.json
  archive/<stamp>/               # outputs of earlier runs (RESULTS, explorers, phase JSON)
  input/research/
  data/                          # phase JSON (gitignored)
  reports/                       # local regenerations (gitignored)
  EXPLORE.md | explore.html      # tracked explorer artifacts
```

Framework promotions used by this study: `cryoquant.data.sources.cnbc_yields`,
`cryoquant.data.sources.eurex_futures`, FRED LT yield aliases, Yahoo FR tickers in
`cryocore/instruments.py`. Pricing, Monte Carlo, and rules stay study-local.

## Run

```bash
cd /Users/ulrikdeichsel/CryoQuant && source .venv/bin/activate

# Refresh: new snapshot (live entry quote, history to the last full session),
# activate it, archive the previous run, rerun phases 1–5 + both explorers.
python studies/france_sovereign_stress/run_refresh.py
python studies/france_sovereign_stress/run_refresh.py --reuse <stamp>   # rerun, no fetch

# Or step by step: snapshot only (--activate sets snapshot.stamp), then the phases
python studies/france_sovereign_stress/run_snapshot.py --activate

python studies/france_sovereign_stress/run_phase1_data.py
python studies/france_sovereign_stress/run_phase2_pricing.py
python studies/france_sovereign_stress/run_phase3_paths.py --n 500   # smoke
python studies/france_sovereign_stress/run_phase4_rules.py
python studies/france_sovereign_stress/run_phase5_evaluate.py        # full 10k

# Fine exit grid (200–400 bp / 10 bp) + presets; rebuilt when the stamp changes
python studies/france_sovereign_stress/run_explore_report.py
# Interactive self-contained HTML; prose numbers come from the phase outputs
python studies/france_sovereign_stress/run_explore_interactive.py

pytest studies/france_sovereign_stress tests/test_sources_cnbc_eurex.py -q
```

**Snapshots.** The active stamp is `FSS_SNAPSHOT` (a stamp or `reference`), else
`snapshot.stamp` in `config.yaml`, else the v5 reference `2026-10-09T1456`. Only the
reference run enforces the v5 acceptance gates; a live snapshot reports drift and keeps
the live P&L check (11 Sep–8 Oct, +€11,490) as a hard gate. The €/bp regression uses the
last `calibration.settle_window_days` (20) settles; vol and CAC beta use 126 business
days ending at the last full session; the calmer-vol window stays anchored before
September. `run_refresh.py` copies the current outputs to `archive/<old stamp>/`
before it reruns. Tests always run against the reference (`tests/conftest.py`).

Open [`explore_interactive.html`](explore_interactive.html) in a browser (Chart.js from CDN; all simulation data is embedded).

## Locked assumptions (Phase 0)

| Topic | Choice |
|-------|--------|
| Scope | Spread FOAT/FGBL + CAC short; **options parked** |
| Execution | `daily_close` baseline (IBKR cannot rest a stop on the synthetic) |
| Costs | €2.00 / contract / side (Lynx live) + half-tick (€5) bid–ask; 1 bp stop slip |
| Margin | `config.yaml` → `margin.initial_eur` (IBKR Europe overnight IM); additive FOAT+FGBL ladder for €10k/€15k/€20k |
| Vol | Primary = trailing 126d (stress window); calmer pre-Sep as sensitivity |
| RNG | Common random numbers across exit levels (differs from v5 `seed+i`) |
| Optimise | 300 bp exit |

Primary Phase 5 headline @300 bp (n=10k): **mean ≈11.58×** vs v5 **11.67×**.
