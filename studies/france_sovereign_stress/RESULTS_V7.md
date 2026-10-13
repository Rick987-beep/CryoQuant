# RESULTS — france_sovereign_stress (v7 low-ops / convex)

Snapshot `2026-10-13T1010` · entry spread **140.72 bp** (quote 2026-10-13T10:10:10.000+0200) · budget €10,000 · n=10000 · seed=11 · common random numbers.

Exit levels simulated: **200 / 250 / 300 / 350 / 400 bp** (base case **300 bp**).

## Design

Same v6 world model (driftless walk → 15-business-day jump to the target level, random timing, Bund flight). Structures are low-touch: **no pyramid**. Option entry at live Eurex ask/bid; rolls/exits at model mid ± observed half-spread. Swissquote Eurex options fee assumed €2.50/contract/side (published tariff not confirmed live; sensitivity in RESULTS).

### Vol grounding

- Fit realised 21d spread σ on level + Δlevel: R²=0.372, use_level=True, max_obs_mult=2.91, base σ=3.20 bp/day, n=733.
- Episodes: {"euro_crisis_2011": {"n": 12, "sig_mean": 3.991671294534836, "sig_max": 9.319269181344096, "level_mean": 114.03964250217109, "level_max": 153.590909090909, "source": "fred_monthly"}, "france_snap_2024": {"n": 3, "sig_mean": 1.7994364237187221, "sig_max": 1.9657934381252586, "level_mean": 69.31706192333333, "level_max": 73.22727272999998, "source": "fred_monthly"}, "france_stress_2026": {"n": 39, "sig_mean": 2.241777278976246, "sig_max": 5.668308011592679, "level_mean": 103.8576923076923, "level_max": 142.27000000000004}, "fred_monthly": {"n": 233, "sig_mean": 1.1604283954225552, "sig_max": 9.319269181344096}}
- Flat-IV sensitivity (multiplier = 1) reported on the top option structures.

## Subjective scenario odds (secondary ranking only)

`{'relief': 0.15, 'grind': 0.5, 'stress': 0.3, 'contested': 0.05}` — relief+grind → wrong world; stress → mean(200,250,300); contested → mean(350,400).

## How to read the tables

- **Multiple (×)**: money at the end divided by the money put at risk (€10k unless stated). 1.0× = break-even, 0× = all lost.
- **Mean / Median**: average and middle outcome over 10,000 simulated paths in which the spread reaches the given level by mid-2027.
- **Lost**: share of those paths that end at 0.1× or less.
- **Wrong mean**: average outcome if no stress event happens (spread drifts sideways until 1 Jul 2027).
- **Odds EV**: average weighted by your subjective scenario odds (secondary ranking only).
- Each structure is explained in one line under “What each structure is” below the tables.

## Comparison @ 300 bp (primary / base case)

| Structure | Kind | Mean | Median | Lost | Wrong mean | Odds EV |
|-----------|------|-----:|-------:|-----:|-----------:|--------:|
| v6_ladder_40_20 | bookend | 11.37× | 14.78× | 25.0% | 0.50× | 3.22× |
| OGBL 125.5 call | option_roll | 7.08× | 3.37× | 0.0% | 0.40× | 2.25× |
| OGBL 125.5 call [front] | option_front | 4.78× | -0.03× | 87.9% | 0.19× | 1.39× |
| 50/50 OOAT 103 put + OGBL 125.5 call | option_pair | 4.56× | 2.78× | 0.0% | 0.24× | 1.45× |
| OGBL 124.5 call | option_roll | 4.56× | 2.87× | 0.0% | 0.49× | 1.63× |
| fixed 3/3 stop 30 | fixed_spread | 4.02× | 5.86× | 32.2% | 0.54× | 1.50× |
| OGBL 125.5/128.5 call spread | option_roll | 3.95× | 2.50× | 0.0% | 0.46× | 1.44× |
| OGBL 124 call | option_roll | 3.80× | 2.66× | 0.0% | 0.54× | 1.46× |
| OGBL 125.5 call [flat IV] | option_roll_flat_iv | 3.74× | 2.57× | 0.2% | 0.29× | 1.23× |
| v6_stop_only | bookend | 3.71× | 4.68× | 21.2% | 0.60× | 1.47× |
| fixed 3/3 stop 40 | fixed_spread | 3.71× | 4.68× | 21.2% | 0.60× | 1.47× |
| fixed 3/3 stop 50 | fixed_spread | 3.43× | 3.96× | 13.4% | 0.65× | 1.43× |
| OGBL 125.5/127.5 call spread | option_roll | 3.39× | 2.36× | 0.0% | 0.48× | 1.30× |
| GLE 56/40 put spread | bank_put_spread | 3.29× | 3.32× | 1.1% | 0.85× | 1.55× |
| OGBL 123.5 call | option_roll | 3.25× | 2.46× | 0.0% | 0.60× | 1.35× |
| fixed 3/3 stop 60 | fixed_spread | 3.18× | 3.47× | 8.2% | 0.69× | 1.39× |
| OGBL 125.5/128.5 call spread [flat IV] | option_roll_flat_iv | 2.99× | 2.81× | 0.2% | 0.35× | 1.05× |
| OGBL 124.5 call [flat IV] | option_roll_flat_iv | 2.96× | 2.43× | 0.1% | 0.40× | 1.10× |
| naked FOAT 3c stop 40 / tp 160 | naked_foat | 2.18× | 2.73× | 38.5% | 0.62× | 1.05× |
| short GLE stop 12% | bank_stock | 2.15× | 3.81× | 48.5% | 0.23× | 0.78× |
| naked FOAT 4c stop 30 / tp 120 | naked_foat | 2.11× | 2.20× | 49.0% | 0.57× | 0.99× |
| OOAT 103 put | option_roll | 2.04× | 1.56× | 0.0% | 0.08× | 0.66× |
| naked FOAT 2c stop 50 / tp 200 | naked_foat | 1.93× | 2.32× | 30.2% | 0.72× | 1.06× |

## Mean multiples by exit level

| Structure | 200 bp | 250 bp | 300 bp | 350 bp | 400 bp | Wrong |
|-----------|-----:|-----:|-----:|-----:|-----:|------:|
| v6_ladder_40_20 | 1.91× | 5.17× | 11.37× | 17.84× | 24.28× | 0.50× |
| OGBL 125.5 call | 2.57× | 4.82× | 7.08× | 9.52× | 12.11× | 0.40× |
| OGBL 125.5 call [front] | 0.89× | 2.55× | 4.78× | 7.38× | 10.16× | 0.19× |
| 50/50 OOAT 103 put + OGBL 125.5 call | 1.79× | 3.18× | 4.56× | 6.08× | 7.74× | 0.24× |
| OGBL 124.5 call | 1.96× | 3.28× | 4.56× | 5.89× | 7.27× | 0.49× |
| fixed 3/3 stop 30 | 1.74× | 2.88× | 4.02× | 5.15× | 6.28× | 0.54× |
| OGBL 125.5/128.5 call spread | 1.99× | 3.01× | 3.95× | 4.67× | 5.13× | 0.46× |
| OGBL 124 call | 1.78× | 2.81× | 3.80× | 4.81× | 5.85× | 0.54× |
| OGBL 125.5 call [flat IV] | 1.19× | 2.21× | 3.74× | 5.55× | 7.49× | 0.29× |
| v6_stop_only | 1.73× | 2.72× | 3.71× | 4.69× | 5.68× | 0.60× |
| fixed 3/3 stop 40 | 1.73× | 2.72× | 3.71× | 4.69× | 5.68× | 0.60× |
| fixed 3/3 stop 50 | 1.70× | 2.57× | 3.43× | 4.30× | 5.17× | 0.65× |
| OGBL 125.5/127.5 call spread | 1.83× | 2.66× | 3.39× | 3.92× | 4.25× | 0.48× |
| GLE 56/40 put spread | 2.00× | 2.79× | 3.29× | 3.65× | 3.89× | 0.85× |
| OGBL 123.5 call | 1.65× | 2.48× | 3.25× | 4.03× | 4.82× | 0.60× |
| fixed 3/3 stop 60 | 1.65× | 2.42× | 3.18× | 3.95× | 4.71× | 0.69× |
| OGBL 125.5/128.5 call spread [flat IV] | 1.24× | 2.10× | 2.99× | 3.63× | 4.05× | 0.35× |
| OGBL 124.5 call [flat IV] | 1.20× | 1.96× | 2.96× | 4.08× | 5.25× | 0.40× |
| naked FOAT 3c stop 40 / tp 160 | 1.22× | 1.71× | 2.18× | 2.56× | 2.81× | 0.62× |
| short GLE stop 12% | 1.11× | 1.68× | 2.15× | 2.53× | 2.85× | 0.23× |
| naked FOAT 4c stop 30 / tp 120 | 1.20× | 1.71× | 2.11× | 2.34× | 2.45× | 0.57× |
| OOAT 103 put | 1.02× | 1.55× | 2.04× | 2.64× | 3.36× | 0.08× |
| naked FOAT 2c stop 50 / tp 200 | 1.19× | 1.57× | 1.93× | 2.29× | 2.59× | 0.72× |

## What each structure is

- **v6_ladder_40_20**: The v6 primary book, kept as a reference: short Euro-OAT futures / long Euro-Bund futures (the OAT–Bund spread trade), €10k at risk, stop 40 bp below the last add, and the position is increased every time the spread widens another 20 bp. Many orders; not a v7 candidate.
- **OGBL 125.5 call**: Buy call options on the Euro-Bund future (Germany) at strike 125.5, expiring 20/11/2026. The first strike is 4.2 points above the future (121.31), i.e. about 43 bp of German 10y yield fall. About every 8 weeks the position is rolled into the next expiry at the same distance from the market, until mid-2027; the €10k premium budget is split across those rolls in proportion to their length. Sold when the stress event completes.
- **OGBL 125.5 call [front]**: Same option, but the whole €10k is spent on the 20/11/2026 expiry and never rolled. Expires worthless if the stress comes after that date.
- **50/50 OOAT 103 put + OGBL 125.5 call**: Half the budget in the “OOAT 103 put” trade (France) and half in the “OGBL 125.5 call” trade (Germany), both with the same 8-week rolls.
- **OGBL 124.5 call**: Buy call options on the Euro-Bund future (Germany) at strike 124.5, expiring 20/11/2026. The first strike is 3.2 points above the future (121.31), i.e. about 32 bp of German 10y yield fall. About every 8 weeks the position is rolled into the next expiry at the same distance from the market, until mid-2027; the €10k premium budget is split across those rolls in proportion to their length. Sold when the stress event completes.
- **fixed 3/3 stop 30**: Short 3 Euro-OAT futures and long 3 Euro-Bund futures (the spread trade), opened once and never added to. Closed if the spread narrows 30 bp below entry (checked at the daily close), otherwise held until the event completes. Futures rolled quarterly. Multiples are measured against the money lost if stopped: €7,956.
- **OGBL 125.5/128.5 call spread**: Buy the 125.5 call and sell the 128.5 call on the Euro-Bund future (Germany), both expiring 20/11/2026; cheaper than the single option, but the payout stops growing beyond 128.5. The first strike is 4.2 points above the future (121.31), i.e. about 43 bp of German 10y yield fall. About every 8 weeks the position is rolled into the next expiry at the same distance from the market, until mid-2027; the €10k premium budget is split across those rolls in proportion to their length. Sold when the stress event completes.
- **OGBL 124 call**: Buy call options on the Euro-Bund future (Germany) at strike 124, expiring 20/11/2026. The first strike is 2.7 points above the future (121.31), i.e. about 27 bp of German 10y yield fall. About every 8 weeks the position is rolled into the next expiry at the same distance from the market, until mid-2027; the €10k premium budget is split across those rolls in proportion to their length. Sold when the stress event completes.
- **OGBL 125.5 call [flat IV]**: Same option trade as the line without “[flat IV]”, but rolls and exits are priced with today's implied volatility unchanged, instead of letting volatility rise with the spread as fitted on history. This is the conservative version.
- **v6_stop_only**: Same spread trade sized so a 40 bp move against it loses €10k, opened once with a stop and never added to.
- **fixed 3/3 stop 40**: Short 3 Euro-OAT futures and long 3 Euro-Bund futures (the spread trade), opened once and never added to. Closed if the spread narrows 40 bp below entry (checked at the daily close), otherwise held until the event completes. Futures rolled quarterly. Multiples are measured against the money lost if stopped: €10,608.
- **fixed 3/3 stop 50**: Short 3 Euro-OAT futures and long 3 Euro-Bund futures (the spread trade), opened once and never added to. Closed if the spread narrows 50 bp below entry (checked at the daily close), otherwise held until the event completes. Futures rolled quarterly. Multiples are measured against the money lost if stopped: €13,260.
- **OGBL 125.5/127.5 call spread**: Buy the 125.5 call and sell the 127.5 call on the Euro-Bund future (Germany), both expiring 20/11/2026; cheaper than the single option, but the payout stops growing beyond 127.5. The first strike is 4.2 points above the future (121.31), i.e. about 43 bp of German 10y yield fall. About every 8 weeks the position is rolled into the next expiry at the same distance from the market, until mid-2027; the €10k premium budget is split across those rolls in proportion to their length. Sold when the stress event completes.
- **GLE 56/40 put spread**: Buy Société Générale 56 puts and sell 40 puts (Eurex), expiring 18/06/2027, opened once and held. Share price 64.11; pays from 56 down to 40, maximum 16 per share against a 3.44 cost. Loss is limited to the premium.
- **OGBL 123.5 call**: Buy call options on the Euro-Bund future (Germany) at strike 123.5, expiring 20/11/2026. The first strike is 2.2 points above the future (121.31), i.e. about 22 bp of German 10y yield fall. About every 8 weeks the position is rolled into the next expiry at the same distance from the market, until mid-2027; the €10k premium budget is split across those rolls in proportion to their length. Sold when the stress event completes.
- **fixed 3/3 stop 60**: Short 3 Euro-OAT futures and long 3 Euro-Bund futures (the spread trade), opened once and never added to. Closed if the spread narrows 60 bp below entry (checked at the daily close), otherwise held until the event completes. Futures rolled quarterly. Multiples are measured against the money lost if stopped: €15,912.
- **OGBL 125.5/128.5 call spread [flat IV]**: Same option trade as the line without “[flat IV]”, but rolls and exits are priced with today's implied volatility unchanged, instead of letting volatility rise with the spread as fitted on history. This is the conservative version.
- **OGBL 124.5 call [flat IV]**: Same option trade as the line without “[flat IV]”, but rolls and exits are priced with today's implied volatility unchanged, instead of letting volatility rise with the spread as fitted on history. This is the conservative version.
- **naked FOAT 3c stop 40 / tp 160**: Short 3 Euro-OAT futures with no Bund hedge, so it bets on the French 10y yield itself rising. Closed at a loss if that yield falls 40 bp from entry, or at a profit if it rises 160 bp (both checked at the daily close). Stop risk ≈ €10,608.
- **short GLE stop 12%**: Short Société Générale shares (€83,333) sized so a 12% rise stops the trade out for about €10k. Pays borrow cost and the 0.4% French transaction tax when buying back.
- **naked FOAT 4c stop 30 / tp 120**: Short 4 Euro-OAT futures with no Bund hedge, so it bets on the French 10y yield itself rising. Closed at a loss if that yield falls 30 bp from entry, or at a profit if it rises 120 bp (both checked at the daily close). Stop risk ≈ €10,608.
- **OOAT 103 put**: Buy put options on the Euro-OAT future (France) at strike 103, expiring 20/11/2026. The first strike is 6.1 points below the future (109.14), i.e. about 70 bp of French 10y yield rise. About every 8 weeks the position is rolled into the next expiry at the same distance from the market, until mid-2027; the €10k premium budget is split across those rolls in proportion to their length. Sold when the stress event completes.
- **naked FOAT 2c stop 50 / tp 200**: Short 2 Euro-OAT futures with no Bund hedge, so it bets on the French 10y yield itself rising. Closed at a loss if that yield falls 50 bp from entry, or at a profit if it rises 200 bp (both checked at the daily close). Stop risk ≈ €8,840.

## Bank pick

| Bank | Score | β_spread | Mean episode DD | Two-sided opts | IV/RV | Notes |
|------|------:|---------:|----------------:|---------------:|------:|-------|
| GLE | 6.42 | -0.00388 | -37.7% | 61 | 1.35 | puts rich vs realised (IV/RV=1.35) |
| ACA | 6.09 | -0.00262 | -36.3% | 55 | 1.26 | — |
| BNP | 5.64 | -0.00342 | -29.9% | 55 | 1.33 | puts rich vs realised (IV/RV=1.33) |
| EXV1 | 2.76 | -0.00282 | -19.6% | 0 | — | no two-sided Eurex equity option quotes in snapshot |

Columns: **β_spread** = daily share-price move per 1 bp of OAT–Bund widening (−0.0039 ≈ −0.39% per bp), from a regression on two years of daily data; **Mean episode DD** = average worst fall in the 2011 euro crisis, the June 2024 French snap election and the Aug–Oct 2026 stress; **Two-sided opts** = Eurex option strikes with both a bid and an ask; **IV/RV** = option implied vol divided by recent realised vol (above 1 means puts are expensive).

Score = β term + drawdown term − idiosyncratic-vol term + liquidity term − expensive-puts term. The weights are a judgement call, not fitted.

**Pick: GLE** (GLE.PA). It has the largest share-price sensitivity to the spread (β -0.0039) and the deepest stress drawdowns on average (2011 -65%, 2024 -25%, 2026 -23%), and the most quoted option strikes. Against it: its puts are the most expensive relative to realised vol, and it has the most bank-specific noise. Crédit Agricole is a close second with cheaper puts but a weaker spread link.

### Suggested bank put spread (live snapshot)

- Buy GLE 56 put / sell 40 put, expiry 18/06/2027 (spot 64.11).
- Live debit ≈ **3.44** pts (ask−bid crossed); half-spread ≈ 0.44; ATM IV ≈ 37.4%.
- **Why these strikes:** the shape comes from the research note (long put about 10–15% below the share price, short put about 35–40% below, longest listed expiry). The code targets 12% and 37% below 64.11 (56.42 and 40.39) and snaps to the nearest listed strikes, 56 and 40. 18/06/2027 is the last Eurex expiry in the snapshot. The strikes were not optimised.
- Maximum payout is 16 per share for a 3.44 cost (≈4.7× before fees), which is why the multiple flattens above 300 bp.


## Concrete trade suggestions

### 1. OGBL 125.5 call

- @300 (base) mean **7.08×**, subjective odds EV **2.25×**.
- Means by level: 200=2.57×, 250=4.82×, 300=7.08×, 350=9.52×, 400=12.11×.
- Detail: `{"front": "20/11/2026", "fwd": 121.315, "points_per_bp": 0.09819465259364861, "live_cost": 0.07, "unit0_eur": 72.5, "n_entry": 137.0, "cadence_months": 2, "n_tranches": 5, "half_spread": 0.0050000000000000044, "fee_eur": 2.5, "vol_fit_use_level": "True", "structure": "OGBL 125.5 call", "legs": ["Buy 1 OGBL 125.5 call"]}`
- Weakness: Roll decay if stress arrives late; OTM OGBL calls are cheap but wrong-world premium burn is large; payout depends on Bund flight.

### 2. fixed 3/3 stop 30

- @300 (base) mean **4.02×**, subjective odds EV **1.50×**.
- Means by level: 200=1.74×, 250=2.88×, 300=4.02×, 350=5.15×, 400=6.28×.
- Detail: `{"foat_n": 3, "fgbl_n": 3, "stop_bp": 30.0, "eur_per_bp": 88.4016452818487, "stop_risk_eur": 7956.148075366384, "tcost_bp": 0.1509910128299188, "execution": "daily_close"}`
- Weakness: Linear in spread; no convexity. Stopout risk in wrong world ~like stop_only.

### 3. GLE 56/40 put spread

- @300 (base) mean **3.29×**, subjective odds EV **1.55×**.
- Means by level: 200=2.00×, 250=2.79×, 300=3.29×, 350=3.65×, 400=3.89×.
- Detail: `{"spot": 64.11000061035156, "long_k": 56.0, "short_k": 40.0, "expiry": "2027-06-18", "live_debit": 3.44, "n": 28.0, "unit_eur": 349.0, "atm_iv": 0.3741509284001351, "half_spread": 0.44, "bank": "GLE", "suggestion": {"code": "GLE", "expiry": "18/06/2027", "expiry_date": "2027-06-18", "spot": 64.11000061035156, "k_long": 56.0, "k_short": 40.0, "live_debit": 3.44, "half_spread": 0.44, "atm_iv": 0.3741509284001351, "fwd": 65.8625, "settle_flagged_short": false, "long_ask": 4.26, "short_bid": 0.82}}`
- Weakness: Bank beta to the OAT–Bund spread is noisy; idiosyncratic bank news can dominate.

## Notes

- Broker choice / order frequency are out of scope; fills always cross the bid/ask.
- Swissquote options fee assumed €2.50/contract/side (tariff not confirmed live).
- Machine-readable: `data/v7_evaluate.json`.
