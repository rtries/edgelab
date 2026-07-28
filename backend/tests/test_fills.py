"""Fill decision logic: every order type, gaps, and no-liquidity cases."""
import pytest

from engine.execution.costs import SimpleCostModel
from engine.execution.fills import decide_fill, execution_price
from engine.types import Order, OrderType, Side

from tests.helpers import bar


def make(side: Side, otype: OrderType, limit=None, stop=None) -> Order:
    return Order(id=1, symbol="X", side=side, qty=10, type=otype,
                 limit_price=limit, stop_price=stop)


def test_market_fills_at_open():
    d = decide_fill(make(Side.BUY, OrderType.MARKET), bar(2, 100, 102, 99, 101))
    assert d is not None and d.raw_price == 100 and d.aggressive


def test_zero_volume_never_fills():
    b = bar(2, 100, 102, 99, 101, v=0)
    for otype, kw in [
        (OrderType.MARKET, {}),
        (OrderType.LIMIT, {"limit": 101}),
        (OrderType.STOP, {"stop": 99}),
    ]:
        assert decide_fill(make(Side.BUY, otype, **kw), b) is None


def test_limit_buy_fills_at_limit_intrabar():
    # Limit 99.5; bar opens 100, trades down to 99 -> fill at 99.5 exactly.
    d = decide_fill(make(Side.BUY, OrderType.LIMIT, limit=99.5), bar(2, 100, 101, 99, 100))
    assert d is not None and d.raw_price == 99.5 and not d.aggressive


def test_limit_buy_favorable_gap_fills_at_open():
    # Limit 100; bar opens at 98 (gap down through the limit) -> fill at 98,
    # BETTER than the limit. Passive fills never fill worse than the limit.
    d = decide_fill(make(Side.BUY, OrderType.LIMIT, limit=100), bar(2, 98, 99, 97, 98.5))
    assert d is not None and d.raw_price == 98


def test_limit_buy_no_touch_no_fill():
    d = decide_fill(make(Side.BUY, OrderType.LIMIT, limit=95), bar(2, 100, 102, 99, 101))
    assert d is None


def test_limit_sell_mirror():
    d = decide_fill(make(Side.SELL, OrderType.LIMIT, limit=101.5), bar(2, 100, 102, 99, 101))
    assert d is not None and d.raw_price == 101.5
    d2 = decide_fill(make(Side.SELL, OrderType.LIMIT, limit=100), bar(2, 103, 104, 102, 103.5))
    assert d2 is not None and d2.raw_price == 103  # favorable gap up


def test_stop_sell_gap_fills_at_open_not_stop():
    # THE gap case: protective stop at 95, market opens at 90.
    # You get 90 (the open), NOT your stop price.
    d = decide_fill(make(Side.SELL, OrderType.STOP, stop=95), bar(2, 90, 91, 88, 89))
    assert d is not None and d.raw_price == 90 and d.aggressive


def test_stop_sell_intrabar_fills_at_stop():
    d = decide_fill(make(Side.SELL, OrderType.STOP, stop=95), bar(2, 97, 98, 94, 96))
    assert d is not None and d.raw_price == 95


def test_stop_buy_gap_and_intrabar():
    gap = decide_fill(make(Side.BUY, OrderType.STOP, stop=105), bar(2, 108, 109, 107, 108))
    assert gap is not None and gap.raw_price == 108
    intra = decide_fill(make(Side.BUY, OrderType.STOP, stop=105), bar(2, 103, 106, 102, 105.5))
    assert intra is not None and intra.raw_price == 105


def test_stop_not_touched_no_fill():
    assert decide_fill(make(Side.SELL, OrderType.STOP, stop=90), bar(2, 100, 102, 95, 101)) is None


def test_stop_limit_buy_intrabar_fill():
    # stop 105, limit 106: intrabar trigger at 105 <= 106 -> fill at 105.
    o = make(Side.BUY, OrderType.STOP_LIMIT, limit=106, stop=105)
    d = decide_fill(o, bar(2, 103, 106, 102, 105))
    assert d is not None and d.raw_price == 105 and o.triggered


def test_stop_limit_buy_gap_beyond_limit_rests():
    # stop 105, limit 106: opens at 108 (beyond limit) -> triggered, NO fill.
    o = make(Side.BUY, OrderType.STOP_LIMIT, limit=106, stop=105)
    assert decide_fill(o, bar(2, 108, 110, 107, 109)) is None
    assert o.triggered
    # Later bar trades back to 106 -> now fills as a plain limit at 106.
    d = decide_fill(o, bar(3, 107, 108, 105.5, 106))
    assert d is not None and d.raw_price == 106 and not d.aggressive


def test_cost_model_adjustments():
    # slippage 10 bps + spread 20 bps -> aggressive adverse = 10 + 10 = 20 bps.
    cm = SimpleCostModel(commission_per_share=0.01, min_commission=1.0,
                         slippage_bps=10, spread_bps=20)
    assert cm.aggressive_price(100.0, Side.BUY) == pytest.approx(100.20)
    assert cm.aggressive_price(100.0, Side.SELL) == pytest.approx(99.80)
    assert cm.passive_price(100.0, Side.BUY) == 100.0
    # commission: max(1.0, 50 * 0.01) = 1.0 ; max(1.0, 500 * 0.01) = 5.0
    assert cm.commission(50) == 1.0
    assert cm.commission(500) == 5.0


def test_execution_price_uses_aggressive_only_when_flagged():
    cm = SimpleCostModel(slippage_bps=10, spread_bps=20)
    d = decide_fill(make(Side.BUY, OrderType.LIMIT, limit=99.5), bar(2, 100, 101, 99, 100))
    assert execution_price(d, Side.BUY, cm) == 99.5  # passive: untouched
    dm = decide_fill(make(Side.BUY, OrderType.MARKET), bar(2, 100, 101, 99, 100))
    assert execution_price(dm, Side.BUY, cm) == pytest.approx(100.20)
