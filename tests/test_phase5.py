"""Phase 5 unit tests — backtest harness.

Tests:
    TestSpotSimulate  — handcrafted 100-bar series with 3 known trades
    TestRobustness    — deflated_sharpe closed-form, bootstrap_ci coverage
    TestCryoBTBridge  — duck-typed shape check, generate_signals
    TestReports       — render writes a non-empty HTML file
    TestCLIBacktest   — CLI subcommand smoke tests
"""
from __future__ import annotations

import math
from datetime import timezone

import numpy as np
import pandas as pd
import pytest

from tests.conftest import make_ohlcv


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_bars(n: int = 100) -> pd.DataFrame:
    return make_ohlcv(n=n, start="2024-01-01", freq="1h")


def _const_signal(bars: pd.DataFrame, fire_rows: list[int]):
    """BoolSignal that fires at exactly the given row indices."""
    from cryoquant.signals.base import BoolSignal

    mask = pd.Series(False, index=bars.index)
    mask.iloc[fire_rows] = True

    return BoolSignal(
        signal_id="test_bool",
        condition=lambda df: mask.reindex(df.index, fill_value=False),
    )


# ─────────────────────────────────────────────────────────────────────────────
# TestSpotSimulate
# ─────────────────────────────────────────────────────────────────────────────

class TestSpotSimulate:

    def test_no_fires_returns_empty_trades(self):
        from cryoquant.backtest.spot_pnl import simulate
        from cryoquant.signals.base import BoolSignal

        bars = _make_bars(50)
        sig = BoolSignal("never", condition=lambda df: pd.Series(False, index=df.index))
        result = simulate(sig, bars, hold_h=5)

        assert result.trades.empty
        assert len(result.equity) == len(bars)
        assert float(result.equity.iloc[0]) == pytest.approx(1.0)
        assert result.metrics["n_trades"] == 0

    def test_three_known_trades_boundaries(self):
        """Fire at rows 0, 30, 60 → entries at 1, 31, 61."""
        from cryoquant.backtest.spot_pnl import simulate

        bars = _make_bars(100)
        # Use constant open prices to make P&L deterministic
        bars["open"] = 100.0
        bars["close"] = 100.0

        sig = _const_signal(bars, fire_rows=[0, 30, 60])
        result = simulate(sig, bars, hold_h=5, fee_bps=0.0)

        assert result.metrics["n_trades"] == 3
        # entry at bar 1, exit at bar 6
        assert result.trades["entry_price"].iloc[0] == pytest.approx(100.0)
        assert result.trades["exit_price"].iloc[0]  == pytest.approx(100.0)

    def test_pnl_with_rising_prices(self):
        """Check P&L sign when exit price > entry price."""
        from cryoquant.backtest.spot_pnl import simulate

        bars = _make_bars(50)
        opens = np.linspace(100, 200, 50)
        bars["open"] = opens
        bars["close"] = opens

        sig = _const_signal(bars, fire_rows=[0])
        result = simulate(sig, bars, hold_h=10, fee_bps=0.0)

        assert result.metrics["n_trades"] == 1
        pnl = result.trades["pnl_pct"].iloc[0]
        assert pnl > 0, "Rising prices → positive P&L"

    def test_fee_reduces_pnl(self):
        from cryoquant.backtest.spot_pnl import simulate

        bars = _make_bars(50)
        bars["open"] = 100.0
        bars["close"] = 100.0

        sig = _const_signal(bars, fire_rows=[0])
        result_nofee = simulate(sig, bars, hold_h=5, fee_bps=0.0)
        result_fee   = simulate(sig, bars, hold_h=5, fee_bps=10.0)

        pnl_nofee = result_nofee.trades["pnl_pct"].iloc[0]
        pnl_fee   = result_fee.trades["pnl_pct"].iloc[0]
        assert pnl_fee < pnl_nofee, "Fees must reduce P&L"

    def test_equity_starts_at_one(self):
        from cryoquant.backtest.spot_pnl import simulate

        bars = _make_bars(100)
        sig = _const_signal(bars, fire_rows=[5])
        result = simulate(sig, bars, hold_h=10)

        assert float(result.equity.iloc[0]) == pytest.approx(1.0)

    def test_next_open_no_lookahead(self):
        """Entry must be at NEXT bar's open, not the current bar's open."""
        from cryoquant.backtest.spot_pnl import simulate

        bars = _make_bars(50)
        # Fire bar has open=100, NEXT bar has open=200 — entry should be 200
        bars["open"] = 100.0
        bars["close"] = 100.0
        bars.loc[bars.index[1], "open"] = 200.0  # next bar after fire at row 0

        sig = _const_signal(bars, fire_rows=[0])
        result = simulate(sig, bars, hold_h=5, fee_bps=0.0)

        assert result.trades["entry_price"].iloc[0] == pytest.approx(200.0)

    def test_non_overlapping_skips_concurrent_fire(self):
        """Second fire while trade is open must be skipped."""
        from cryoquant.backtest.spot_pnl import simulate

        bars = _make_bars(50)
        bars["open"] = 100.0
        bars["close"] = 100.0

        # Fire at 0 and 2 with hold_h=10 — fire at 2 overlaps with trade [1..11]
        sig = _const_signal(bars, fire_rows=[0, 2, 20])
        result = simulate(sig, bars, hold_h=10, fee_bps=0.0)

        assert result.metrics["n_trades"] == 2, "Only 2 non-overlapping trades"
        assert result.trades["entry_price"].iloc[0] == pytest.approx(100.0)

    def test_prob_signal_uses_threshold(self):
        """ProbSignal fires when prob >= threshold."""
        from cryoquant.backtest.spot_pnl import simulate
        from cryoquant.signals.base import ProbSignal
        from cryoquant.models.baselines import make_pullback
        from cryoquant.models.tabular import TabularModel

        bars = _make_bars(200)
        # Create a synthetic prob series
        probs = pd.Series(0.3, index=bars.index)
        probs.iloc[10] = 0.8  # only fires at bar 10 with threshold=0.6

        model = make_pullback()
        # Use a minimal trained model that always returns a fixed prob
        class _ConstModel:
            signal_id = "const"
            version = "1"
            default_threshold = 0.6
            symbol_str = ""

            def as_feature(self, df):
                return probs.reindex(df.index, fill_value=0.3)

        result = simulate(_ConstModel(), bars, thr=0.6, hold_h=5, fee_bps=0.0)
        assert result.metrics["n_trades"] == 1

    def test_metrics_finite(self):
        from cryoquant.backtest.spot_pnl import simulate

        bars = _make_bars(100)
        sig = _const_signal(bars, fire_rows=[0, 20, 40, 60])
        result = simulate(sig, bars, hold_h=10)

        for key in ("total_return", "win_rate", "n_trades"):
            assert math.isfinite(result.metrics[key]), f"{key} must be finite"


# ─────────────────────────────────────────────────────────────────────────────
# TestRobustness
# ─────────────────────────────────────────────────────────────────────────────

class TestRobustness:

    def test_deflated_sharpe_neutral_strategy(self):
        """SR=0 → DSR ≈ 0.5 for a single trial."""
        from cryoquant.backtest.robustness import deflated_sharpe
        dsr = deflated_sharpe(0.0, n_trials=1, n_obs=252)
        assert 0.4 < dsr < 0.6, f"Expected DSR ≈ 0.5, got {dsr}"

    def test_deflated_sharpe_high_sr_single_trial(self):
        """High Sharpe with one trial → high DSR."""
        from cryoquant.backtest.robustness import deflated_sharpe
        dsr = deflated_sharpe(2.0, n_trials=1, n_obs=252)
        assert dsr > 0.9, f"Expected DSR > 0.9, got {dsr}"

    def test_deflated_sharpe_multiple_trials_reduces_dsr(self):
        """Same SR with more trials → lower DSR (harder to pass)."""
        from cryoquant.backtest.robustness import deflated_sharpe
        dsr_1  = deflated_sharpe(1.5, n_trials=1,   n_obs=252)
        dsr_10 = deflated_sharpe(1.5, n_trials=10,  n_obs=252)
        dsr_100 = deflated_sharpe(1.5, n_trials=100, n_obs=252)
        assert dsr_1 > dsr_10 > dsr_100

    def test_deflated_sharpe_returns_probability(self):
        """Output must be in [0, 1]."""
        from cryoquant.backtest.robustness import deflated_sharpe
        for sr in [-2.0, -0.5, 0.0, 0.5, 1.0, 3.0]:
            dsr = deflated_sharpe(sr, n_trials=5, n_obs=252)
            assert 0.0 <= dsr <= 1.0

    @pytest.mark.slow
    def test_bootstrap_ci_contains_true_mean(self):
        """95% CI should cover true mean in ≥ 90% of random experiments."""
        from cryoquant.backtest.robustness import bootstrap_ci
        rng = np.random.default_rng(0)
        true_mean = 0.05
        n_experiments = 100
        covered = 0
        for seed in range(n_experiments):
            trades = rng.normal(true_mean, 0.1, size=60)
            lo, hi = bootstrap_ci(trades, np.mean, n=2000, alpha=0.05, rng_seed=seed)
            if lo <= true_mean <= hi:
                covered += 1
        assert covered >= 90, f"CI covered {covered}/100 experiments (expected ≥ 90)"

    def test_bootstrap_ci_returns_tuple_of_two_floats(self):
        from cryoquant.backtest.robustness import bootstrap_ci
        rng = np.random.default_rng(42)
        trades = rng.normal(0.0, 0.1, size=50)
        lo, hi = bootstrap_ci(trades, np.mean, n=500, alpha=0.05)
        assert isinstance(lo, float)
        assert isinstance(hi, float)
        assert lo < hi


# ─────────────────────────────────────────────────────────────────────────────
# TestCryoBTBridge
# ─────────────────────────────────────────────────────────────────────────────

class TestCryoBTBridge:

    def _make_bool_signal(self):
        from cryoquant.signals.base import BoolSignal
        return BoolSignal(
            "test_bool",
            condition=lambda df: pd.Series(True, index=df.index),
            version="1",
        )

    def test_bridge_has_required_attributes(self):
        from cryoquant.backtest.cryobt_bridge import CryoBTAdapter
        adapter = CryoBTAdapter(self._make_bool_signal())
        assert isinstance(adapter.name, str) and adapter.name
        assert isinstance(adapter.description, str)
        assert callable(adapter.generate_signals)
        assert callable(adapter.get_parameters)

    def test_bridge_generate_signals_bool(self):
        from cryoquant.backtest.cryobt_bridge import CryoBTAdapter
        bars = _make_bars(20)
        adapter = CryoBTAdapter(self._make_bool_signal())
        sigs = adapter.generate_signals(bars)
        assert isinstance(sigs, pd.Series)
        assert set(sigs.unique()).issubset({0, 1})

    def test_bridge_generate_signals_state(self):
        from cryoquant.backtest.cryobt_bridge import CryoBTAdapter
        from cryoquant.signals.base import StateSignal
        bars = _make_bars(20)
        state_sig = StateSignal(
            "s1",
            state_fn=lambda df: pd.Series(1, index=df.index, dtype="int8"),
        )
        adapter = CryoBTAdapter(state_sig)
        sigs = adapter.generate_signals(bars)
        assert set(sigs.unique()).issubset({-1, 0, 1})

    def test_bridge_get_parameters_contains_signal_id(self):
        from cryoquant.backtest.cryobt_bridge import CryoBTAdapter
        adapter = CryoBTAdapter(self._make_bool_signal(), threshold=0.7)
        params = adapter.get_parameters()
        assert "signal_id" in params
        assert "threshold" in params
        assert params["threshold"] == pytest.approx(0.7)

    def test_bridge_duck_typed_check(self):
        """The adapter must have all required Strategy attributes/methods."""
        from cryoquant.backtest.cryobt_bridge import CryoBTAdapter

        adapter = CryoBTAdapter(self._make_bool_signal())
        # Duck-typed Strategy check (no actual CryoBacktester invocation)
        assert hasattr(adapter, "name")
        assert hasattr(adapter, "description")
        assert hasattr(adapter, "generate_signals")
        assert hasattr(adapter, "get_parameters")
        bars = _make_bars(10)
        sigs = adapter.generate_signals(bars)
        assert len(sigs) == len(bars)
        params = adapter.get_parameters()
        assert isinstance(params, dict)


# ─────────────────────────────────────────────────────────────────────────────
# TestReports
# ─────────────────────────────────────────────────────────────────────────────

class TestReports:

    def test_render_spot_pnl_writes_html(self, tmp_path):
        from cryoquant.backtest.reports import render_spot_result
        from cryoquant.backtest.spot_pnl import simulate

        bars = _make_bars(100)
        sig = _const_signal(bars, fire_rows=[0, 20, 40])
        result = simulate(sig, bars, hold_h=5)

        out = tmp_path / "report.html"
        rendered = render_spot_result(result, out)
        assert rendered.exists()
        content = rendered.read_text()
        assert "<html" in content.lower()
        # Jinja2 autoescape renders & as &amp; in title
        assert "Spot P" in content and "L Report" in content
        assert len(content) > 500

    def test_render_option_result_writes_html(self, tmp_path):
        from cryoquant.backtest.reports import render_option_result
        from cryoquant.backtest.option_lookup import OptionResult

        result = OptionResult(
            fires_evaluated=10,
            fires_with_data=7,
            pnl_pct=[0.1, -0.2, 0.3, 0.05, -0.1, 0.4, 0.2],
            win_rate=0.57,
            expectancy=0.107,
            entry_costs_usd=[800.0] * 7,
            dte_actual=[2] * 7,
        )
        out = tmp_path / "opt.html"
        rendered = render_option_result(result, out, dte=2, delta=0.25)
        assert rendered.exists()
        content = rendered.read_text()
        assert "Option Lookup Report" in content

    def test_render_unknown_template_raises(self, tmp_path):
        from cryoquant.backtest.reports import render
        from jinja2 import TemplateNotFound
        with pytest.raises(TemplateNotFound):
            render("no_such_template", {}, tmp_path / "out.html")


# ─────────────────────────────────────────────────────────────────────────────
# TestCLIBacktest
# ─────────────────────────────────────────────────────────────────────────────

class TestCLIBacktest:

    def test_backtest_spot_stub(self, capsys):
        from cryoquant.cli import main
        rc = main(["backtest", "spot", "--signal", "pullback_v1"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "pullback_v1" in captured.out

    def test_backtest_options_stub(self, capsys):
        from cryoquant.cli import main
        rc = main(["backtest", "options", "--signal", "pullback_v1", "--dte", "2"])
        assert rc == 0

    def test_backtest_no_subcommand_returns_one(self):
        from cryoquant.cli import main
        rc = main(["backtest"])
        assert rc == 1
