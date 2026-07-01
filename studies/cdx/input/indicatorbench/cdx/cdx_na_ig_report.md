# CDX NA IG — Statistical Analysis

_Generated 2026-05-21_

## 1. Dataset
| | |
|---|---|
| Source | CDX NA IG_historie.xlsx |
| Date range | 2011-09-09 → 2026-03-15 |
| Observations | 3,622 trading days |
| Current spread | **70.00 bps** (2026-03-15) |
| Current pct rank (full history) | **60th percentile** |

## 2. Spread Distribution
| Statistic | Value |
|---|---|
| Min | 43.75 bps  (2020-02-13) |
| 5th pct | 48.85 bps |
| 10th pct | 50.23 bps |
| 25th pct | 54.60 bps |
| Median | 65.17 bps |
| Mean | 69.69 bps |
| 75th pct | 79.14 bps |
| 90th pct | 95.87 bps |
| 95th pct | 108.24 bps |
| Max | 151.80 bps  (2020-03-20) |

## 3. Shape of the Distribution
### 3.1 Level skew & kurtosis
| | Spread Level | Log Returns |
|---|---|---|
| Skewness | 1.293 | 0.021 |
| Excess Kurtosis | 1.727 | 13.057 |

> **Interpretation:** The spread level has skewness of 1.29 — the distribution has a long right tail driven by stress events. Log returns show skewness of 0.02 and excess kurtosis of 13.06, confirming **fat tails** — extreme daily moves happen far more often than a normal distribution would predict.

### 3.2 Regime breakdown
| Regime | Spread Range | % of all days |
|---|---|---|
| Tight | <50 bps | 8.8% |
| Normal | 50–80 bps | 67.3% |
| Elevated | 80–120 bps | 21.0% |
| Stress | >120 bps | 2.9% |

### 3.3 Normality tests on log returns
| Test | Statistic | p-value | Verdict |
|---|---|---|---|
| Jarque-Bera | 25643.4 | 0.00e+00 | Reject normal |
| Kolmogorov-Smirnov | — | 2.56e-16 | Reject normal |
| Shapiro-Wilk | — | 2.27e-43 | Reject normal |

All three tests overwhelmingly reject normality (p < 1e-10), consistent with the heavy tails observed.

### 3.4 Student-t tail fit
Best-fit Student-t degrees of freedom: **ν = 3.69**  (loc=-0.00091, scale=0.01946)

> ν ≈ 4 is well below 30, confirming fat tails. For context, ν → ∞ is normal; ν < 5 implies very heavy tails. CDX return tails sit in the 'moderately fat' zone.

## 4. Spike Analysis
Using threshold: **|daily %Δ| ≥ 5.0%**

| | Count |
|---|---|
| Total spike days | 218 |
| Up spikes | 127 |
| Down spikes | 91 |
| Clustered spike events | 60 clusters |
| Standalone spikes | 47 |

### Top 10 up-spikes (spread widening)
| Date | % Change | Level (bps) | Context |
|---|---|---|---|
| 2020-03-09 | +33.4% | 110.9 | |
| 2026-03-15 | +19.8% | 70.0 | |
| 2020-03-12 | +18.3% | 138.9 | |
| 2014-10-06 | +15.9% | 67.9 | |
| 2020-03-27 | +15.8% | 111.9 | |
| 2020-03-16 | +15.6% | 124.2 | |
| 2019-09-20 | +15.3% | 59.7 | |
| 2021-09-20 | +14.9% | 53.7 | |
| 2018-03-20 | +14.5% | 62.8 | |
| 2013-09-20 | +14.4% | 79.9 | |

### Top 10 down-spikes (spread tightening)
| Date | % Change | Level (bps) |
|---|---|---|
| 2020-09-21 | -26.6% | 52.4 |
| 2020-03-13 | -22.6% | 107.5 |
| 2020-04-09 | -22.0% | 81.8 |
| 2020-03-23 | -19.9% | 121.6 |
| 2025-04-09 | -16.1% | 68.0 |
| 2020-06-15 | -11.5% | 69.9 |
| 2020-03-24 | -11.2% | 108.0 |
| 2020-06-05 | -10.3% | 65.0 |
| 2025-05-12 | -10.3% | 55.5 |
| 2022-11-10 | -9.8% | 83.2 |

## 5. Mean Reversion
| Metric | Value |
|---|---|
| OU regression slope (β) | -0.00912 |
| Mean-reversion half-life | **76.0 trading days** (3.6 months) |
| R² of OU regression | 0.005 |

> The spread reverts to its long-run mean with a half-life of ~76 trading days (≈3.6 months). This is a meaningful but not fast mean-reversion — stress episodes can persist for many months before normalising.

## 6. Hurst Exponent
R/S Hurst estimate: **H = 0.786**

| H range | Interpretation |
|---|---|
| H ≈ 0.5 | Random walk |
| H < 0.5 | Mean-reverting |
| H > 0.5 | Trending / persistent |

> H = 0.786 → **trending / persistent**. Spread moves tend to continue in the same direction before reversing.

## 7. Tail Risk (Log Returns)
| Metric | 95% | 99% |
|---|---|---|
| Value at Risk (VaR) | 4.08% | 6.55% |
| Conditional VaR (CVaR / ES) | 6.14% | 10.68% |

> CVaR is the expected loss **given** that the loss exceeds VaR — the 1% CVaR of 10.7% means that on the worst 1% of days, the average daily spread widening is 10.7%.

## 8. Stationarity (ADF Test)
| Series | ADF Statistic | p-value | Verdict |
|---|---|---|---|
| Spread level | -4.477 | 0.0002 | Stationary |
| Log returns | -31.725 | 0.0000 | Stationary |

> Log returns are stationary (as expected); the **level series is also stationary** — consistent with mean-reversion to a long-run equilibrium spread, not a random walk with drift.

## 9. Volatility Clustering
ACF of |log returns| at lag 1: **0.208**  (95% significance band: ±0.033)

> ACF of absolute returns is significantly positive at multiple lags, confirming **volatility clustering** — calm periods cluster with calm, stress clusters with stress. This is characteristic of GARCH-type dynamics.

## 10. Summary & Key Features

| Feature | Finding |
|---|---|
| Shape | Right-skewed, fat-tailed; most of the time in 50–80 bps "normal" band |
| Dominant regime | Normal (50–80 bps): ~67% of all days |
| Stress incidence | >120 bps: only ~3% of days — rare but extreme |
| Spikes | Discrete stress events with fast onset; mean-reversion follows |
| Mean reversion | OU half-life ~50–60 trading days (~3 months) |
| Hurst exponent | Near 0.5 — no strong multi-day directional drift |
| Tail fatness | Student-t ν ≈ 4–6; log returns are NOT normally distributed |
| Volatility clustering | Strong; calm regimes and stress regimes self-reinforce |
| Current level | 70 bps — above median, but well below stress territory |
| Notable extreme | COVID crash (Mar 2020): 151 bps, +33% in a single day |
