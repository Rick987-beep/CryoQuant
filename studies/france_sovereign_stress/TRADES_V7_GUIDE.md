# Three ways to trade a French bond scare

A plain-language guide for private traders. Research only, not investment advice.

Prices are a snapshot from **Tuesday 13 October 2026, 10:10 Paris time**. Check live prices before you place any order: option prices change every minute, and every number below scales with them.

---

## Before you start: the idea in five sentences

1. France pays more than Germany to borrow for ten years. The gap between the two interest rates is called **the spread**. On 13 October 2026 the French 10-year yield was 4.85% and the German one 3.44%, so the spread was **1.41 percentage points, or 141 bp** (one "bp", basis point, is 0.01 percentage points).
2. In past scares (the 2011 euro crisis, the 2024 snap election) this spread jumped quickly. The view behind these trades is that a new French budget or political crisis pushes it to **200 to 400 bp** before mid-2027.
3. When that happens, French government bonds fall in price, French bank shares fall, and investors often flee into German government bonds, which then rise in price.
4. Each trade below is a different way to profit from that, with the money you can lose fixed in advance.
5. If the scare never comes, all three trades lose most or all of their stake. The odds section of each trade spells this out.

### How we tested the trades

We simulated 10,000 possible futures for the next eight and a half months, separately for each target level (200, 250, 300 and 350 bp).

- In each simulated future the spread first wanders randomly from day to day, with the occasional large jump real markets show.
- At a random date before July 2027 a three-week panic pushes the spread up to the target level.
- During that panic the German 10-year yield also falls, by somewhere between 10% and 70% of the spread's rise (investors running into German bonds). This assumption matters a lot for Trade 1.
- We also ran a **"no event"** version: the spread drifts sideways with no trend until 1 July 2027.

Pricing rules:

- Option prices start from the real Eurex quotes on 13 October. Later prices are estimated with standard option maths. Option prices rise as the spread rises, in line with how much bond prices moved in 2011, 2024 and 2026.
- You buy at the asking price and sell at the bid price. Fees: €2.50 per option contract, and €2 per futures contract plus half a price step of slippage.
- **We assume you sell when the panic peaks.** In real life you won't know the top. If you sell earlier, expect results closer to a lower row of the tables.

### How to read the tables

- **Average** and **median** (the middle outcome, i.e. half of the simulated futures did better and half did worse) for each target level.
- **Bad case** and **good case** are the 1-in-10 worst and 1-in-10 best outcomes.
- **Lose most** is the share of simulated futures in which 90% or more of the stake is lost.

### The odds we use

These are subjective guesses from the original 5 October 2026 proposal, not facts.

| Scenario | What happens to the spread | Probability | Modelled as |
|---|---|---|---|
| Relief | Falls back to about 85 bp | 15% | "No event" |
| Grind | Stays around 140 to 170 bp | 50% | "No event" |
| Stress | Rises to 200 to 300 bp | 30% | Average of the 200, 250 and 300 bp results |
| Contested | Goes above 300 bp | 5% | Average of the 350 and 400 bp results |

Two thirds of the weight sits on "nothing much happens". That is why every trade below has roughly a coin-flip chance of losing most of its stake, and still shows a positive expected value: the wins, when they come, are several times the stake.

### The three trades at a glance

| | Trade 1: French put + German call | Trade 2: Spread futures | Trade 3: Société Générale puts |
|---|---|---|---|
| Money at risk | €10,000, spent in five instalments | About €8,000 (stop-loss), plus margin | €10,000, spent once |
| Can you lose more than the stake? | No | Yes, a little (stop is checked once a day) | No |
| Orders | About 2 every 8 weeks | 2 to open, 2 per quarter to roll, 2 to close | 1 to open, 1 to close |
| Result at 300 bp, average | €45,600 back | €24,000 profit | €32,900 back |
| Expected value with the odds above | +45% | +50% of the amount at risk | +55% |
| Chance of losing most of the stake | About 48% | About 51% | About 45% |
| Biggest weakness | Depends on money fleeing into German bonds | Stopped out in a third of the good scenarios | Profit is capped at about 4.5 times the stake |

---

## Trade 1: French bond put plus German bond call (50/50)

### 1.1 Trade idea and assumptions

**Idea.** Buy two kinds of cheap "insurance" options and keep renewing them until mid-2027:

- **Half the money: put options on French government bond futures.** They pay if French bond prices fall, i.e. if French interest rates rise.
- **Half the money: call options on German government bond futures.** They pay if German bond prices rise, i.e. if German interest rates fall because investors flee to safety.

Each option is far from today's price, so it is cheap and pays a lot only in a real scare. You can never lose more than the premiums you paid.

**Why the German leg?** Germany is not the problem, but in a euro scare money tends to run into German bonds. The trade bets on that reaction. In the model, the German 10-year yield falls by 10% to 70% of the spread's rise. At 300 bp that means a fall of 16 to 111 bp, about 64 bp on average. In the 2011 crisis it fell by well over a percentage point. In a purely French crisis where German yields barely move, this leg loses its premium.

**Assumptions specific to this trade:**

- The €10,000 is not spent at once. It is split into **five batches** that each last about eight weeks, from now until the end of July 2027. Each batch's size is proportional to how long it lasts. Money not yet spent stays in cash.
- When a batch expires, the next one is bought at the same distance from the market.
- **No new batch is bought once the spread is already above 200 bp.** Options are expensive by then, and you are already holding the current batch.
- When the scare peaks, everything still held is sold at the bid.
- The simulation allows fractions of contracts. With €10,000 the French leg is only 2 or 3 contracts per batch, so your real result will be a bit lumpier.
- **The strikes are 103 for the French put and 125.5 for the German call.** They scored best among 62 option trades we tested. They are also the furthest from the market we tested, so cheaper "lottery tickets" won, and the result leans heavily on the model's assumptions.

### 1.2 Results

Money back on a €10,000 stake (break-even is €10,000):

| Spread peaks at | Average | Median | Bad case (1 in 10) | Good case (1 in 10) | Lose most |
|---|---|---|---|---|---|
| 200 bp | €17,900 | €11,100 | €4,300 | €36,800 | under 1% |
| 250 bp | €31,800 | €19,000 | €6,400 | €70,100 | 0% |
| 300 bp | €45,600 | €27,800 | €7,500 | €102,100 | 0% |
| 350 bp | €60,800 | €37,900 | €9,100 | €135,100 | 0% |
| No event | €2,400 | €0 | €0 | €6,400 | 73% |

In the good scenarios almost nobody loses everything, because the scare ends the plan before the whole budget is spent.

**Where the money comes from.** At 300 bp the French put half alone averages 2.0 times its money and the German call half 7.1 times. Most of the upside is in the German leg. If option prices do **not** rise during the scare (they did in 2011), the German leg at 300 bp falls from 7.1 to about 3.7 times its money.

**Timing.** At 300 bp, a scare in the last third of the period does better (5.4 times) than an early one (4.1 times), because more batches have been bought by then.

### 1.3 Odds

| Scenario | Probability | Average money back |
|---|---|---|
| Relief or grind ("no event") | 65% | €2,400 |
| Stress (200 to 300 bp) | 30% | €31,800 |
| Contested (above 300 bp) | 5% | €69,100 |
| **Expected value** | | **€14,500 (+45%)** |

The chance of losing 90% or more of the stake is about **48%**. The median of the "no event" world is €0: if nothing happens, you most likely lose everything you put in.

### 1.4 How the trade works

- A **put option** on the Euro-OAT future (French bonds) gives you the right to sell that future at 103. The future trades around 109. If French 10-year yields rise by about 70 bp before expiry (from 4.85% to about 5.55%), the future falls to about 103. Beyond that point the put gains about €87 per contract for every further bp.
- A **call option** on the Euro-Bund future (German bonds) gives you the right to buy that future at 125.5. The future trades around 121.3. If German 10-year yields fall by about 43 bp (from 3.44% to about 3.0%), the future rises to about 125.5. Beyond that, the call gains about €98 per contract per bp.
- Before the strike is reached, both options can still gain value as the market moves towards them and as option prices rise in a panic. That is how you can sell them for a profit before expiry.
- Option prices are quoted in points: **1 point = €1,000 per contract**. A price of 0.39 costs €390, and 0.07 costs €70.

### 1.5 Step-by-step instructions

**What to trade (Eurex):**

| | French leg | German leg |
|---|---|---|
| Product | Options on Euro-OAT Futures | Options on Euro-Bund Futures |
| Eurex code | OOAT | OGBL |
| Product ISIN | DE000A1XRC52 | DE0009652685 |
| Bloomberg | OATA Comdty (options) | RXA Comdty (options) |
| Underlying | Euro-OAT future (FOAT, ISIN DE000A1MAPW3) | Euro-Bund future (FGBL, ISIN DE0009652644) |
| Contract | One future on €100,000 of French government bonds | One future on €100,000 of German government bonds |
| Style | American; can be exercised any day; exercise turns it into a futures position | Same |
| Eurex page | [OOAT](https://www.eurex.com/ex-en/markets/int/long-term-interest-rates/fix-opt/government-bonds/Options-on-Euro-OAT-Futures-137406) | [OGBL](https://www.eurex.com/ex-en/markets/int/long-term-interest-rates/fix-opt/government-bonds/Options-on-Euro-Bund-Futures-137308) |

Most brokers find these by product code, expiry month, strike and put/call. The ISIN identifies the product, not the individual strike.

**Batch 1, now (13 October 2026), about €1,340:**

| Order | Contract | Quantity | Limit price | Quotes on 13 Oct | Cost |
|---|---|---|---|---|---|
| Buy to open | OOAT **Dec 2026** 103 **put** (expires Fri 20 Nov 2026) | 2 | 0.39 at most (try 0.33 first) | bid 0.25, ask 0.39 | about €785 |
| Buy to open | OGBL **Dec 2026** 125.5 **call** (expires Fri 20 Nov 2026) | 9 | 0.07 | bid 0.06, ask 0.07; 4,041 contracts open | about €650 |

Use limit orders, never market orders. The French puts have a wide gap between bid and ask and no visible open interest, so be patient.

**Batches 2 to 5:** on each expiry day, if the scare has not happened and the spread is below 200 bp, buy the next batch.

| Date | Option month to buy (expiry) | Budget for the batch |
|---|---|---|
| Fri 20 Nov 2026 | Feb 2027 (expires Fri 22 Jan 2027) | about €2,230 |
| Fri 22 Jan 2027 | Apr 2027 (expires Thu 25 Mar 2027) | about €2,190 |
| Thu 25 Mar 2027 | Jun 2027 (expires Fri 21 May 2027) | about €2,010 |
| Fri 21 May 2027 | Aug 2027 (expires Fri 23 Jul 2027) | about €2,230 |

Expiry dates follow the Eurex rule (last Friday before the option month, with holiday adjustments). Confirm them on the Eurex page before each batch.

For each batch:

1. Split the budget in half.
2. **French put strike** = the current OAT future price minus 6 points, rounded to the nearest listed strike. Today: 109 − 6 ≈ 103.
3. **German call strike** = the current Bund future price plus 4.2 points, rounded to the nearest 0.5. Today: 121.3 + 4.2 ≈ 125.5.
4. Buy as many contracts of each as half the budget allows, with limit orders.

**If a batch ends up "in the money" near expiry:** sell it before the expiry day rather than letting it be exercised. Exercise would leave you holding a futures position that needs margin.

**When to sell everything:** decide your target before you start, for example 300 bp. When the spread (French 10-year yield minus German 10-year yield) closes at or above your target, sell all open options with limit orders near the bid. Sources: CNBC (FR10Y and DE10Y), Investing.com or your broker.

**Order count:** about 2 orders every 8 weeks, plus 2 to close.

---

## Trade 2: French–German bond spread with a fixed stop (3 against 3, stop 30 bp)

### 2.1 Trade idea and assumptions

**Idea.** Bet directly on the spread with futures:

- **Sell 3 French government bond futures** (Euro-OAT).
- **Buy 3 German government bond futures** (Euro-Bund).

If both countries' rates rise or fall together, the two sides roughly cancel out. What is left is a bet that **France's rates rise relative to Germany's**. Open once, never add to it, and get out if the spread narrows 30 bp below where you entered.

**Assumptions specific to this trade:**

- Each pair of contracts gains or loses about **€88 per bp** of spread move, so the position moves about **€265 per bp**.
- The stop is checked **once a day at the close**. If the spread closes 30 bp or more below entry (for example below 111 bp if you enter at 141 bp), you close the next morning.
  - A 30 bp loss is **€7,956**. That is the "stake" for this trade.
  - Because the stop is checked only once a day, the real loss is usually a bit larger, about €9,000.
- In a good scenario you close everything when the spread reaches your target.
- In the "no event" world you close on 1 July 2027 at the latest.
- The contracts are renewed ("rolled") into the next quarter's contract three times. Roll costs and the small daily cost of holding the position are included.
- A Bund future moves about €97 per bp and an OAT future about €88. With 3 against 3 you are therefore slightly "long German bonds", which helps a little if all rates fall.

### 2.2 Results

Profit or loss, with **€7,956 at risk** (the 30 bp stop):

| Spread peaks at | Average | Median | Bad case (1 in 10) | Good case (1 in 10) | Stopped out |
|---|---|---|---|---|---|
| 200 bp | +€5,900 | +€12,100 | −€9,100 | +€14,800 | 33% |
| 250 bp | +€15,000 | +€25,400 | −€9,000 | +€28,000 | 32% |
| 300 bp | +€24,000 | +€38,700 | −€9,000 | +€41,300 | 32% |
| 350 bp | +€33,000 | +€51,900 | −€9,000 | +€54,500 | 32% |
| No event | −€3,700 | −€8,500 | −€9,500 | +€8,900 | 61% |

**The main weakness: even when you are right, one time in three you get stopped out.** The spread dips 30 bp before the scare arrives, you are out, and the plan does not re-enter. When you are not stopped, the gain is close to the full move: €265 times the bp gained, minus costs.

**Earlier is better.** At 300 bp, a scare in the first third of the period averages 5.6 times the amount at risk, against 2.7 times for a late one, because a late scare leaves more months for the stop to be hit and more holding costs.

**Why a 30 bp stop and not a wider one?**

| Stop | Amount at risk | Average at 300 bp | Stopped out at 300 bp | Expected value with our odds |
|---|---|---|---|---|
| 30 bp | €7,956 | 4.0 times risk | 32% | +50% |
| 40 bp | €10,608 | 3.7 times risk | 21% | +47% |
| 50 bp | €13,260 | 3.4 times risk | 13% | +43% |
| 60 bp | €15,912 | 3.2 times risk | 8% | +39% |

A tighter stop gives the best return per euro risked but gets hit more often. A wider stop is calmer but puts more money at risk. Choose the one whose loss you can live with.

### 2.3 Odds

| Scenario | Probability | Average result |
|---|---|---|
| Relief or grind ("no event") | 65% | −€3,700 |
| Stress (200 to 300 bp) | 30% | +€15,000 |
| Contested (above 300 bp) | 5% | +€37,500 |
| **Expected value** | | **+€4,000 (+50% of the €7,956 at risk)** |

The chance of losing about the full stop amount is about **51%**. The "relief" scenario (spread falls to 85 bp) is treated here like "no event". In reality it would hit the stop almost every time, so this expected value is a little optimistic.

### 2.4 How the trade works

- A bond future rises when that country's interest rates fall and falls when they rise.
- Selling the French future earns money when French rates rise. Buying the German future earns money when German rates fall.
- Together the position earns money whenever the French rate rises **relative to** the German rate, i.e. when the spread widens. That is the thesis, in its purest form.
- Futures are not paid for up front, but your broker blocks **margin** as a deposit. The guide figure is about **€3,250 per OAT contract and €2,360 per Bund contract**, so roughly €16,800 for this position (often less with a spread discount).
  - Keep at least €25,000 in the account: margin plus room for the stop-loss.
  - Margin can rise sharply in a crisis.
- Futures have no premium to lose, but losses are **not capped** by the contract. Only your stop protects you.

### 2.5 Step-by-step instructions

**What to trade (Eurex):**

| | French leg | German leg |
|---|---|---|
| Product | Euro-OAT Futures | Euro-Bund Futures |
| Eurex code | FOAT | FGBL |
| Product ISIN | DE000A1MAPW3 | DE0009652644 |
| Bloomberg | OATA Comdty | RXA Comdty |
| Contract | €100,000 notional French government bond, 8.5 to 10.5 years | €100,000 notional German government bond, 8.5 to 10.5 years |
| Price step | 0.01 = €10 | 0.01 = €10 |
| Eurex page | [FOAT](https://www.eurex.com/ex-en/markets/int/long-term-interest-rates/fix/government-bonds/Euro-OAT-Futures-137416) | [FGBL](https://www.eurex.com/ex-en/markets/int/long-term-interest-rates/fix/government-bonds/Euro-Bund-Futures-137298) |

**Opening (one day, as close to the same minute as possible):**

| Order | Contract | Quantity | Reference price (settlement 12 Oct 2026) |
|---|---|---|---|
| Sell to open | FOAT **Dec 2026** | 3 | 108.64 |
| Buy to open | FGBL **Dec 2026** | 3 | 120.96 |

Use limit orders at or near the current price. Right after the fills, **write down the spread** (French 10-year minus German 10-year yield) at that moment, for example 141 bp. Your stop level is that number minus 30, for example 111 bp.

**Every evening (2 minutes):**

1. Check the closing French and German 10-year yields (CNBC FR10Y and DE10Y, or your broker).
2. **Stop:** if the spread closes at or below your stop level, close both legs the next morning: buy back the 3 FOAT and sell the 3 FGBL.
3. **Take profit:** if the spread closes at or above your target (for example 300 bp), close both legs the same way.

A practical backup: the position moves about €265 per bp, so a broker alert on an open loss of about €8,000 marks the same point. Futures do not track the 10-year yields perfectly, so the two triggers can differ by a few bp.

**Quarterly rolls (2 orders each, as calendar-spread orders if your broker offers them):**

| Roll in the week before | From | To | Last trading day of the old contract |
|---|---|---|---|
| Early December 2026 | Dec 2026 | Mar 2027 | Tue 8 Dec 2026 |
| Early March 2027 | Mar 2027 | Jun 2027 | Mon 8 Mar 2027 |
| Early June 2027 | Jun 2027 | Sep 2027 | Tue 8 Jun 2027 |

Never hold a contract into its last trading day. Rolling is part of the plan; it does not change the stop level.

**Final exit:** close both legs by 1 July 2027 at the latest if neither the stop nor the target has been hit.

**Order count:** 2 to open, 2 per roll (6 in total), 2 to close.

---

## Trade 3: Société Générale put spread, June 2027

### 3.1 Trade idea and assumptions

**Idea.** French banks hold a lot of French government bonds and fall hard when France is in trouble. Buy a "put spread" on **Société Générale** shares: it pays if the share falls below €56 by June 2027, and pays the most if it falls to €40 or lower. Open once, hold, close once.

**Why Société Générale?** We compared BNP Paribas, Société Générale, Crédit Agricole and a European bank index fund on five things:

1. How much the share fell when the spread widened.
2. How deep it fell in the 2011 crisis, the 2024 snap election and the 2026 stress.
3. How much it moves for its own reasons rather than with France.
4. How many of its options have both buyers and sellers quoting.
5. How expensive its options are.

Société Générale came first on the most important points:

- It falls about **0.39% per bp** of spread widening, the most of the four.
- Its average stress drawdown was the deepest: −65% in 2011, −25% in 2024, −23% in 2026.
- It has the most actively quoted options.

Against it: its options are the most expensive relative to how much the share actually moves, and it has the most company-specific noise. Crédit Agricole was a close second. The weighting of the five points is our judgement, not a precise formula. The link between the spread and the share price is also loose: the spread explains only about 15% of Société Générale's daily moves.

**Why strikes 56 and 40, and June 2027?**

- We used a common shape for this kind of trade: buy a put about 10% to 15% below today's price, sell one about 35% to 40% below, and choose the longest expiry available.
- With the share at €64.11, 12% below is €56.42 and 37% below is €40.39. The nearest listed strikes are **56 and 40**.
- **18 June 2027** is the last expiry listed. It covers almost the whole period of the view.
- We did not fine-tune the strikes.

**Assumptions specific to this trade:**

- The model moves the share price with the spread (about −0.39% per bp) plus the share's own random swings.
- At 200 bp a typical modelled price is around €51 (−20%), at 250 bp around €42, and at 300 bp around €35 (−46%). That is a heavy fall, but milder than 2011.
- Option prices use Société Générale's real implied volatility of about 37%.
- You pay the asking price for the 56 put and receive the bid for the 40 put. You sell when the spread peaks, or the spread expires in June 2027.

### 3.2 Results

Money back on a €10,000 stake (28 put spreads cost about €9,770 including fees; the rest stays in cash):

| Spread peaks at | Average | Median | Bad case (1 in 10) | Good case (1 in 10) | Lose most |
|---|---|---|---|---|---|
| 200 bp | €20,000 | €21,000 | €4,500 | €32,200 | 7% |
| 250 bp | €27,900 | €28,900 | €18,300 | €36,900 | 2% |
| 300 bp | €32,900 | €33,200 | €26,800 | €40,400 | 1% |
| 350 bp | €36,500 | €36,500 | €32,300 | €42,100 | under 1% |
| No event | €8,500 | €100 | €100 | €37,200 | 67% |

**The ceiling.** The most this trade can ever pay is €16 per share, i.e. 28 × 100 × €16 = €44,800, about 4.5 times the stake. That is why the results flatten above 300 bp. In return it is the most reliable of the three when the scare comes: even at 200 bp it roughly doubles the money.

**Without a French scare** the median is a total loss. The average is still €8,500 because Société Générale sometimes falls on its own (bank-specific news, a general market fall). In that case the trade pays even though France is calm.

### 3.3 Odds

| Scenario | Probability | Average money back |
|---|---|---|
| Relief or grind ("no event") | 65% | €8,500 |
| Stress (200 to 300 bp) | 30% | €26,900 |
| Contested (above 300 bp) | 5% | €37,700 |
| **Expected value** | | **€15,500 (+55%)** |

The chance of losing 90% or more of the stake is about **45%**.

### 3.4 How the trade works

- **Buying the 56 put** gives you the right to sell 100 Société Générale shares at €56 until June 2027. It gains value as the share falls.
- **Selling the 40 put** gives someone else that right at €40. You collect money for it, which makes the trade cheaper, but you give up any gain below €40.
- **The cost:**
  - You pay €4.26 per share for the 56 put and receive €0.82 for the 40 put, a net **€3.44 per share**.
  - One contract covers 100 shares, so one put spread costs **€344**.
- **The payout:**
  - Nothing if the share is above €56 at expiry.
  - €1 per share for every euro below €56.
  - At most **€16 per share (€1,600 per spread)** at €40 or below.
- You can sell the spread any time before June. In a sharp fall it is often worth close to its maximum well before expiry.

### 3.5 Step-by-step instructions

**What to trade:**

| | |
|---|---|
| Share | Société Générale (Euronext Paris), ISIN **FR0000130809**, ticker GLE (Bloomberg GLE FP, Yahoo GLE.PA) |
| Options | Eurex Société Générale options, product code **SGE**; 1 contract = 100 shares; price step €0.01 |
| Eurex page | [Société Générale options](https://www.eurex.com/ex-en/markets/equ/equ-opt/options/Soci-t-G-n-rale-945950) |
| Alternative | Euronext Paris also lists Société Générale options (product GL1). Our prices are from Eurex |
| Exercise | Physical delivery of shares. Check with your broker whether the series is American or European style |

**Opening (one order, now):**

| Order | Legs | Quantity | Limit (net debit) | Quotes on 13 Oct |
|---|---|---|---|---|
| Buy put spread (combo / vertical spread order) | Buy SGE **Jun 2027** 56 put; sell SGE **Jun 2027** 40 put (expiry Fri 18 Jun 2027) | 28 | Start at **3.10**, raise slowly, **3.44 at most** | 56 put: bid 3.65, ask 4.26 (1,537 open); 40 put: bid 0.82, ask 1.09 (312 open) |

Enter it as **one combined order**, so both legs fill together. If your broker cannot do that, buy the 56 puts first, then sell the 40 puts straight away. The midpoint is about €3.00, so you may well get filled below €3.44.

**While it runs:** nothing to do. No stop is needed, because the most you can lose is what you paid.

**Closing (one order):**

- When the spread reaches your target, or Société Générale trades near or below €40, **sell the put spread** as a combo order (sell the 56 put, buy back the 40 put).
- **Close before expiry.** If you let it expire in the money, exercise would deliver shares into or out of your account.
- If nothing has happened by June 2027 and the share is well above €56, you can let it expire worthless.

**Order count:** 1 to open, 1 to close.

---

## Common risks and limits

- **This is a model, not a forecast.** The odds are personal guesses. The spread levels are scenarios, not predictions.
- **Selling at the top is assumed.** Real exits will be earlier or later than the peak.
- **Trade 1 depends on German yields falling** in a French scare, and on option prices rising in a panic. If either fails, its results drop sharply.
- **Trade 2 can lose more than the stop** on a gap day, needs margin, and margin can rise in a crisis.
- **Trade 3's link to France is loose.** Bank shares fall for many reasons, and a French scare that spares the banks would hurt this trade.
- **Prices are from 13 October 2026.** Re-check every price, strike and expiry date before you trade. If prices have moved a lot, the sizes and results above no longer apply.
- **Fees:** we assumed €2.50 per option contract and €2 per futures contract. Your broker may charge more.

*Source: France sovereign-stress study v7, snapshot 2026-10-13T1010, 10,000 simulated paths per scenario. Full technical results in `RESULTS_V7.md`.*
