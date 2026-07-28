"""Risk engine: every check exercised pass and fail, with exact sizing
math and check-order verification."""
import dataclasses
from datetime import UTC, datetime

import pytest

from engine.portfolio.accounting import Portfolio
from engine.types import Fill, Side
from ops.deployments import RiskPolicy, deployment_from_experiment
from ops.risk import MarketState, SignalCandidate, evaluate

from tests.ops_fixtures import ops_env  # noqa: F401

TS = datetime(2026, 1, 5, 16, 0, tzinfo=UTC)      # Monday, inside session


def make_state(equity_cash=100_000.0, **overrides) -> MarketState:
    state = MarketState(
        portfolio=Portfolio(initial_cash=equity_cash),
        last_bar_ts={"DEMO": TS},
        last_close={"DEMO": 100.0},
        last_dollar_volume={"DEMO": 50_000_000.0},
        last_quote={"DEMO": {"bid": 99.95, "ask": 100.05, "spread_bps": 10.0}},
        bars_seen={"DEMO": 30},
        day_start_equity=equity_cash,
        current_day=TS.date().isoformat(),
    )
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


@pytest.fixture()
def dep(ops_env):
    d = deployment_from_experiment(ops_env["experiment"])
    return dataclasses.replace(d, id="")     # fresh id, default policy


def cand(side=Side.BUY, qty=10.0, ts=TS) -> SignalCandidate:
    return SignalCandidate(
        deployment_id="dep1", strategy="MACrossover", symbol="DEMO",
        side=side, qty=qty, ts=ts, received_at=ts,
    )


def test_clean_approval_and_pct_equity_sizing(dep):
    state = make_state()
    result = evaluate(cand(), dep, state)
    assert result.approved, result.rejection
    # pct_equity: floor(100_000 * 0.1 / 100) = 100 shares exactly.
    assert result.final_qty == 100.0
    assert [d.check for d in result.decisions][:2] == ["emergency_stop", "market_hours"]


def test_fixed_qty_sizing(dep):
    dep = dataclasses.replace(
        dep, risk=RiskPolicy(sizing_mode="fixed_qty", sizing_value=7), id="")
    result = evaluate(cand(), dep, make_state())
    assert result.approved and result.final_qty == 7.0


def test_emergency_stop_blocks_everything(dep):
    result = evaluate(cand(), dep, make_state(emergency_stop=True))
    assert not result.approved
    assert result.rejection.check == "emergency_stop"


def test_market_hours(dep):
    weekend = datetime(2026, 1, 3, 16, 0, tzinfo=UTC)      # Saturday
    result = evaluate(cand(ts=weekend), dep, make_state())
    assert result.rejection.check == "market_hours"
    after_close = datetime(2026, 1, 5, 22, 0, tzinfo=UTC)  # past 21:00 close
    result = evaluate(cand(ts=after_close), dep, make_state())
    assert result.rejection.check == "market_hours"
    assert "session" in result.rejection.evidence


def test_data_quality_requires_bars(dep):
    result = evaluate(cand(), dep, make_state(last_bar_ts={}))
    assert result.rejection.check == "data_quality"


def test_duplicate_cooldown(dep):
    state = make_state(recent_signals=[(dep.id, "DEMO", "buy", 30)])
    dep_cand = dataclasses.replace(cand(), deployment_id=dep.id)
    result = evaluate(dep_cand, dep, state)
    assert result.rejection.check == "duplicate"
    # outside cooldown: previous signal 5 bars ago, cooldown 1 -> fine
    state2 = make_state(recent_signals=[(dep.id, "DEMO", "buy", 25)])
    assert evaluate(dep_cand, dep, state2).approved
    # different side is not a duplicate
    state3 = make_state(recent_signals=[(dep.id, "DEMO", "buy", 30)])
    assert evaluate(
        dataclasses.replace(cand(side=Side.SELL), deployment_id=dep.id),
        dep, state3, is_closing=True,
    ).approved


def test_spread_gate(dep):
    state = make_state(
        last_quote={"DEMO": {"bid": 99, "ask": 101, "spread_bps": 200.0}})
    result = evaluate(cand(), dep, state)
    assert result.rejection.check == "spread"
    assert result.rejection.evidence["spread_bps"] == 200.0


def test_liquidity_floor(dep):
    result = evaluate(cand(), dep, make_state(last_dollar_volume={"DEMO": 5000.0}))
    assert result.rejection.check == "liquidity"


def test_position_limit(dep):
    tight = dataclasses.replace(
        dep, risk=RiskPolicy(sizing_mode="fixed_qty", sizing_value=500,
                             max_position_pct=0.25), id="")
    # 500 shares * $100 = 50k on 100k equity = 50% > 25% cap.
    result = evaluate(cand(), tight, make_state())
    assert result.rejection.check == "position_limit"


def test_exposure_limit_counts_existing_positions(dep):
    state = make_state()
    # Preload a big position in another symbol: 900 * 100 = 90k gross.
    state.portfolio.apply_fill(Fill(order_id=1, symbol="OTHER", side=Side.BUY,
                                    qty=900, price=100.0, fees=0.0, ts=TS))
    state.portfolio.mark("OTHER", 100.0)
    tight = dataclasses.replace(
        dep, risk=RiskPolicy(sizing_mode="fixed_qty", sizing_value=200,
                             max_position_pct=1.0,
                             max_gross_exposure_pct=1.0), id="")
    result = evaluate(cand(), tight, state)     # +20k -> 110k gross > equity
    assert result.rejection.check == "exposure_limit"


def test_daily_loss_limit_halts(dep):
    state = make_state()
    state.day_start_equity = 100_000.0
    state.portfolio.cash -= 5_000.0            # 5% down on the day, limit 3%
    result = evaluate(cand(), dep, state)
    assert result.rejection.check == "daily_loss"


def test_buying_power_uses_frozen_validation(dep):
    poor = make_state(equity_cash=500.0)
    big = dataclasses.replace(
        dep, risk=RiskPolicy(sizing_mode="fixed_qty", sizing_value=50,
                             max_position_pct=100.0,
                             max_gross_exposure_pct=100.0), id="")
    result = evaluate(cand(), big, poor)        # 50 * $100 = 5k > $500
    assert result.rejection.check == "buying_power"
    assert "insufficient buying power" in result.rejection.reason


def test_short_policy(dep):
    no_shorts = dataclasses.replace(
        dep, risk=RiskPolicy(allow_short=False), id="")
    result = evaluate(cand(side=Side.SELL), no_shorts, make_state())
    assert not result.approved
    assert "short" in result.rejection.reason


def test_closing_bypasses_entry_gates_not_safety(dep):
    state = make_state(
        last_quote={"DEMO": {"bid": 90, "ask": 110, "spread_bps": 2000.0}},
        last_dollar_volume={"DEMO": 100.0},
    )
    state.portfolio.apply_fill(Fill(order_id=1, symbol="DEMO", side=Side.BUY,
                                    qty=50, price=100.0, fees=0.0, ts=TS))
    state.portfolio.mark("DEMO", 100.0)
    exit_cand = cand(side=Side.SELL, qty=50)
    # closing: awful spread/liquidity don't trap the position
    assert evaluate(exit_cand, dep, state, is_closing=True).approved
    # ...but the kill switch still does
    state.emergency_stop = True
    assert not evaluate(exit_cand, dep, state, is_closing=True).approved
