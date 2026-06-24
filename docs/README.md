# CryoQuant documentation

Guides for **using** the library. Planning specs and ADRs live in [`archive/`](archive/) — you do not need them to run a study.

---

## Start here

| | |
|---|---|
| **New to CryoQuant?** | [how_to_use.md](how_to_use.md) — setup, paths A/B/C, and reference for each pipeline layer |
| **Starting a new study?** | [how_to_build_a_study.md](how_to_build_a_study.md) — from a data track (new or existing) to a backtested signal |
| **Publishing study outputs?** | [how_to_report.md](how_to_report.md) — artifact layout and report format menu |
| **Lookup a term** | [glossary.md](glossary.md) |

---

## Runnable examples

Scripts in [`../scripts/`](../scripts/) mirror the docs:

| Script | Path | Shows |
|---|---|---|
| `ema_cross_backtest.py` | Hello World | EMA cross, `BoolSignal`, HTML report |
| `quick_indicator.py` | A | `load_track`, `align_series`, rule signal |
| `ml_multi_source.py` | C | `DataPanel`, `walk_forward_fit`, `ProbSignal` |
| `ema_cross_options_backtest.py` | Options | Deribit leg evaluation |

---

## How the docs split

```text
how_to_use.md           Reference walkthrough (what each module does)
how_to_build_a_study.md Cookbook (what to do for a new idea end-to-end)
how_to_report.md        Artifact layout and report format menu
glossary.md               Definitions
archive/                  Internal build history (phases, ADRs, module inventory)
```

**Strict at seams, loose in the middle** — always use `Symbol` + `load_track` for data and `Signal` + `simulate` for backtest output; everything between is your study code in `analyses/` or optional framework helpers.

---

## Archive

[archive/README.md](archive/README.md) — `quant_plan`, `quant_spec`, `FRAMEWORK_STATUS`, `workflow_plan`, `decisions`. Kept for contributors; not required reading.
