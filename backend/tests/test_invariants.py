"""Engine-wide invariants under messy (but deterministic) order flow.

These are not fixture tests — they assert structural truths that must
survive any refactor:

  I1  equity == initial_cash + realized_pnl + unrealized_pnl - total_fees
      at EVERY bar, mid-run, as observed by the strategy itself.
  I2  A flat portfolio's equity equals its cash exactly.
  I3  Filled + remaining quantity always reconciles per order.
"""
import itertools

import pytest

from engine.backtest import Backtester
from engine.data.feeds import InMemoryFeed
from engine.execution.costs import SimpleCostModel
from engine.strategy import BaseStrategy
from engine.types import OrderType, Side

from tests.helpers import bar


class ChaoticAuditor(BaseStrategy):
    """Fires a rotating mix of order types and audits identity I1 on the
    snapshot it receives each bar."""

    def __init__(self) -> None:
        self.initial_cash: float | None = None
        self.violations: list[str] = []
        self._actions = itertools.cycle(
            [
                lambda ctx, s: ctx.submit(s, Side.BUY, 7),
                lambda ctx, s: ctx.submit(s, Side.SELL, 11, OrderType.LIMIT, limit_price=999.0),
                lambda ctx, s: ctx.submit(s, Side.SELL, 12),
                lambda ctx, s: ctx.submit(s, Side.BUY, 3, OrderType.STOP, stop_price=1.0),
                lambda ctx, s: ctx.submit(s, Side.SELL, 5, OrderType.STOP, stop_price=1e9),
            ]
        )

    def on_start(self, ctx, params) -> None:  # noqa: ANN001
        self.initial_cash = ctx.portfolio.cash

    def on_bar(self, b, ctx) -> None:  # noqa: ANN001
        next(self._actions)(ctx, b.symbol)
        snap = ctx.portfolio
        identity = (
            self.initial_cash + snap.realized_pnl + snap.unrealized_pnl - snap.total_fees
        )
        if abs(snap.equity - identity) > 1e-6:
            self.violations.append(f"{b.ts}: equity {snap.equity} != identity {identity}")


def _bars():
    prices = [100, 103, 101, 98, 104, 107, 102, 99, 101, 105, 108, 103, 97, 100, 106]
    return [bar(d + 1, p, p * 1.02, p * 0.98, p * 1.01) for d, p in enumerate(prices)]


def test_identity_holds_every_bar_under_chaotic_flow():
    strat = ChaoticAuditor()
    bt = Backtester(
        InMemoryFeed(_bars()),
        strat,
        SimpleCostModel(),
        initial_cash=50_000,
        margin_multiplier=2.0,
    )
    bt.run()
    assert strat.violations == []
    # I2: if flat at the end, equity == cash
    if not bt.portfolio.has_open_positions():
        assert bt.portfolio.equity == pytest.approx(bt.portfolio.cash)


def test_order_quantities_reconcile():
    strat = ChaoticAuditor()
    bt = Backtester(
        InMemoryFeed(_bars()),
        strat,
        SimpleCostModel(),
        initial_cash=50_000,
        margin_multiplier=2.0,
    )
    result = bt.run()
    for order in result.orders:
        assert order.filled_qty <= order.qty + 1e-9
        assert order.filled_qty == pytest.approx(
            sum(f.qty for f in result.fills if f.order_id == order.id)
        )
    # Every fill maps to a real order
    order_ids = {o.id for o in result.orders}
    assert all(f.order_id in order_ids for f in result.fills)
