> **Archived (Jun 2026).** Internal workflow glue design — implemented; kept for history.
> Start with [how_to_use.md](../how_to_use.md).

# CryoQuant — Workflow & Glue Layer Plan

**Date:** 24 Jun 2026  
**Updated:** 24 Jun 2026 — backward-compat policy; CLI stubs retained (D22)  
**Status:** Implemented (24 Jun 2026)  
**Context:** Balance generic framework vs per-analysis freedom; support both quick
indicators (2–3 series) and complex ML studies (20+ heterogeneous tracks).

**Principles (unchanged):**
- **Strict at seams:** `Symbol`, `OHLCVBars`, `Signal`, no lookahead, `TRADE_COLUMNS`.
- **Loose in the middle:** pandas joins, optional `FeatureBuilder`, analysis-local glue.
- **Promote on reuse:** move to `cryoquant/` when two analyses need the same pattern.
- **Backward compatibility:** additive modules only; no signature changes on existing public APIs;
  CLI stub subcommands (`backtest`, `signals publish`) retained until explicitly deprecated (D22).

---

## 1. Problem statement

| Gap | Who feels it | Today |
|---|---|---|
| Macro/bars alignment | Simple + complex paths | Copy-paste `reindex` / private `_align_to_index` in `trend_builders.py` |
| OHLCV vs macro routing | Complex path | Caller knows `loader.load` vs `macro_store.load_series` vs ingest |
| Multi-track container | Complex path | Ad-hoc `dict[DatasetRef, DataFrame]` with no helpers |
| ML walk-forward boilerplate | Complex path | Manual loop in `how_to_use.md` §7 |
| Path clarity | All users | Docs read as “everything is FeatureBuilder + registry” |

**Non-goals:** pipeline runner, experiment registry, feature catalog YAML, MLflow, mandatory analysis layout.

---

## 2. Code to add

### 2.1 `cryoquant/features/align.py` *(priority: high)*

Extract and generalise alignment logic currently private in `trend_builders.py`.

**Public API:**

```python
def align_series(
    target_index: pd.DatetimeIndex,
    series: pd.Series,
    *,
    method: Literal["asof", "ffill"] = "asof",
    ffill_limit: int | None = 35,   # calendar days; None = no cap
    name: str | None = None,
) -> pd.Series:
    """Align a scalar series onto target_index (closed-bar safe for daily macro)."""

def align_frame_column(
    target_index: pd.DatetimeIndex,
    frame: pd.DataFrame,
    column: str = "close",
    **kwargs,
) -> pd.Series:
    """align_series wrapper for a single OHLCV column."""

def align_many(
    target_index: pd.DatetimeIndex,
    series_map: dict[str, pd.Series],
    *,
    prefix: str = "",
    **kwargs,
) -> pd.DataFrame:
    """Align multiple series; columns = prefix + key."""

def join_features(
    primary: pd.DataFrame,
    *others: pd.DataFrame,
    how: Literal["inner", "outer"] = "inner",
) -> pd.DataFrame:
    """Index-join feature frames on DatetimeIndex; duplicate col names raise."""
```

**Notes:**
- `method="asof"` uses `merge_asof` backward (same semantics as `_align_to_index`).
- `method="ffill"` uses `reindex(..., method="ffill")` for same-frequency data.
- `htf_align` stays in `primitives.py`; `align.py` may re-export or cross-link in docs.
- **Refactor:** `trend_builders._align_to_index` → call `align.align_series`; delete private copy.

**Tests:** `tests/test_features_align.py` — asof vs ffill, ffill_limit staleness, empty series, tz-naive input normalised to UTC.

---

### 2.2 `cryoquant/data/resolve.py` *(priority: high)*

Single entry point for “give me data for this Symbol” regardless of OHLCV vs macro.

**Public API:**

```python
@dataclass(frozen=True)
class SeriesRef:
    source: str      # catalog source, e.g. "fred", "yahoo", "manual"
    series_id: str   # ticker or macro id

def is_ohlcv_symbol(symbol: Symbol) -> bool:
    """True if symbol routes to loader.load (not macro_store)."""

def load_track(
    symbol: Symbol,
    tf: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame | pd.Series:
    """Load one track. OHLCV → DataFrame; macro/scalar → Series (close or value)."""

def load_tracks(
    specs: list[tuple[Symbol, str]],   # (symbol, tf) pairs
    start: datetime,
    end: datetime,
) -> dict[str, pd.DataFrame | pd.Series]:
    """Batch load; keys = str(symbol) or str(symbol)+'@'+tf."""
```

**Routing rules (encode in `is_ohlcv_symbol`):**
- `asset_class in ("macro",)` or `venue == "fred"` with no OHLCV in catalog → `macro_store` or FRED source.
- `instrument.meta.get("storage") == "macro"` if we add that key later.
- Default: `loader.load`.

**Initial implementation:** inspect `get_instrument(symbol).asset_class` and existing ingest conventions (`manual/` for analysis CSVs like CDX). Document edge cases; don't over-automate exotic formats.

**Tests:** `tests/test_data_resolve.py` — mock/synthetic instruments; OHLCV path uses existing loader fixtures; macro path uses `tmp_path` macro_store.

---

### 2.3 `cryoquant/features/panel.py` *(priority: medium)*

Lightweight container for multi-track studies — not a database, not a feature store.

**Public API:**

```python
@dataclass
class DataPanel:
    """Aligned multi-track bag for FeatureBuilder inputs."""
    primary_ref: DatasetRef
    primary: pd.DataFrame
    tracks: dict[str, pd.DataFrame | pd.Series]   # named extras
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_loads(
        cls,
        primary: tuple[Symbol, str],
        extras: list[tuple[str, Symbol, str]],  # (name, symbol, tf)
        start: datetime,
        end: datetime,
    ) -> DataPanel: ...

    def to_frames(self) -> dict[DatasetRef, pd.DataFrame]:
        """Convert to FeatureBuilder frames dict (Series → single-col DataFrame)."""

    def align_track(
        self,
        name: str,
        *,
        ffill_limit: int | None = 35,
    ) -> pd.Series:
        """Align named track onto primary.index via align.align_series."""

    def with_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Join feature columns onto primary bars (inner join on index)."""
```

**Scope limit:** No lazy loading, no versioning, no catalog — just ergonomics for 20-track ML setups.

**Tests:** `tests/test_features_panel.py` — from_loads with mocked `load_track`, align_track, to_frames round-trip.

---

### 2.4 `cryoquant/models/fit_loop.py` *(priority: medium)*

Thin wrapper for walk-forward ML — mirrors backtest `sweep_collector` philosophy for models.

**Public API:**

```python
@dataclass
class FoldResult:
    fold_id: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    metrics: dict[str, float]
    y_prob: pd.Series | None = None

def walk_forward_fit(
    model_factory: Callable[[], TabularModel],
    X: pd.DataFrame,
    y: pd.Series,
    *,
    train_window_bars: int,
    test_window_bars: int,
    step_bars: int,
    embargo_bars: int = 0,
    metrics_fn: Callable = compute_metrics,
) -> list[FoldResult]:
    """Walk-forward train/predict; returns per-fold metrics + optional OOS probs."""

def concat_oos_probs(results: list[FoldResult]) -> pd.Series:
    """Stitch out-of-sample probabilities across folds."""
```

**Non-goals:** Optuna integration, automatic feature selection, model registry writes (caller does that).

**Tests:** `tests/test_models_fit_loop.py` — synthetic X/y, 3 folds, no leakage at fold boundaries.

---

### 2.5 Example scripts *(priority: medium — documentation by example)*

| Script | Demonstrates |
|---|---|
| `scripts/quick_indicator.py` | Path A: 2 primitives + 1 macro via `load_track` + `align_series` + `BoolSignal` + `simulate` |
| `scripts/ml_multi_source.py` | Path C: `DataPanel.from_loads` + compose builders + `walk_forward_fit` + `prob_from_model` |

Keep scripts &lt;150 lines each; runnable with cached data where possible.

---

### 2.6 Refactors *(priority: high, bundled with 2.1)*

| File | Change |
|---|---|
| `cryoquant/features/trend_builders.py` | Replace `_align_to_index` with `align.align_series` |
| `cryoquant/features/__init__.py` | Optional re-export: `align`, `panel` (or document import-from-submodule only) |
| `cryoquant/backtest/__init__.py` | No change |

---

## 3. What we explicitly do NOT add

| Item | Reason |
|---|---|
| `cryoquant/pipeline.py` orchestrator | Analysis scripts are the orchestrator |
| `experiments/` tree | YAGNI (D22/D23) |
| Feature catalog YAML | YAGNI |
| ML sweep / Optuna harness | Add only when a study needs it; use `fit_loop` first |
| `load_any` async / parallel fetch | `ingest.run_ingest` already batch-loads |
| Changes to `analyses/` | Out of scope |
| Remove CLI `backtest` / `signals` stubs | **Do not** — users still call them (D22) |
| Wire CLI backtest/publish to library | Deferred; stubs stay until a real implementation ships |

---

## 3.1 Backward compatibility policy

| Change type | Policy |
|---|---|
| New modules (`align`, `resolve`, `panel`, `fit_loop`) | Additive — old imports unchanged |
| `loader`, `macro_store`, builders, signals, backtest | **No signature changes** |
| `trend_builders` → `align` refactor | Internal only; `test_features_trend_builders` must pass unchanged |
| Feature cache | Bump builder `version` only if output values intentionally change |
| CLI | `catalog` + `models` live; `backtest` + `signals publish` **stubs retained** (exit 0) |
| Deprecation | If stubs are removed later: one release with `DeprecationWarning` + doc notice |

**Already reverted:** Phase 6A briefly removed CLI stubs; restored per user request (D22 update).

---

## 4. Documentation updates

### 4.1 `docs/how_to_use.md` *(major restructure)*

**Header:** bump to v1.1, date 24 Jun 2026.

**New §2 — Choose your path** (insert before current §2, renumber rest):

| Path | When | Sections to read | Code entry |
|---|---|---|---|
| **A — Quick indicator** | 2–5 series, rule-based | §4 load, §5 primitives, §8 signals, §9 backtest | `scripts/quick_indicator.py` |
| **B — Study / sweep** | Many symbols, parameter grids | §4 ingest, §5 builders, §9 + sweep docs | `analyses/` pattern, `breakout_sim` |
| **C — ML indicator** | 10–20+ tracks, ProbSignal | §4–8, `fit_loop` | `scripts/ml_multi_source.py` |

Include decision tree (mermaid) and “when to promote to framework” box.

**New §5.4 — Aligning series from different sources**
- `align_series`, `align_many`, `htf_align` when to use which.
- Staleness / `ffill_limit` for monthly macro.
- Anti-pattern: `shift(-1)` on features.

**New §4.3 — `load_track` / batch loads**
- One function for OHLCV + macro.
- Link to `ingest` for 20+ symbols.

**New §7.3 — Walk-forward with `fit_loop`**
- Replace expanded manual loop with `walk_forward_fit` example.

**Update §12 Best practices**
- Add “strict at seams” table (data in, signal out).
- Promote rule: 2 analyses → framework.

**Update §13 Workflow**
- Split into Path A / B / C checklists (not one linear 8-step list).

**Trim:** de-emphasise CryoTrader publish steps (6B postponed); keep as optional footnote.

---

### 4.2 `docs/how_to_add_a_signal.md` *(minor)*

- Opening paragraph: link to `how_to_use.md` §2 path picker.
- Note: Path A signals may live in analysis scripts; only promote to `cryoquant/signals/` when reused.

---

### 4.3 `docs/FRAMEWORK_STATUS.md` *(after implementation)*

Add rows:

| Module | Key exports |
|---|---|
| `features/align.py` | `align_series`, `align_many`, `join_features` |
| `features/panel.py` | `DataPanel` |
| `data/resolve.py` | `load_track`, `load_tracks` |
| `models/fit_loop.py` | `walk_forward_fit`, `FoldResult` |

Update architecture diagram `features/` line to include `align`, `panel`.

---

### 4.4 `docs/quant_plan.md` *(philosophy paragraph)*

Add short §2.6 **Framework philosophy:**
- Library not workflow engine.
- Three paths (A/B/C).
- Promotion criteria.
- Pointer to `workflow_plan.md`.

---

### 4.5 `docs/glossary.md` *(minor)*

Add entries: `DataPanel`, `align_series`, `load_track`, Path A/B/C.

---

### 4.6 `README.md` *(minor)*

Under “Current status”: link `how_to_use.md` §2 path picker.
List `scripts/quick_indicator.py` in quick start.

---

## 5. Test plan summary

| File | ~tests | Covers |
|---|---|---|
| `tests/test_features_align.py` | 8–10 | asof, ffill, limit, tz, align_many |
| `tests/test_data_resolve.py` | 5–7 | routing OHLCV vs macro, load_tracks |
| `tests/test_features_panel.py` | 5–6 | from_loads, align_track, to_frames |
| `tests/test_models_fit_loop.py` | 4–5 | walk_forward_fit, concat_oos_probs |
| Update `tests/test_features_trend_builders.py` | — | Still passes after align refactor |

Target: +25–30 tests, all offline.

---

## 6. Implementation sequence

| Step | Work | Est. |
|---|---|---|
| **1** | `features/align.py` + tests + refactor `trend_builders` | ½ day |
| **2** | `data/resolve.py` + tests | ½ day |
| **3** | `docs/how_to_use.md` §2 + §5.4 + §4.3 (align + load_track docs; can doc align before resolve ships) | ½ day |
| **4** | `scripts/quick_indicator.py` | 2 h |
| **5** | `features/panel.py` + tests | ½ day |
| **6** | `models/fit_loop.py` + tests + `how_to_use` §7.3 | ½ day |
| **7** | `scripts/ml_multi_source.py` | 3 h |
| **8** | FRAMEWORK_STATUS, glossary, README, quant_plan §2.6 | 2 h |

**Total:** ~2.5–3 days focused work.

Step 1 alone unblocks most simple-path pain; steps 5–7 unlock the complex ML path.

---

## 7. Acceptance criteria

Framework workflow layer is “done” when:

1. Path A example script runs end-to-end without `FeatureBuilder` or registry.
2. Path C example script runs with `DataPanel` + `walk_forward_fit` on ≥3 mocked tracks.
3. `trend_builders` uses public `align` module; no duplicate `_align_to_index`.
4. `how_to_use.md` §2 lets a new user pick a path in &lt;2 minutes.
5. All new tests green; total offline count &gt;500.

---

## 8. Open decisions (defaults chosen)

| Question | Default in this plan |
|---|---|
| Re-export from `cryoquant.features` top-level? | No — import from submodules (matches existing style) |
| `load_track` for `manual/` CSV macros? | Yes — check CDX `macro_store` pattern |
| Add `Instrument.meta["storage"]` enum? | Defer — use `asset_class` first |
| Optuna helper in `fit_loop`? | Defer to Phase 7+ |
