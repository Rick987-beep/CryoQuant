# HANDOVER — france_sovereign_stress v7 explore

> **Concluded 13 Oct 2026.** Results: [`RESULTS_V7.md`](RESULTS_V7.md). Trade write-up:
> [`TRADES_V7_GUIDE.md`](TRADES_V7_GUIDE.md) / `.html` (OOAT put + OGBL call pair, fixed 3/3
> spread stop 30, Société Générale 56/40 put spread Jun 2027). The brief below is kept for history.

**Start a new Cursor chat** with workspace `/Users/ulrikdeichsel/CryoQuant`.  
This file is the brief. Do **not** continue the long v6/IBRateTrade thread.

**Goal:** same trade idea and drivers, **simpler book: no add ladder**. Fixed size (or stop-only), daily-close, still short FOAT / long FGBL.

---

## 1. Paste into the new chat

```
Read studies/france_sovereign_stress/HANDOVER_V7.md.

Explore v7: same OAT–Bund thesis and drivers as v6, but NO pyramid/ladder of adds.
Fixed size + stop (or stop-only variants). Reuse v6 snapshot, calibration, scenarios,
and refresh tooling. Compare payouts and margin vs v6 primary (stop 40 / +20).

Stay in CryoQuant studies/france_sovereign_stress (or a clear v7 subfolder if cleaner).
Do not build IBKR automation here — that is IBRateTrade.
Research only from this study unless I ask otherwise.
```

---

## 2. Thesis (unchanged)

OAT–Bund 10Y spread can reprice into ~200–300 bp (or beyond) into mid-2027 on French budget / politics / election / limited ECB backstop. Vehicle: **short Euro-OAT (FOAT) / long Euro-Bund (FGBL)** on Eurex, duration-matched.

Drivers and scenario odds stay in `config.yaml` `view.scenario_odds` (subjective; not used for EV).

---

## 3. What v6 already proved (keep)

| Topic | Takeaway |
|-------|----------|
| Snapshot | Active `2026-10-12T0941`; entry **137.34 bp**; history to **2026-10-09** |
| Refresh | `run_refresh.py` / `run_snapshot.py`; live quote + merge frozen history |
| Primary ladder book @300 | mean **11.69×**, median **15.35×**, lost **25.7%** (€10k, n=10k) |
| **Stop-only (no adds) @300** | mean **3.75×** — already in RESULTS sensitivities; this is the closest v6 proxy to “no ladder” |
| No-event | mean ~0.51×, ~61% stopped out |
| Timing | Early stress ≫ late stress (terciles ~15.9 / 11.9 / 7.3×) |
| Vol | ×1.5 hurts a lot (~8.5×, ~45% lost); calmer vol helps (~13.3×) |
| Costs | Lynx **€2.00**/side; half-tick **€5** validated |
| Margin (additive IM) | FOAT €3,247 / FGBL €2,363 per contract; 3/3 entry ~€16.8k; 20/18 cap ~€107k |
| Execution | Daily-close default; IBKR cannot rest stop on synthetic spread; **two separate tickets** (no OAT–GBL combo) |
| IB automation | Separate repo **`/Users/ulrikdeichsel/IBRateTrade`** — out of scope for v7 research |

Archives: `archive/2026-10-09T1456/`, `archive/2026-10-12T0941/`.

---

## 4. v7 design intent

**Drop:** add-every-+20 pyramid, contract ladder to 20/18, “equity ÷ 40 after each add”.

**Keep:** FOAT/FGBL hedge, daily-close stop, carry/costs, same MC worlds (reuse CRN if possible), same exit levels 240/300/340/400, same budget notion (€ at risk).

**Propose and compare at least:**

1. **Fixed N contracts** (e.g. 3/3 or sized so stop ≈ budget) + hard stop X bp from entry  
2. **Stop-only** continuous €/bp (v6 already has `stop_only` ~3.75×) as baseline  
3. Optional: one scale-in (single add) vs full ladder — only if useful as intermediate  

Report: mean / median / lost @300, no-event, margin IM at entry (and max), operational complexity vs v6.

---

## 5. Key paths

| | Path |
|---|------|
| Study root | `studies/france_sovereign_stress/` |
| Results v6 | `RESULTS.md`, `data/phase5_evaluate.json` |
| Interactive | `explore_interactive.html` |
| Rules engine | `src/rules.py` (`stop_only` / sleeve without step) |
| Margin | `src/margin.py`, `config.yaml` → `margin` |
| Refresh | `run_refresh.py` |
| IB bot (later) | `/Users/ulrikdeichsel/IBRateTrade` |

---

## 6. Suggested first steps for the new agent

1. Read this file + `RESULTS.md` sensitivities (`stop_only`).  
2. Sketch v7 rule(s) in PLAN or a short `EXPLORE_V7.md` — no code until agreed, or light probes if asked.  
3. Reuse `FSS_SNAPSHOT` / stamp `2026-10-12T0941` so numbers compare cleanly to v6.  
4. Prefer extending evaluate sensitivities over forking the whole study; promote to `v7` only if the simple book is the new primary.

---

## 7. Safety

- Study remains **research only** (no orders from CryoQuant).  
- Never delete TradeUbuHetz.  
- Commit only when asked.
