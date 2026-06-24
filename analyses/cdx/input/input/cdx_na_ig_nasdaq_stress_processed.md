# CDX NA IG and NASDAQ Under Stress — Processed Extract
Source: `input/Microsoft Word - CDX_NA_IG_and_NASDAQ_Under_Stress_Working_Paper_2026-3.docx.pdf`
Author: Thao Nguyen | Working Paper 2026 | Confidential Draft

## Metadata
- Sample: 3,668 daily obs, Sep 2011 – Jun 2026
- Instruments: CDX NA IG 5Y on-the-run (bps), NASDAQ Composite
- Model: 3-state Markov-Switching VAR (EM), regimes by velocity volatility
- Signals: Widening +3% 3d pct chg; Tightening −5% 3d pct chg; Confirmed = 2nd tightening within 20d

## Table 1 — Regimes
| Metric | Low-Stress | Moderate-Stress | High-Stress |
|--------|------------|-----------------|-------------|
| Share of days | 63.1% | 29.4% | 7.5% |
| σ (3-day % chg) | 2.22% | 2.99% | 7.61% |
| Median \|3-day % chg\| | 2.18% | 3.13% | 8.80% |
| Weighted-median CDX level | ~63 bps | ~71 bps | ~70 bps |
| ρ(CDX Δ, NASDAQ ret) | −0.74 | −0.82 | −0.67 |

## Table 2 — Granger (3-day % spec)
| Regime | CDX→NDQ F | p | NDQ→CDX F | CDX predictor? |
|--------|-----------|---|-----------|----------------|
| Low | 2.13 | 0.095 | 142.4 | No |
| Moderate | 5.19 | 0.001 | 96.9 | Yes ** |
| High | 4.99 | 0.002 | 11.7 | Yes ** |

## Table 5a — Confirmed tightening accuracy
| Horizon | Recovery | False |
|---------|----------|-------|
| 5d | 63.8% | 36.2% |
| 10d | 73.8% | 26.2% |
| 20d | 75.5% | 24.5% |
| 20d (99 episodes) | 68% | 32% |

## Table 5b — Single vs confirmed
| Type | n | Fwd 10d | Fwd 20d | P(up) 20d |
|------|---|---------|---------|-----------|
| Single | 61 | −0.19% | +0.72% | 64% |
| Confirmed | 359 | +1.28% | +2.43% | 75% |

## Table 5d — OOS (split Jan 2023)
| Period | n | Fwd 20d | P(up) 20d |
|--------|---|---------|-----------|
| IS confirmed ≤2022 | 298 | +1.90% | 73% |
| OOS confirmed 2023–26 | 61 | +5.01% | 85% |
| OOS episodes | 17 | +3.09% mean | p=0.001 |

## Event study (11 corrections) — key stats
- Median peak→trough drawdown: −13.1%
- Median DD duration: 42 trading days
- Widening signal: median 12d after peak, 28d before trough
- Confirmed tightening: median 3d from trough (8/11 within 1 week)
- CDX move % vs drawdown: r = −0.85
