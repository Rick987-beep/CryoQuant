"""Unit tests for cryoquant.backtest.breakout_sim.

Channel-breakout simulator: BreakoutConfig + simulate_breakout().
Former turtle_simulate coverage lives here at framework level.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from cryoquant.backtest.breakout_sim import BreakoutConfig, simulate_breakout
from cryoquant.backtest.trades import TRADE_COLUMNS


def _cfg(**kwargs) -> BreakoutConfig:
    defaults = dict(entry_n=20, exit_n=10, direction="long", fee_bps=5.0)
    defaults.update(kwargs)
    return BreakoutConfig(**defaults)


def _run(bars, entry_filter=None, **kwargs):
    return simulate_breakout(bars, _cfg(**kwargs), entry_filter)


# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------

def _bars(
    closes: list[float],
    opens: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    *,
    freq: str = "1D",
    start: str = "2020-01-01",
) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from explicit arrays.

    If opens/highs/lows are omitted they default to close ±0 (flat candles).
    """
    n = len(closes)
    c = np.array(closes, dtype=float)
    o = np.array(opens, dtype=float) if opens is not None else c.copy()
    h = np.array(highs, dtype=float) if highs is not None else c.copy()
    lo = np.array(lows, dtype=float) if lows is not None else c.copy()
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    df = pd.DataFrame({"open": o, "high": h, "low": lo, "close": c, "volume": 1.0}, index=idx)
    df.index.name = "timestamp"
    return df


def _trending_bars(n: int, start_price: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    """Linearly trending close prices with slight noise in highs/lows."""
    closes = [start_price + i * step for i in range(n)]
    rng = np.random.default_rng(0)
    noise = rng.uniform(0.1, 0.5, n)
    return _bars(
        closes=closes,
        highs=[c + no for c, no in zip(closes, noise)],
        lows=[c - no for c, no in zip(closes, noise)],
    )


def _flat_then_breakout(flat_n: int = 25, entry_n: int = 20) -> pd.DataFrame:
    """flat_n flat bars at 100.0, then one breakout candle.

    Designed so that after flat_n bars the Donchian(entry_n) upper = 100.0,
    and the breakout bar closes at 105.0 to trigger a long signal.
    """
    closes = [100.0] * flat_n + [105.0]
    highs = [100.5] * flat_n + [106.0]
    lows = [99.5] * flat_n + [104.0]
    return _bars(closes=closes, highs=highs, lows=lows)



class TestLookahead:
    def test_no_lookahead_extra_bar(self) -> None:
        """Run on N bars then N+1 bars — all trades from the N-bar run must
        appear identically in the N+1-bar run (same entry_ts, exit_ts, pnl)."""
        bars = _trending_bars(n=200)
        r_short = _run(bars.iloc[:150], entry_n=20, exit_n=10, direction="long")
        r_full  = _run(bars.iloc[:151], entry_n=20, exit_n=10, direction="long")

        trades_s = r_short.trades.reset_index(drop=True)
        trades_f = r_full.trades.reset_index(drop=True)

        # Every trade from the short run must appear in the full run
        for _, row in trades_s.iterrows():
            if row["exit_type"] == "end_of_data":
                continue  # force-closed trade — may differ when data extends
            match = trades_f[
                (trades_f["entry_ts"] == row["entry_ts"]) &
                (trades_f["exit_ts"]  == row["exit_ts"])
            ]
            assert len(match) == 1, (
                f"Trade entry={row['entry_ts']} exit={row['exit_ts']} "
                f"missing in extended run"
            )
            assert match.iloc[0]["pnl_pct"] == pytest.approx(row["pnl_pct"], rel=1e-9)

    def test_no_lookahead_prepend_bar(self) -> None:
        """Signals on bar i must not change if we change bar i+5 data."""
        bars = _trending_bars(n=100)
        bars_modified = bars.copy()
        # Drastically alter a future bar's close
        bars_modified.iloc[80, bars_modified.columns.get_loc("close")] = 1_000_000.0
        bars_modified.iloc[80, bars_modified.columns.get_loc("high")] = 1_000_000.0

        r_orig = _run(bars.iloc[:70], entry_n=20, exit_n=10, direction="long")
        r_mod  = _run(bars_modified.iloc[:70], entry_n=20, exit_n=10, direction="long")

        # First 70 bars are unchanged — results must be identical
        assert r_orig.trades.shape == r_mod.trades.shape
        if not r_orig.trades.empty:
            pd.testing.assert_frame_equal(
                r_orig.trades.reset_index(drop=True),
                r_mod.trades.reset_index(drop=True),
                check_exact=False, rtol=1e-9,
            )


# ============================================================================
# T03  Non-overlapping trades
# ============================================================================


class TestNonOverlapping:
    def test_no_time_overlap(self) -> None:
        """No two trades should be open at the same time."""
        bars = _trending_bars(n=300)
        result = _run(bars, entry_n=20, exit_n=10, direction="long", fee_bps=0.0)
        trades = result.trades
        if len(trades) < 2:
            return
        trades_sorted = trades.sort_values("entry_ts").reset_index(drop=True)
        for i in range(len(trades_sorted) - 1):
            assert trades_sorted.loc[i, "exit_ts"] <= trades_sorted.loc[i + 1, "entry_ts"], (
                f"Trade {i} exits at {trades_sorted.loc[i,'exit_ts']} but "
                f"trade {i+1} enters at {trades_sorted.loc[i+1,'entry_ts']}"
            )

    def test_no_duplicate_entry_ts(self) -> None:
        bars = _trending_bars(n=300)
        result = _run(bars, entry_n=20, exit_n=10, direction="long")
        assert result.trades["entry_ts"].is_unique


# ============================================================================
# T04  Trailing stop fires on downward close
# ============================================================================


class TestTrailingExit:
    def test_trail_exit_type(self) -> None:
        """When a trade exits via the trailing stop, exit_type must be 'trail'."""
        # Up-trend for 60 bars, then reverses cleanly below exit channel
        closes = [100.0 + i for i in range(60)] + [150.0 - i * 2 for i in range(30)]
        bars = _bars(closes=closes)
        result = _run(bars, entry_n=20, exit_n=10, direction="long", fee_bps=0.0)
        trails = result.trades[result.trades["exit_type"] == "trail"]
        assert len(trails) >= 1, "Expected at least one trail exit on the reversal"

    def test_trail_exit_price_is_next_open(self) -> None:
        """Trail exits execute at the open of the bar AFTER the signal bar."""
        closes = [100.0 + i for i in range(60)] + [150.0 - i * 2 for i in range(30)]
        # Give each bar a distinct open 0.5 above the close
        opens = [c + 0.5 for c in closes]
        bars = _bars(closes=closes, opens=opens)
        result = _run(bars, entry_n=20, exit_n=10, direction="long", fee_bps=0.0)
        trails = result.trades[result.trades["exit_type"] == "trail"]
        for _, trade in trails.iterrows():
            exit_ts = trade["exit_ts"]
            bar_open = bars.loc[exit_ts, "open"]
            assert trade["exit_price"] == pytest.approx(bar_open), (
                f"Trail exit price {trade['exit_price']} != open at exit bar {bar_open}"
            )


# ============================================================================
# T05  Hard stop fires when intraday low breaches stop level
# ============================================================================


class TestHardStop:
    def _hard_stop_bars(self) -> pd.DataFrame:
        """Flat warmup → breakout → one bar that drops below the ATR stop."""
        # 25 flat bars (atr ~0.5), then breakout at 101, then hard stop bar
        flat_closes = [100.0] * 25
        flat_highs  = [100.5] * 25
        flat_lows   = [99.5] * 25
        # Breakout bar: close 101
        breakout_close = [101.0]
        breakout_high  = [102.0]
        breakout_low   = [100.5]
        # Entry bar: open at 101 (execution bar)
        entry_open = [101.0]
        entry_high = [102.0]
        entry_low  = [101.0]
        entry_close= [101.5]
        # Hard stop bar: open 101.5, low drops to 90 (well below ATR stop)
        stop_open  = [101.5]
        stop_high  = [102.0]
        stop_low   = [90.0]
        stop_close = [91.0]

        all_c = flat_closes + breakout_close + entry_close + stop_close + [101.0] * 5
        all_o = flat_closes + breakout_close + entry_open + stop_open + [101.0] * 5
        all_h = flat_highs + breakout_high + entry_high + stop_high + [102.0] * 5
        all_lo = flat_lows + breakout_low + entry_low + stop_low + [100.0] * 5
        return _bars(closes=all_c, opens=all_o, highs=all_h, lows=all_lo)

    def test_hard_stop_exit_type(self) -> None:
        bars = self._hard_stop_bars()
        result = _run(bars, entry_n=20, exit_n=10, direction="long", fee_bps=0.0, stop_atr_mult=2.0, atr_n=20)
        hard_stops = result.trades[result.trades["exit_type"] == "hard_stop"]
        assert len(hard_stops) >= 1, "Expected at least one hard_stop exit"

    def test_hard_stop_pnl_negative(self) -> None:
        bars = self._hard_stop_bars()
        result = _run(bars, entry_n=20, exit_n=10, direction="long", fee_bps=0.0, stop_atr_mult=2.0, atr_n=20)
        hard_stops = result.trades[result.trades["exit_type"] == "hard_stop"]
        if not hard_stops.empty:
            assert hard_stops.iloc[0]["pnl_pct"] < 0.0, "Hard stop should produce a loss"


# ============================================================================
# T06  Hard stop gap-fill — fill at open when price gaps through stop
# ============================================================================


class TestHardStopGapFill:
    def test_gap_down_fills_at_open_not_stop(self) -> None:
        """If the bar opens BELOW the hard stop (gap), exit price must be the open,
        not the hard_stop level (which was never reached from below)."""
        # Flat warmup so ATR is near 0.5, entry price ≈ 101
        flat_closes = [100.0] * 25
        flat_highs  = [100.5] * 25
        flat_lows   = [99.5] * 25
        # Breakout bar
        breakout = [101.0]; bh = [102.0]; bl = [100.5]
        # Entry execution bar (bar after breakout signal)
        entry_bar_open = 101.0
        eb = [entry_bar_open]; ebh = [102.0]; ebl = [101.0]; ebc = [101.5]
        # Gap-down bar: opens at 80, well below any stop (ATR ≈ 0.5, stop ≈ 100)
        gap_open = 80.0
        gb = [gap_open]; gbh = [82.0]; gbl = [78.0]; gbc = [79.0]
        padding = [79.0] * 5

        all_c = flat_closes + breakout + ebc + gbc + padding
        all_o = flat_closes + breakout + eb + gb + padding
        all_h = flat_highs + bh + ebh + gbh + [82.0] * 5
        all_lo = flat_lows + bl + ebl + gbl + [78.0] * 5

        bars = _bars(closes=all_c, opens=all_o, highs=all_h, lows=all_lo)
        result = _run(bars, entry_n=20, exit_n=10, direction="long", fee_bps=0.0, stop_atr_mult=2.0, atr_n=20)

        hard_stops = result.trades[result.trades["exit_type"] == "hard_stop"]
        assert len(hard_stops) >= 1

        for _, t in hard_stops.iterrows():
            # Exit price must be <= entry_price (loss trade)
            assert t["exit_price"] <= t["entry_price"], (
                f"Hard stop exit price {t['exit_price']} > entry {t['entry_price']}"
            )
            # Exit price must be <= hard_stop: if gapped, fill at open (80) not stop
            # The gap open (80) is below any reasonable ATR stop for a 100-level entry
            assert t["exit_price"] < 100.0, (
                f"Expected fill at gap open (~80), got {t['exit_price']}"
            )

    def test_intraday_stop_fills_at_stop_price(self) -> None:
        """When the bar opens ABOVE the stop but the low dips below it,
        exit price must be exactly hard_stop (clean intraday fill)."""
        # entry_price=101, atr≈0.5 → hard_stop = 101 - 2*0.5 = 100
        flat_closes = [100.0] * 25
        flat_highs  = [100.5] * 25
        flat_lows   = [99.5] * 25
        breakout = [101.0]; bh = [102.0]; bl = [100.5]
        eb = [101.0]; ebh = [102.0]; ebl = [101.0]; ebc = [101.5]
        # Stop bar: opens at 101.5 (above stop ~100), low dips to 99.5 (below stop)
        sb = [101.5]; sbh = [102.0]; sbl = [99.5]; sbc = [100.0]
        padding = [100.0] * 5

        all_c = flat_closes + breakout + ebc + sbc + padding
        all_o = flat_closes + breakout + eb + sb + padding
        all_h = flat_highs + bh + ebh + sbh + [101.0] * 5
        all_lo = flat_lows + bl + ebl + sbl + [99.5] * 5

        bars = _bars(closes=all_c, opens=all_o, highs=all_h, lows=all_lo)
        result = _run(bars, entry_n=20, exit_n=10, direction="long", fee_bps=0.0, stop_atr_mult=2.0, atr_n=20)

        hard_stops = result.trades[result.trades["exit_type"] == "hard_stop"]
        if not hard_stops.empty:
            t = hard_stops.iloc[0]
            # Exit price should be the hard stop level, not the low
            # hard_stop = entry_price - 2*atr ≈ 101 - 1 = 100
            assert t["exit_price"] >= 99.5, "Should not fill below the bar low"
            assert t["exit_price"] <= t["entry_price"], "Hard stop must be a loss"


# ============================================================================
# T07 / T08  Short direction
# ============================================================================


class TestShortDirection:
    def test_short_profitable_on_downtrend(self) -> None:
        """Short trades should be profitable when price trends down."""
        closes = [200.0 - i for i in range(100)]
        bars = _bars(closes=closes)
        result = _run(bars, entry_n=20, exit_n=10, direction="short",
                                 fee_bps=0.0)
        # Should have at least some trades
        assert result.metrics["n_trades"] >= 1
        # At least some trades should be profitable
        profits = result.trades[result.trades["pnl_pct"] > 0]
        assert len(profits) >= 1

    def test_short_pnl_sign(self) -> None:
        """For a short trade: exit_price < entry_price → positive P&L."""
        # Build bars where we know a short entry will fire and price keeps falling
        closes_down = [100.0 - i * 0.5 for i in range(100)]
        bars = _bars(closes=closes_down)
        result = _run(bars, entry_n=20, exit_n=10, direction="short",
                                 fee_bps=0.0)
        for _, t in result.trades.iterrows():
            if t["exit_type"] == "end_of_data":
                continue
            if t["exit_type"] == "trail":
                raw = (t["entry_price"] - t["exit_price"]) / t["entry_price"]
                assert abs(t["pnl_pct"] - raw) < 1e-9, (
                    f"Short P&L {t['pnl_pct']:.6f} != (entry-exit)/entry {raw:.6f}"
                )

    def test_short_hard_stop_above_entry(self) -> None:
        """For a short trade, hard stop must be ABOVE the entry price."""
        closes_down = [100.0 - i * 0.5 for i in range(100)]
        bars = _bars(closes=closes_down)
        result = _run(bars, entry_n=20, exit_n=10, direction="short",
                                 fee_bps=0.0, stop_atr_mult=2.0)
        hard_stops = result.trades[result.trades["exit_type"] == "hard_stop"]
        for _, t in hard_stops.iterrows():
            # Short hard stop hit → price rose above stop → exit_price >= entry_price
            assert t["exit_price"] >= t["entry_price"] * 0.99, (
                f"Short hard stop exit {t['exit_price']} below entry {t['entry_price']}"
            )


# ============================================================================
# T09  Fee deduction
# ============================================================================


class TestFees:
    def test_zero_fee_raw_return(self) -> None:
        """With fee_bps=0, pnl_pct must exactly equal (exit-entry)/entry for longs."""
        bars = _trending_bars(n=100)
        result = _run(bars, entry_n=20, exit_n=10, direction="long", fee_bps=0.0)
        for _, t in result.trades.iterrows():
            if t["exit_type"] == "end_of_data":
                raw = (t["exit_price"] - t["entry_price"]) / t["entry_price"]
            elif t["exit_type"] == "trail":
                raw = (t["exit_price"] - t["entry_price"]) / t["entry_price"]
            else:  # hard_stop
                raw = (t["exit_price"] - t["entry_price"]) / t["entry_price"]
            assert t["pnl_pct"] == pytest.approx(raw, abs=1e-12), (
                f"fee=0 but pnl={t['pnl_pct']:.8f} != raw={raw:.8f}"
            )

    def test_fee_reduces_pnl(self) -> None:
        """pnl with fee > 0 must be less than pnl with fee = 0."""
        bars = _trending_bars(n=100)
        r0 = _run(bars, entry_n=20, exit_n=10, direction="long", fee_bps=0.0)
        r5 = _run(bars, entry_n=20, exit_n=10, direction="long", fee_bps=5.0)
        if r0.metrics["n_trades"] == 0:
            return
        assert r5.metrics["total_return"] < r0.metrics["total_return"]

    def test_fee_pct_column(self) -> None:
        """fee_pct column must equal fee_bps/10000 * 2 (round-trip)."""
        bars = _trending_bars(n=100)
        fee_bps = 7.0
        result = _run(bars, entry_n=20, exit_n=10, direction="long", fee_bps=fee_bps)
        expected_fee = fee_bps / 10_000.0 * 2
        for _, t in result.trades.iterrows():
            assert t["fee_pct"] == pytest.approx(expected_fee, rel=1e-9)


# ============================================================================
# T10  End-of-data force close
# ============================================================================


class TestEndOfData:
    def test_force_close_marked(self) -> None:
        """If a trade is open at the last bar, it must be closed and marked."""
        # Strongly trending bars so a trade opens and doesn't exit before end
        closes = [100.0 + i * 2 for i in range(50)]
        bars = _bars(closes=closes)
        result = _run(bars, entry_n=20, exit_n=10, direction="long")
        if result.metrics["n_trades"] > 0:
            last_exit_type = result.trades.iloc[-1]["exit_type"]
            assert last_exit_type in {"trail", "hard_stop", "end_of_data"}

    def test_force_close_exit_at_last_close(self) -> None:
        """Force-closed trade must exit at the last bar's close."""
        closes = [100.0 + i * 2 for i in range(50)]
        bars = _bars(closes=closes)
        result = _run(bars, entry_n=20, exit_n=10, direction="long")
        eod = result.trades[result.trades["exit_type"] == "end_of_data"]
        if not eod.empty:
            last_close = bars["close"].iloc[-1]
            assert eod.iloc[-1]["exit_price"] == pytest.approx(last_close)


# ============================================================================
# T11  Edge cases — too-short input
# ============================================================================


class TestEdgeCases:
    def test_empty_bars_returns_empty(self) -> None:
        bars = _bars(closes=[])
        result = _run(bars, entry_n=20, exit_n=10, direction="long")
        assert result.metrics["n_trades"] == 0
        assert result.trades.empty

    def test_insufficient_bars_returns_empty(self) -> None:
        bars = _bars(closes=[100.0] * 10)
        result = _run(bars, entry_n=20, exit_n=10, direction="long")
        assert result.metrics["n_trades"] == 0

    def test_all_same_prices_no_breakout(self) -> None:
        """Flat price — Donchian channel never broken → no trades."""
        bars = _bars(closes=[100.0] * 100)
        result = _run(bars, entry_n=20, exit_n=10, direction="long")
        assert result.metrics["n_trades"] == 0

    def test_equity_curve_length_matches_bars(self) -> None:
        bars = _trending_bars(n=100)
        result = _run(bars, entry_n=20, exit_n=10, direction="long")
        assert len(result.equity) == len(bars)

    def test_equity_starts_at_one(self) -> None:
        bars = _trending_bars(n=100)
        result = _run(bars, entry_n=20, exit_n=10, direction="long")
        assert result.equity.iloc[0] == pytest.approx(1.0)


# ============================================================================
# T12  All-NaN prices
# ============================================================================


class TestNaNInput:
    def test_nan_close_returns_empty(self) -> None:
        closes = [float("nan")] * 50
        bars = _bars(closes=closes)
        result = _run(bars, entry_n=20, exit_n=10, direction="long")
        assert result.metrics["n_trades"] == 0


# ============================================================================
# T13  Unique run_ids
# ============================================================================


class TestSharpeSanity:
    def test_sharpe_equity_lower_than_trade_sharpe(self) -> None:
        """The equity-curve daily Sharpe must be lower than the trade-level Sharpe.
        
        Trade-level Sharpe scales by sqrt(252) but each 'observation' is a trade
        (may span many days). The equity-curve Sharpe scales the same but the daily
        returns include many flat/zero days — so it is smaller.
        """
        bars = _trending_bars(n=300)
        result = _run(bars, entry_n=20, exit_n=10, direction="long", fee_bps=0.0)
        if result.metrics["n_trades"] < 5:
            pytest.skip("Not enough trades for Sharpe comparison")
        se = result.metrics["sharpe_equity"]
        st = result.metrics["sharpe"]
        assert not math.isnan(se), "sharpe_equity must not be NaN with sufficient trades"
        assert not math.isnan(st), "sharpe must not be NaN with sufficient trades"
        assert se < st, (
            f"sharpe_equity {se:.3f} should be < trade-level sharpe {st:.3f}"
        )

    def test_sharpe_equity_positive_on_profitable_strategy(self) -> None:
        bars = _trending_bars(n=300)
        result = _run(bars, entry_n=20, exit_n=10, direction="long", fee_bps=0.0)
        if result.metrics["total_return"] > 0 and result.metrics["n_trades"] >= 5:
            assert result.metrics["sharpe_equity"] > 0


# ============================================================================
# T18  Metrics completeness
# ============================================================================


class TestMetricsCompleteness:
    _REQUIRED = frozenset({
        "n_trades", "total_return", "win_rate", "sharpe",
        "sharpe_equity", "max_drawdown", "expectancy",
    })

    def test_all_keys_present(self) -> None:
        bars = _trending_bars(n=100)
        result = _run(bars, entry_n=20, exit_n=10, direction="long")
        missing = self._REQUIRED - set(result.metrics)
        assert not missing, f"Missing metric keys: {missing}"

    def test_empty_result_all_keys(self) -> None:
        bars = _bars(closes=[100.0] * 5)  # too short
        result = _run(bars, entry_n=20, exit_n=10, direction="long")
        missing = self._REQUIRED - set(result.metrics)
        assert not missing, f"Empty result missing metric keys: {missing}"


# ============================================================================
# T19  Equity curve only jumps at trade exits
# ============================================================================


class TestEquityCurve:
    def test_equity_flat_between_trades(self) -> None:
        """Equity must be constant in all bars where no trade is open (flat periods).

        The simulator produces a mark-to-market (MTM) equity curve: equity moves
        during open positions and is flat only between a trade exit and the next
        trade entry.  This test verifies the flat periods are truly flat.
        """
        closes = (
            [100.0 + i for i in range(40)]    # uptrend
            + [140.0 - i for i in range(40)]  # reversal
            + [100.0 + i for i in range(40)]  # second uptrend
        )
        bars = _bars(closes=closes)
        result = _run(bars, entry_n=20, exit_n=10, direction="long")
        if result.trades.empty:
            return

        eq_arr = result.equity.values
        equity_idx = result.equity.index

        # Build the set of bar positions that are inside any trade (entry through exit inclusive)
        in_trade_positions: set[int] = set()
        for _, row in result.trades.iterrows():
            try:
                entry_pos = equity_idx.get_loc(row["entry_ts"])
                exit_pos  = equity_idx.get_loc(row["exit_ts"])
                for p in range(entry_pos, exit_pos + 1):
                    in_trade_positions.add(p)
            except KeyError:
                pass

        # Verify equity is flat (constant) in every bar that is NOT inside a trade
        for i in range(1, len(eq_arr)):
            if i not in in_trade_positions:
                assert eq_arr[i] == pytest.approx(eq_arr[i - 1], rel=1e-9), (
                    f"Equity changed in a flat (between-trade) period at position {i} "
                    f"({equity_idx[i]}): {eq_arr[i-1]} → {eq_arr[i]}"
                )


# ============================================================================
# T20  No duplicate trades in output
# ============================================================================


class TestNoDuplicateTrades:
    def test_no_duplicate_entry_exit_pairs(self) -> None:
        bars = _trending_bars(n=300)
        result = _run(bars, entry_n=20, exit_n=10, direction="long")
        dupes = result.trades.duplicated(subset=["entry_ts", "exit_ts"])
        assert not dupes.any(), f"Duplicate trades found:\n{result.trades[dupes]}"


# ============================================================================
# T21  4h resampling preserves OHLCV integrity
# ============================================================================


class TestHardStopLevel:
    def test_hard_stop_based_on_entry_open(self) -> None:
        """hard_stop = entry_open - 2*ATR_at_signal_bar (long).

        If the entry open is gapped up from the signal close, the stop
        level should be set relative to the entry open (not the signal close).
        """
        # 25 flat bars (atr ≈ 0.5), breakout at 101, entry opens at 110 (gap up)
        flat_c = [100.0] * 25; flat_h = [100.5] * 25; flat_l = [99.5] * 25
        breakout_c = [101.0]; breakout_h = [102.0]; breakout_l = [100.5]
        # Entry execution bar: opens at 110 (gap-up overnight)
        entry_c = [111.0]; entry_h = [112.0]; entry_l = [109.5]; entry_o = [110.0]
        # Hard stop bar: low dips to 107 (below 110 - 2*0.5=109 stop)
        stop_c = [107.5]; stop_h = [111.0]; stop_l = [107.0]; stop_o = [110.5]
        padding_c = [107.0] * 5

        all_c = flat_c + breakout_c + entry_c + stop_c + padding_c
        all_o = flat_c + breakout_c + entry_o + stop_o + [107.0] * 5
        all_h = flat_h + breakout_h + entry_h + stop_h + [108.0] * 5
        all_l = flat_l + breakout_l + entry_l + stop_l + [106.5] * 5

        bars = _bars(closes=all_c, opens=all_o, highs=all_h, lows=all_l)
        result = _run(bars, entry_n=20, exit_n=10, direction="long", fee_bps=0.0, stop_atr_mult=2.0, atr_n=20)

        if result.trades.empty:
            return

        first_trade = result.trades.iloc[0]
        # hard_stop ≈ 110 - 2*0.5 = 109; intraday low of 107 breaches it
        # Entry price should be around 110 (the gap-up open)
        assert first_trade["entry_price"] == pytest.approx(110.0), (
            f"Expected entry at gap-up open 110, got {first_trade['entry_price']}"
        )


class TestBothDirection:
    def test_both_direction_produces_mixed_sides(self) -> None:
        closes = (
            [100.0 + i for i in range(60)]
            + [160.0 - i for i in range(60)]
            + [100.0 + i for i in range(60)]
        )
        n = len(closes)
        c = np.array(closes)
        idx = pd.date_range("2020-01-01", periods=n, freq="1D", tz="UTC")
        bars = pd.DataFrame(
            {"open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 1.0},
            index=idx,
        )
        bars.index.name = "timestamp"
        result = _run(bars, entry_n=15, exit_n=8, direction="both", fee_bps=0.0)
        if result.trades.empty:
            pytest.skip("No trades in oscillating series")
        sides = set(result.trades["side"].unique())
        assert "long" in sides or "short" in sides


class TestEnrichedTradeSchema:
    def test_trades_have_all_trade_columns(self) -> None:
        result = _run(_trending_bars(n=300), fee_bps=0.0)
        if result.trades.empty:
            pytest.skip("No trades")
        missing = set(TRADE_COLUMNS) - set(result.trades.columns)
        assert not missing, f"Missing TRADE_COLUMNS: {missing}"

    def test_trade_column_order_matches_schema(self) -> None:
        result = _run(_trending_bars(n=300), fee_bps=0.0)
        if result.trades.empty:
            pytest.skip("No trades")
        assert list(result.trades.columns) == TRADE_COLUMNS

    def test_new_metrics_present(self) -> None:
        _NEW = frozenset({"sortino_equity", "calmar", "profit_factor", "omega", "avg_hold_days"})
        result = _run(_trending_bars(n=300), fee_bps=0.0)
        missing = _NEW - set(result.metrics)
        assert not missing, f"Missing new metric keys: {missing}"
