# Signal Input Parameters

**Adaptive BTC Options Portfolio · Overview for CryoTrader**

The following market and macro inputs are supplied as **daily values** to the portfolio signal logic. All three strategy modules (regime filter, short volatility, long convexity) draw from the **same data foundation**; how strongly each input matters in a given module follows from that module’s calibration and does not require separate configuration on your side.

**Timing:** values reflect **prior-day end-of-day** data and/or a **~08:00 Europe/Berlin** morning snapshot — with no forward-looking information.

---

## 1 · Price Trend & Momentum

| Parameter | Why it matters for the BTC price |
|-----------|----------------------------------|
| Bitcoin performance **7 days** | Short-term direction and trend strength — helps judge continuation vs. exhaustion. |
| Bitcoin performance **year-to-date** | Position within the annual move; extremes suggest stretched or persistent market phases. |
| **RSI (14 days)** | Whether the market is short-term overbought or oversold — relevant for correction vs. trend scenarios. |
| **MACD trend strength** | Whether the trend is accelerating or fading — often visible before raw price alone. |
| **Distance from 200-day average** | Separates structurally bullish from bearish phases over months. |
| **Performance 14 days** | Medium-term momentum — more stable than a one-week move alone. |
| **Performance 30 days** | Monthly trend as a filter for the medium-term backdrop. |
| **Net up/down days (7 days)** | Whether the market is “running hot” or looks exhausted — short-term overheating or capitulation. |

---

## 2 · Market Sentiment

| Parameter | Why it matters for the BTC price |
|-----------|----------------------------------|
| **Fear & Greed Index (current)** | Aggregated investor mood; extremes often signal euphoria (correction risk) or panic (recovery potential). |
| **Fear & Greed Index (7-day average)** | Smoothed sentiment — less daily noise, clearer regime signal. |

---

## 3 · Broader Crypto Market

| Parameter | Why it matters for the BTC price |
|-----------|----------------------------------|
| **ETH/BTC ratio (7-day change)** | Rising ratio = more risk appetite in altcoins — often coincides with a supportive BTC backdrop. |
| **Total crypto market cap (7-day change)** | Whether the broad crypto rally moves with BTC or is isolated. |

---

## 4 · Derivatives & Market Leverage

| Parameter | Why it matters for the BTC price |
|-----------|----------------------------------|
| **Funding rate (7-day average)** | Shows whether long or short positioning dominates — high positive funding often indicates an overheated long side. |
| **Funding rate (percentile vs. 60 days)** | Places current leverage conditions in historical context. |
| **Open interest (7-day change)** | Rising OI with a trend = new positioning; falling OI with a move = possible trend exhaustion. |
| **Open interest (14-day change)** | Medium-term build-up or unwind of derivatives positioning. |

---

## 5 · Volatility

| Parameter | Why it matters for the BTC price |
|-----------|----------------------------------|
| **Implied volatility (DVOL, level)** | The “price of uncertainty” — central for options strategy context and expected move size. |
| **Implied volatility (percentile vs. 90 days)** | Whether options volatility is historically cheap or expensive. |
| **Implied volatility (7-day change)** | Whether the vol environment is rising (stress) or falling (calm). |
| **Realized volatility (14 days, annualized)** | Actual movement experienced — comparison with implied vol shows over- or under-pricing of options. |

---

## 6 · Chart Structure & Market Position

| Parameter | Why it matters for the BTC price |
|-----------|----------------------------------|
| **Position in Bollinger Bands (20 days)** | Extremes suggest stretched prices and potential mean reversion. |
| **Position in 20-day price range** | Proximity to range high or low — breakout vs. sideways phase. |
| **Distance from 52-week high** | Psychologically important level; large gap = recovery or weakness phase. |
| **50-day vs. 200-day average** | Classic regime signal (golden cross / death cross) for medium-term trend direction. |
| **Distance from 20-day average** | Short-term trend above or below the moving average. |
| **Distance from 50-day average** | Medium-term trend — filter for entry conditions. |

---

## 7 · Institutional BTC Demand (Strategy Inc.)

| Parameter | Why it matters for the BTC price |
|-----------|----------------------------------|
| **Number of SEC filings (purchases, 30 days)** | Activity of large listed BTC buyers — structural spot demand. |
| **BTC purchased (30 days)** | Size of recent institutional buying pressure. |
| **BTC purchased (90 days)** | Longer accumulation trend beyond short-term noise. |
| **Days since last filing** | “Fresh” institutional news can support the market short term. |
| **Active purchase period (yes/no)** | Whether the market is in a known accumulation window. |

---

## 8 · ETF & Fund Volume

| Parameter | Why it matters for the BTC price |
|-----------|----------------------------------|
| **Largest US BTC ETF (price level)** | Liquidity and institutional access proxy for regulated BTC exposure. |
| **ETF trading volume (deviation vs. 30 days)** | Unusual activity = institutional rotation, often linked to trend continuation. |
| **Sum of ETF volume (7-day change)** | Broad inflow/outflow trend via spot ETFs. |
| **Sum of ETF volume (deviation vs. 30 days)** | Trading activity unusually high or low vs. normal — regime or event signal. |

---

## 9 · Stablecoin Liquidity

| Parameter | Why it matters for the BTC price |
|-----------|----------------------------------|
| **Total stablecoin market cap** | Available “dry powder” in crypto — capital in stables can later rotate into BTC. |
| **Stablecoin market cap (7-day change)** | Short-term liquidity inflow or outflow. |
| **Stablecoin market cap (30-day change)** | Medium-term liquidity trend in the market. |

---

## 10 · Network & US Demand

| Parameter | Why it matters for the BTC price |
|-----------|----------------------------------|
| **Bitcoin hash rate** | Network security and miner confidence — long-term trust signal. |
| **Hash rate (30-day change)** | Rising hash rate = miners investing; falling = stress in the mining sector. |
| **Coinbase premium vs. Binance** | US buying pressure (institutional/retail); positive premium often bullish for BTC. |
| **Coinbase premium (7-day average)** | Smoothed US demand signal without daily noise. |

---

## 11 · Global Macro Backdrop

| Parameter | Why it matters for the BTC price |
|-----------|----------------------------------|
| **US Dollar Index (level)** | A strong dollar typically weighs on risk assets including Bitcoin. |
| **US Dollar (1-day / 7-day change)** | Short- and weekly dollar moves as risk-on/off filters. |
| **US 10-year yield (level)** | Higher “risk-free” yields compete with speculative assets like BTC. |
| **US 10-year yield (1-day / 7-day change)** | Fast rate moves affect liquidity and risk appetite. |
| **VIX — global fear (level)** | High VIX = risk-off; low VIX = calmer, more risk-seeking environment. |
| **VIX (1-day / 7-day change)** | Sudden or sustained global uncertainty. |
| **VIX (deviation vs. 30 days)** | Whether global fear is historically unusually high or low. |
| **Gold (7-day change)** | Safe-haven competition; gold rally with weak BTC = risk-off rotation. |
| **Nasdaq (1-day / 7-day change)** | Tech/growth risk proxy; BTC often correlates with Nasdaq. |
| **S&P 500 (7-day change)** | Broader US equity market as a gauge of global risk appetite. |

---

## 12 · Combined Market Indicators

These values combine multiple individual inputs into **thematic summaries** (trend, sentiment, derivatives, volatility, ETF flows, macro, etc.). They give the signal logic a compressed view of the overall market environment.

| Theme | Why it matters for the BTC price |
|-------|----------------------------------|
| **Trend & technicals (combined)** | Single read on all price and trend signals together. |
| **Sentiment (combined)** | Aggregated mood across sentiment sources. |
| **Crypto market (combined)** | Broader crypto backdrop beyond BTC price alone. |
| **Derivatives market (combined)** | Leverage and positioning environment at a glance. |
| **Volatility (combined)** | Whether the options and volatility backdrop is favourable or stressed. |
| **Institutional purchases (combined)** | Structural BTC demand from large buyers, summarized. |
| **Market structure (combined)** | Chart and range position in compressed form. |
| **ETF flows (combined)** | Regulated institutional inflow/outflow via ETFs. |
| **Stablecoin liquidity (combined)** | Available buying power in the system, summarized. |
| **Global macro (combined)** | Dollar, rates, equities, fear index — external backdrop for BTC. |

---

*June 2026 · Mindworks Institut · Adaptive BTC Options Portfolio*
