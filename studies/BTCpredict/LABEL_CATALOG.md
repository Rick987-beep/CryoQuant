---
name: BTCpredict v1 — Label catalog
status: signed off (2026-06-28)
version: 1
review_date: "2026-06-28"
upstream: KICKOFF §5.4, §6 (P-4, P-5, P-0b), SPEC §9
machine_readable: labels.yaml
config_gate: config.yaml → phase2_complete: true
path_touch: deferred (Phase 6 — ExitRule / management policy)
build_status: complete
build_date: "2026-06-28"
---

# BTCpredict v1 — Label catalog

**Purpose:** Authoritative register of every row in `data/labels.parquet`. Labels are **never** merged into `features.parquet` (P-4).

**Panel alignment:** one label row per `(timestamp, asset, horizon_id, label_name)`. Timestamps match the Phase 2 feature panel (UTC daily bar open). SOL rows start 2020-08-11.

**Sign-off:** ✅ **2026-06-28** — families 1–6 locked and built; family 7 (path/touch exceedance) **deferred** to Phase 6. `phase3_complete: true`.

---

## Horizons (locked)

| `horizon_id` | `horizon_bars` | Use |
|---|---|---|
| `T+1d` | 1 | Tactical / ~1–2 DTE |
| `T+5d` | 5 | Weekly swing / ~7 DTE |
| `T+10-21d` | 14 | Position tilt / ~14–30 DTE |

---

## Label families

### 1 — Directional (Goal 1 + option side tilt)

| `label_name` pattern | Type | Formula |
|---|---|---|
| `up_win_t{t}_h{H}` | binary | Forward max-high over `(t+1..t+H]` ≥ `close[t] × (1+τ/100)` |
| `down_win_t{t}_h{H}` | binary | Forward min-low ≤ `close[t] × (1-τ/100)` |
| `magnitude_win_t{t}_h{H}` | binary | Either up or down barrier hit |
| `*_win_volscaled_h{H}` | binary | Same, with per-bar `τ = vol_scale_k × σ_daily × √H` |

**Threshold τ:** fixed `direction_threshold_pct` (default 1.5%) when `use_vol_scaled_threshold: false`; else `VolScaledThreshold` with trailing window `realized_vol_window` (5 bars).

**Assets:** BTC, ETH, SOL.

---

### 2 — Log return (benchmark + quantile-head input)

| `label_name` | Type | Formula |
|---|---|---|
| `log_return_h{H}` | float | `ln(close[t+H] / close[t])` |

**Assets:** BTC, ETH, SOL.  
**Note:** conditional quantiles are **model outputs** (Phase 4), not separate label columns.

---

### 3 — Forward realized volatility (Goal 2 vol head)

| `label_name` | Type | Formula |
|---|---|---|
| `fwd_rv_h{H}` | float | `std(daily log ret, t+1..t+H) × √252 × 100` (annualised %) |

**Assets:** BTC, ETH, SOL.

---

### 4 — Terminal exceedance — call (Goal 2)

| `label_name` pattern | Type | Formula |
|---|---|---|
| `exceedance_call_d{d}_h{H}` | binary | `close[t+H] > close[t] × exp(q_call)` |

`q_call` = causal rolling `quantile(1-δ)` of past forward log returns (`exceedance_quantile_lookback`, default 252).

**Assets:** BTC, ETH only (options book v1).

---

### 5 — Terminal exceedance — put (Goal 2)

| `label_name` pattern | Type | Formula |
|---|---|---|
| `exceedance_put_d{d}_h{H}` | binary | `close[t+H] < close[t] × exp(q_put)` |

`q_put` = causal rolling `quantile(δ)` of past forward log returns (typically negative).

**δ grid:** 0.10, 0.15, 0.20 (`config.label.exceedance_deltas`).

**Assets:** BTC, ETH only.

---

### 6 — VRP realization (Goal 2 entry timing)

| `label_name` | Type | Formula |
|---|---|---|
| `vrp_realized_h{H}` | float | `DVOL_t − fwd_rv_h{H}` |

`DVOL_t` = Deribit vol index at *t* (`BTC_DVOL` / `ETH_DVOL`). Forward RV matches family 3.

**Assets:** BTC, ETH only. Skipped when `vrp_enabled: false` or IV series missing.

---

### 7 — Path / touch exceedance ⏸ DEFERRED

Intraday strike touch over `(t+1..t+H]` for managed exits (`ExitRule`). Build when Phase 6 management policy is swept — not v1 labels.

---

## Row counts (approximate)

| Scope | Families | Labels per (asset, horizon) |
|---|---|---|
| BTC, ETH, SOL | 1–3 | 5 (+3 volscaled names replace fixed-τ names when vol-scaled) |
| BTC, ETH | 4–6 | +9 (6 exceedance + 1 VRP + already counted 1–3) |

Trailing `H` rows per series are **NaN** (incomplete forward window).

---

## Causality rules

- Labels at *t* may use `OHLCV[t+1..t+H]` and `IV_t` only — never future IV or features.
- Exceedance strike quantiles use **past** forward returns only (`shift(1)`).
- Raw OHLCV loaded via `load_track` (not from `features.parquet`).

---

## Phase 3 artifacts

- `data/labels.parquet` — **246,887 rows** (2026-06-28 build)
- `data/labels_schema.json` — **36** `label_name` values
- `data/phase3_qa_report.json`
- `config.yaml` → `phase3_complete: true`
