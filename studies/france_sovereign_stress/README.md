# france_sovereign_stress

CryoQuant **project** study (path B): will the OAT–Bund 10-year spread reach ≥240 bp before
1 July 2027, and how does a FOAT/FGBL spread sleeve (plus optional CAC short) pay if it does?

v6 rebuild of the misc v5 job. Research only — no orders.

| Doc | Role |
|-----|------|
| [`HANDOVER.md`](HANDOVER.md) | **Start here** — how v5 works, reference numbers, CryoQuant mapping |
| [`KICKOFF.md`](KICKOFF.md) | Purpose, locked decisions |
| [`PLAN.md`](PLAN.md) | Phases / exit criteria / status |
| [`RESULTS.md`](RESULTS.md) | Phase 5 v5 reconciliation + sensitivities |
| [`EXPLORE.md`](EXPLORE.md) | Scenario explorer notes (fine exit grid, costs, fees) |
| [`explore.html`](explore.html) | Branded static explorer (mean + quantiles vs exit level) |
| [`config.yaml`](config.yaml) | Horizon, levels, simulation, instruments, costs, rules |
| [`universe.yaml`](universe.yaml) | Study symbols |

**Status:** Phases 0–5 complete. Phase 6 pitch HTML deferred; use the explore report instead.

## Layout

```text
studies/france_sovereign_stress/
  run_phase1_data.py … run_phase5_evaluate.py
  run_explore_report.py          # rebuild EXPLORE.md + explore.html
  src/                           # study-local only
    data/  calibrate.py  instruments.py  scenarios.py  rules.py  evaluate.py  paths.py
  tests/
  input/v5_reference/            # frozen v5 data, scripts, HTML (read-only)
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

python studies/france_sovereign_stress/run_phase1_data.py
python studies/france_sovereign_stress/run_phase2_pricing.py
python studies/france_sovereign_stress/run_phase3_paths.py --n 500   # smoke
python studies/france_sovereign_stress/run_phase4_rules.py
python studies/france_sovereign_stress/run_phase5_evaluate.py        # full 10k

# Fine exit grid (200–400 bp / 10 bp) + branded explorer
python studies/france_sovereign_stress/run_explore_report.py

pytest studies/france_sovereign_stress tests/test_sources_cnbc_eurex.py -q
```

## Locked assumptions (Phase 0)

| Topic | Choice |
|-------|--------|
| Scope | Spread FOAT/FGBL + CAC short; **options parked** |
| Execution | `daily_close` baseline (IBKR cannot rest a stop on the synthetic) |
| Costs | €2.35 / contract / side + half-tick (€5) bid–ask; 1 bp stop slip |
| Vol | Primary = trailing 126d (stress window); calmer pre-Sep as sensitivity |
| RNG | Common random numbers across exit levels (differs from v5 `seed+i`) |
| Optimise | 300 bp exit |

Primary Phase 5 headline @300 bp (n=10k): **mean ≈11.58×** vs v5 **11.67×**.
