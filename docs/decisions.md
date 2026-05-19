# Decision Log

ADR-style: one entry per material decision. Append-only; if a decision is reversed, write a new
entry referencing the old one rather than editing the original.

Format: `[YYYY-MM-DD] ID — title` then context, decision, consequences.

---

## [2026-05-18] D1 — New sibling workspace `/Users/ulrikdeichsel/CryoQuant`
**Context:** IndicatorBench has accumulated pineforge (indicator lab) + research/long_tradable_options
(quant research). It's a Pine-script-flavoured workspace; the quant work has outgrown it.
**Decision:** Spin up CryoQuant as a fresh sibling repo with its own Python 3.12 venv and git history.
**Consequences:** Clean import boundary. CryoBacktester/CryoTrader can `pip install -e ../CryoQuant`.
Existing IndicatorBench code is referenced via `reference/` copies, not symlinks.

## [2026-05-18] D2 — `cryocore` shared package lives inside CryoQuant
**Context:** CryoBacktester and CryoTrader already duplicate `indicators/` and `market_hours.py`.
A shared package would avoid double work.
**Decision:** Create `cryocore/` as a subpackage of CryoQuant. Promote to its own repo (or installable
subpackage) only when its API has stabilised (Phase 6).
**Consequences:** Single source of truth without premature multi-repo overhead.

## [2026-05-18] D3 — Do not touch CryoBacktester until CryoQuant ships a working signal
**Context:** Tempting to pre-port CryoBacktester's `indicators/` into `cryocore`. Risk of churn.
**Decision:** Leave CryoBacktester untouched until CryoQuant has produced at least one usable signal
end-to-end (Phase 4 milestone). Do not pre-port its indicators.
**Consequences:** Some duplicated code remains in the short term; we get faster iteration on CryoQuant.

## [2026-05-18] D4 — Reference material is copied, not symlinked
**Context:** Need pineforge + long_tradable_options accessible from inside CryoQuant.
**Decision:** Copy. Disk cost is trivial; copies are robust to workspace moves.
**Consequences:** `reference/` may drift from the originals. That's fine — it's a frozen reference.

## [2026-05-18] D5 — Python 3.12
**Context:** CryoBacktester is on 3.12. Picking a different version creates friction for `cryocore`.
**Decision:** 3.12 across the board.
**Consequences:** Drop-in compatibility with sibling repos.

## [2026-05-18] D6 — Asset-agnostic from day one
**Context:** User wants to extend beyond crypto (equities, FX, macro) eventually.
**Decision:** `Symbol = (venue, ticker)`, `Instrument` record, pluggable calendars. Designed in now.
**Consequences:** Slight extra boilerplate; large saving on later retrofits.

## [2026-05-18] D7 — Local-only stack
**Context:** Solo developer, M-series Mac.
**Decision:** Parquet on disk + DuckDB query layer + Python scripts. No cloud, no Airflow.
**Consequences:** Compute envelope constrains hyperparam search; LightGBM+Optuna handle this fine.

## [2026-05-18] D8 — BTCUSD end-to-end first
**Context:** Avoid generalising prematurely.
**Decision:** Phase 1–4 target BTC. ETH and non-crypto come in Phase 5+.
**Consequences:** Faster proof of concept.

## [2026-05-18] D9 — Options data: read directly from CryoBacktester parquets
**Context:** Historic option data is hard to source. CryoBacktester already has a working pipeline.
**Decision:** Configure a path to `/Users/ulrikdeichsel/CryoBacktester/backtester/data/` and read
from there. Zero re-ingestion.
**Consequences:** CryoQuant depends on CryoBacktester's data layout. Stable interface; documented in
`reference/cryobacktester_notes.md`.

## [2026-05-18] D10 — Macro/on-chain: design abstraction, stub one source
**Context:** User wants the capability but has no concrete signal needing it yet.
**Decision:** Build the source-plugin pattern + stub a FRED-DXY source. Add real sources only when a
candidate signal motivates them.
**Consequences:** YAGNI applied. Abstraction is exercised by the stub; real work happens on demand.

## [2026-05-18] D11 — Two-tier feature model
**Context:** Original plan over-specified the feature store. Trivial features (`day_of_week`,
`is_us_session`) shouldn't need versioning + caching.
**Decision:**
- **Tier 1:** primitives + calendar features — pure functions, recomputed on call, no store.
- **Tier 2:** named/versioned feature sets, opt-in caching via `@cached` decorator.
**Consequences:** Lower ceremony for cheap features; the store applies only where it matters.

## [2026-05-18] D12 — Three signal classes: BoolSignal, StateSignal, ProbSignal
**Context:** Original plan only specified `ProbSignal`, but `BTC_IS_UP_TODAY` is a perfectly valid
actionable boolean. `StateSignal` is the existing pineforge contract CryoTrader consumes.
**Decision:** All three implement a common `Signal` protocol. "Indicator" is a presentation concept,
not a class. Every signal is also implicitly a feature column.
**Consequences:** Pine-portable signals stay Pine-portable; ML signals coexist; no duplication.

## [2026-05-18] D13 — Planning documents under `docs/`
**Context:** Single source of truth for the project shape.
**Decision:** `docs/quant_plan.md` is canonical. `docs/decisions.md` (this file) is the ADR log.
**Consequences:** All future planning docs land here.

## [2026-05-19] D14 — cryocore stays inside CryoQuant (Phase 6 decision)
**Context:** Phase 6 originally proposed promoting `cryocore` to its own repo now that Phases 1–5
are complete and the API has stabilised. Options were: (a) own git repo, (b) installable
subpackage within CryoQuant, (c) stay as-is.
**Decision:** cryocore stays as a subpackage inside CryoQuant. No promotion yet.
**Rationale:** The API is stable but CryoTrader and CryoBacktester have not yet been updated to
consume it. Promoting early adds multi-repo overhead with no immediate payoff. Revisit when
a concrete integration is attempted.
**Consequences:** Zero overhead today. CryoTrader/CryoBacktester still import directly from their
own copies. Promotion remains on the backlog.

