"""Strategy SDK: helpers, targeting math, params, logging, no-future history."""
from datetime import UTC, datetime

import pandas as pd
import pytest

from engine.backtest import Backtester
from engine.data.feeds import InMemoryFeed
from engine.data.history import HistoryService
from engine.execution.costs import ZeroCostModel
from engine.params import Param, resolve_params
from engine.sdk import Context, SDKAdapter, SDKStrategy
from engine.types import OrderType, Side

from tests.helpers import bar, ts
from tests.helpers_data import canon_daily


class Probe(SDKStrategy):
    """Runs one queued action per bar and records observations."""

    params = [Param("x", "int", 7, min=1, max=10)]

    def __init__(self, actions):
        self.actions = list(actions)
        self.i = -1
        self.seen_params = None
        self.fills = []

    def initialize(self, context):
        self.seen_params = context.params

    def on_bar(self, context, data):
        self.i += 1
        if self.i < len(self.actions) and self.actions[self.i]:
            self.actions[self.i](context, data)

    def on_fill(self, context, fill):
        self.fills.append(fill)


def run(bars, actions, params=None, history=None, **kw):
    strat = Probe(actions)
    adapter = SDKAdapter(strat, resolve_params(Probe.params, params), history_service=history)
    bt = Backtester(InMemoryFeed(bars), adapter, ZeroCostModel(),
                    max_participation=None, **kw)
    return bt.run(), strat, adapter, bt


B4 = [bar(d, 100, 101, 99, 100) for d in range(1, 5)]


def test_buy_sell_short_cover_map_to_engine_sides():
    captured = []
    actions = [
        lambda c, d: captured.append(c.buy("X", 5)),
        lambda c, d: captured.append(c.sell("X", 5)),
        lambda c, d: captured.append(c.short("X", 3)),
        lambda c, d: captured.append(c.cover("X", 3)),
    ]
    run(B4, actions, initial_cash=10_000, margin_multiplier=2.0)
    assert [o.side for o in captured] == [Side.BUY, Side.SELL, Side.SELL, Side.BUY]
    assert all(o.type is OrderType.MARKET for o in captured)


def test_order_target_quantity_math():
    # Flat -> target 10: BUY 10. Later, long 10 -> target 4: SELL 6.
    captured = []
    actions = [
        lambda c, d: captured.append(c.order_target_quantity("X", 10)),
        None,  # fill lands on bar 2
        lambda c, d: captured.append(c.order_target_quantity("X", 4)),
    ]
    result, strat, _, bt = run(B4, actions, initial_cash=10_000)
    assert captured[0].side is Side.BUY and captured[0].qty == 10
    assert captured[1].side is Side.SELL and captured[1].qty == pytest.approx(6)
    assert bt.portfolio.position_qty("X") == pytest.approx(4)


def test_order_target_quantity_noop_when_at_target():
    captured = []
    actions = [
        lambda c, d: c.order_target_quantity("X", 10),
        None,
        lambda c, d: captured.append(c.order_target_quantity("X", 10)),
    ]
    run(B4, actions, initial_cash=10_000)
    assert captured == [None]


def test_order_target_percent_hand_computed():
    # Bar close 100, equity 10,000, target 50% -> qty = 0.5*10000/100 = 50 BUY.
    captured = []
    actions = [lambda c, d: captured.append(c.order_target_percent("X", 0.5))]
    run(B4, actions, initial_cash=10_000)
    assert captured[0].side is Side.BUY
    assert captured[0].qty == pytest.approx(50.0)


def test_order_target_percent_short_target():
    # Target -30%: qty = -0.3*10000/100 = -30 -> SELL 30 (opens short).
    captured = []
    actions = [lambda c, d: captured.append(c.order_target_percent("X", -0.3))]
    run(B4, actions, initial_cash=10_000, margin_multiplier=2.0)
    assert captured[0].side is Side.SELL
    assert captured[0].qty == pytest.approx(30.0)


def test_cancel_order_via_context():
    holder = {}
    actions = [
        lambda c, d: holder.update(o=c.order("X", Side.BUY, 5, OrderType.LIMIT, limit_price=90)),
        lambda c, d: holder.update(ok=c.cancel_order(holder["o"].id)),
    ]
    result, *_ = run(B4, actions, initial_cash=10_000)
    assert holder["ok"] is True
    assert not result.fills


def test_params_resolved_and_visible():
    _, strat, _, _ = run(B4, [], params={"x": 3})
    assert strat.seen_params == {"x": 3}
    with pytest.raises(ValueError, match="unknown parameters"):
        run(B4, [], params={"typo": 1})
    with pytest.raises(ValueError, match="> max"):
        run(B4, [], params={"x": 99})


def test_context_logging_captured():
    actions = [lambda c, d: c.log("hello")]
    _, _, adapter, _ = run(B4, actions)
    assert len(adapter.logs) == 1
    assert adapter.logs[0].message == "hello"
    assert adapter.logs[0].ts == ts(1)


def test_history_through_context_cannot_see_future():
    # History frame contains ALL 4 daily candles up front (each completing
    # at 21:00 UTC). Execution bars run at 16:00 UTC — mid-session. So on
    # the Jan-2 16:00 execution bar, Jan 2's OWN daily candle is not yet
    # complete: the strategy must see only Jan 1. This is the daily-candle
    # lookahead guard doing its job.
    daily = canon_daily([(d, 100, 101, 99, 100, 1000) for d in range(1, 5)])
    svc = HistoryService({("X", "1d"): daily})
    seen = {}
    actions = [None, lambda c, d: seen.update(h=c.history("X", "1d"))]
    run([bar(d, 100, 101, 99, 100) for d in range(1, 5)], actions, history=svc)
    assert len(seen["h"]) == 1
    assert seen["h"]["ts"].max() == pd.Timestamp(datetime(2024, 1, 1, 21, 0, tzinfo=UTC))


def test_deterministic_sdk_runs():
    daily = canon_daily([(d, 100 + d, 102 + d, 99 + d, 101 + d, 1000) for d in range(1, 8)])
    svc = HistoryService({("X", "1d"): daily})
    bars = [bar(d, 100 + d, 102 + d, 99 + d, 101 + d) for d in range(1, 8)]
    actions = [
        lambda c, d: c.order_target_percent("X", 0.5),
        None, None,
        lambda c, d: c.order_target_quantity("X", 0),
    ]
    r1, *_ = run(bars, actions, history=svc, initial_cash=10_000)
    r2, *_ = run(bars, actions, history=svc, initial_cash=10_000)
    assert r1.equity_curve.equals(r2.equity_curve)
    assert [f.price for f in r1.fills] == [f.price for f in r2.fills]
