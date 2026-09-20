# VIXStrategy — Results

Last refreshed: **2026-09-20 19:16** (cash-VIX Overlay Y re-run; VX futures not used yet).

## Window & account

| Knob | Value |
|------|--------|
| Research window | **2016-09-19 → 2026-09-18** (trailing 10y → last complete UTC day; CBOE through Fri 2026-09-18) |
| Bars | 2,547 |
| Start cash | $100,000 |
| Instrument | Mini VIX (**VXM**), **$100 / point** |
| Grid | Y1=160 · Y2=288 · Y3=480 · **928** total (contracts ∈ {1, 2}) |
| Fees / spread / slip | 0 (hooks ready) |

## Overlay Y isolation — best by idea

| Idea | Run | Terminal | Return | Trades/yr | Max DD | Contracts |
|------|-----|----------|--------|-----------|--------|-----------|
| **Y2** | Y2_245 | **$171,775** | +72% | 38.6 | −8.1% | 2 |
| **Y1** | Y1_121 | **$162,720** | +63% | 37.2 | −7.9% | 2 |
| **Y3** | Y3_539 | **$123,864** | +24% | 5.5 | −2.5% | 2 |

Pass A (terminal > start): **926 / 928**.

Overall leaderboard is Y2-dominated at this lot size. That is expected: 1–2 VXM contracts are ~2–4% of the old unit-NAV `weight=1` risk (~50 contracts at VIX 20). See PLAN.

## Artifacts

- `reports/overlay_y_isolation_report.html`
- `reports/phase1_y_isolation_leaderboard.parquet`
- `reports/phase1_y_isolation.json`
- `reports/phase0_data.json`
- `data/vix_daily_ohlc.parquet`

## Next

1. Fear / spike catalog (Overlay T evaluation episodes)
2. Overlay T + T+Y mutex compose
3. Optional risk-matched sizing screen (fairer Y1/Y2 vs Y3)
