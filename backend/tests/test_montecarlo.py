"""Monte Carlo: hand-computed path metrics, seeded determinism, CIs,
delay wrapper semantics."""
import numpy as np
import pandas as pd
import pytest

from engine.backtest import Backtester
from engine.data.feeds import InMemoryFeed
from engine.execution.costs import ZeroCostModel
from engine.strategy import ScriptedStrategy
from engine.types import Side
from engine.validation.montecarlo import (
    DelayedStrategy,
    bootstrap_trades,
    confidence_intervals,
    delayed_execution_runs,
    path_metrics,
    perturbed_cost_runs,
    skip_trades,
    trade_reshuffle,
)

from tests.helpers import bar, ts


def test_path_metrics_hand_computed():
    # pnls [10, -5, 20], initial 100, span 1 year.
    # equity path: [100, 110, 105, 125]
    # end = 125 ; cagr = 125/100 - 1 = 0.25 (span exactly 1y)
    # cummax [100, 110, 110, 125] -> dd min at 105: 105/110 - 1 = -0.0454545
    # PF = 30/5 = 6 ; expectancy = 25/3 = 8.333333
    # per-trade returns: 10/100 = 0.1 ; -5/110 = -0.04545455 ; 20/105 = 0.19047619
    # mean = 0.08167388 ; std(ddof=1) = 0.11902812 ; trades/yr = 3
    # sharpe = 0.08167388 / 0.11902812 * sqrt(3) = 1.188432 (approx)
    m = path_metrics(np.array([10.0, -5.0, 20.0]), initial=100.0, span_years=1.0)
    assert m["end_equity"] == pytest.approx(125.0)
    assert m["cagr"] == pytest.approx(0.25)
    assert m["max_drawdown"] == pytest.approx(-5 / 110)
    assert m["profit_factor"] == pytest.approx(6.0)
    assert m["expectancy"] == pytest.approx(25 / 3)
    assert m["sharpe"] == pytest.approx(1.1884, abs=2e-3)


def test_path_metrics_degenerate():
    m = path_metrics(np.array([5.0, 5.0]), initial=100.0, span_years=1.0)
    assert m["profit_factor"] == np.inf     # no losses
    m2 = path_metrics(np.array([-5.0, -5.0]), initial=100.0, span_years=1.0)
    assert m2["profit_factor"] == 0.0       # no wins


PNLS = [10.0, -5.0, 20.0, -8.0, 12.0, 3.0, -2.0, 7.0]


def test_reshuffle_preserves_multiset_and_endpoint():
    mc = trade_reshuffle(PNLS, initial=1_000.0, span_years=1.0, n_iter=50, seed=1)
    # Permutations keep the SUM: end equity identical in every iteration.
    # sum(PNLS) = 10-5+20-8+12+3-2+7 = 37 -> end equity 1037 always.
    assert mc.samples["end_equity"].nunique() == 1
    assert mc.samples["end_equity"].iloc[0] == pytest.approx(1_037.0)
    # Profit factor and expectancy are permutation-invariant too.
    assert mc.samples["profit_factor"].nunique() == 1
    assert mc.samples["expectancy"].nunique() == 1
    # Drawdown does vary with ordering.
    assert mc.samples["max_drawdown"].nunique() > 1


def test_seeded_determinism_all_methods():
    for fn in (trade_reshuffle, bootstrap_trades, skip_trades):
        a = fn(PNLS, 1_000.0, 1.0, n_iter=30, seed=9)
        b = fn(PNLS, 1_000.0, 1.0, n_iter=30, seed=9)
        c = fn(PNLS, 1_000.0, 1.0, n_iter=30, seed=10)
        pd.testing.assert_frame_equal(a.samples, b.samples)
        assert not a.samples.equals(c.samples)


def test_bootstrap_varies_endpoint():
    mc = bootstrap_trades(PNLS, 1_000.0, 1.0, n_iter=50, seed=3)
    assert mc.samples["end_equity"].nunique() > 1   # resampling changes sums


def test_skip_trades_removes_some():
    mc = skip_trades(PNLS, 1_000.0, 1.0, n_iter=200, seed=5, skip_prob=0.25)
    # End equity should differ from the full path in most iterations.
    full_end = 1_000.0 + sum(PNLS)
    assert (mc.samples["end_equity"] != pytest.approx(full_end)).any()


def test_confidence_intervals_hand_computed():
    # Samples 1..5: q0.5 = 3; q0.025 (linear) = 1 + 0.025*4*(1) = 1.1;
    # q0.975 = 1 + 0.975*4 = 4.9.
    samples = pd.DataFrame({"sharpe": [1.0, 2.0, 3.0, 4.0, 5.0]})
    ci = confidence_intervals(samples)
    assert ci.loc["sharpe", "q0.5"] == pytest.approx(3.0)
    assert ci.loc["sharpe", "q0.025"] == pytest.approx(1.1)
    assert ci.loc["sharpe", "q0.975"] == pytest.approx(4.9)


def test_confidence_intervals_ignore_inf():
    samples = pd.DataFrame({"profit_factor": [1.0, 2.0, np.inf, 3.0]})
    ci = confidence_intervals(samples, levels=(0.5,))
    assert ci.loc["profit_factor", "q0.5"] == pytest.approx(2.0)


def test_empty_trades_raise():
    with pytest.raises(ValueError, match="no trades"):
        trade_reshuffle([], 1_000.0, 1.0, n_iter=5, seed=0)


# ── engine re-run perturbations ───────────────────────────────────────
class CostSensitiveStub:
    """Stands in for a full backtest: metrics depend on the multipliers so
    determinism and plumbing are observable."""

    def __init__(self, s_mult, c_mult):
        self.metrics = {
            "sharpe": 2.0 - s_mult - 0.5 * c_mult,
            "max_drawdown": -0.1 * s_mult,
            "cagr": 0.2 - 0.05 * s_mult,
            "profit_factor": 3.0 / c_mult,
            "expectancy": 10.0 - s_mult,
            "end_equity": 100_000 * (1.1 - 0.01 * s_mult),
        }


def test_perturbed_cost_runs_seeded():
    calls = []

    def run(s, c):
        calls.append((s, c))
        return CostSensitiveStub(s, c)

    a = perturbed_cost_runs(run, n_iter=20, seed=11)
    calls_a = list(calls); calls.clear()
    b = perturbed_cost_runs(run, n_iter=20, seed=11)
    assert calls_a == calls              # identical multiplier draws
    pd.testing.assert_frame_equal(a.samples, b.samples)
    assert (a.samples["slippage_mult"] >= 0.5).all()
    assert (a.samples["slippage_mult"] <= 2.0).all()
    assert "sharpe" in a.ci.index


# ── delayed execution (strategy-layer, engine untouched) ──────────────
def _delay_run(delay):
    bars = [bar(d, 100 + d, 101 + d, 99 + d, 100 + d) for d in range(1, 8)]
    inner = ScriptedStrategy({0: lambda b, c: c.submit("X", Side.BUY, 10)})
    strat = DelayedStrategy(inner, delay_bars=delay) if delay is not None else inner
    bt = Backtester(InMemoryFeed(bars), strat, ZeroCostModel(),
                    initial_cash=10_000, max_participation=None)
    return bt.run(), bt


def test_delay_zero_identical_to_unwrapped():
    r_plain, _ = _delay_run(None)
    r_zero, _ = _delay_run(0)
    assert [f.ts for f in r_plain.fills] == [f.ts for f in r_zero.fills]
    assert [f.price for f in r_plain.fills] == [f.price for f in r_zero.fills]
    assert r_plain.equity_curve.equals(r_zero.equity_curve)


def test_delay_shifts_fill_by_exact_bars():
    # Unwrapped: submit during bar1 -> fills bar2 open (Phase 1 eligibility).
    # delay=1: intent queued on bar1, released during bar2's processing
    # (submitted then), eligible bar3 -> fills bar3 open. delay=2 -> bar4.
    r0, _ = _delay_run(0)
    r1, _ = _delay_run(1)
    r2, _ = _delay_run(2)
    assert r0.fills[0].ts == ts(2)
    assert r1.fills[0].ts == ts(3)
    assert r2.fills[0].ts == ts(4)
    # Rising fixture: every bar of delay costs a worse (higher) buy price.
    assert r0.fills[0].price < r1.fills[0].price < r2.fills[0].price


def test_delayed_execution_runs_table():
    from engine.metrics.performance import full_report

    def run_with_metrics(d):
        result, _ = _delay_run(d)
        result.metrics = full_report(result.equity_curve, result.trade_pnls,
                                     result.exposure)
        return result

    table = delayed_execution_runs(run_with_metrics, delays=(0, 1, 2))
    assert list(table["delay_bars"]) == [0, 1, 2]
    assert "sharpe" in table.columns
    # Rising-price fixture: later entry -> higher cost basis -> lower end equity.
    assert table["end_equity"].iloc[0] > table["end_equity"].iloc[2]
