"""End-to-end engine tests. Every number traced by hand in comments."""
import pytest

from engine.backtest import Backtester
from engine.data.feeds import InMemoryFeed
from engine.execution.costs import SimpleCostModel, ZeroCostModel
from engine.strategy import ScriptedStrategy
from engine.types import OrderStatus, OrderType, Side, TimeInForce

from tests.helpers import bar, ts

# Costs used in the "with friction" tests:
# slippage 10 bps + spread 20 bps -> aggressive adverse 20 bps (0.2%)
# commission max(1.0, qty * 0.01)
CM = SimpleCostModel(commission_per_share=0.01, min_commission=1.0,
                     slippage_bps=10, spread_bps=20)


def run(bars, script, cost_model=CM, **kw):
    strat = ScriptedStrategy(script)
    bt = Backtester(InMemoryFeed(bars), strat, cost_model, **kw)
    return bt.run(), strat, bt


# ── Fixture A: full long round trip with friction ─────────────────────
def test_long_round_trip_hand_calculated():
    bars = [
        bar(1, 100, 101, 99, 100),
        bar(2, 100, 102, 99.5, 101),
        bar(3, 102, 103, 101, 102),
        bar(4, 103, 104, 102, 103),
    ]
    script = {
        0: lambda b, ctx: ctx.submit("X", Side.BUY, 50),   # fills bar2 open
        1: lambda b, ctx: ctx.submit("X", Side.SELL, 50),  # fills bar3 open
    }
    result, strat, bt = run(bars, script, initial_cash=10_000)

    # Buy fill:  100 * 1.002 = 100.20 ; fee max(1, 0.5) = 1.0
    #   cash = 10000 - 50*100.20 - 1 = 4989
    buy = strat.fills[0]
    assert buy.price == pytest.approx(100.20)
    assert buy.fees == 1.0

    # Equity at bar2 close (101): 4989 + 50*101 = 10039
    assert result.equity_curve[ts(2)] == pytest.approx(10_039.0)

    # Sell fill: 102 * 0.998 = 101.796 ; fee 1.0
    #   cash = 4989 + 50*101.796 - 1 = 10077.8
    sell = strat.fills[1]
    assert sell.price == pytest.approx(101.796)
    assert bt.portfolio.cash == pytest.approx(10_077.80)

    # Realized gross = (101.796 - 100.20) * 50 = 79.80 ; fees 2.0 ; net 77.80
    assert bt.portfolio.realized_pnl == pytest.approx(79.80)
    assert result.equity_curve[ts(4)] == pytest.approx(10_077.80)

    # Round trip row matches
    trade = result.trades.iloc[0]
    assert trade["direction"] == "long"
    assert trade["entry_avg"] == pytest.approx(100.20)
    assert trade["exit_avg"] == pytest.approx(101.796)
    assert trade["gross_pnl"] == pytest.approx(79.80)
    assert trade["fees"] == pytest.approx(2.0)
    assert trade["net_pnl"] == pytest.approx(77.80)

    # Exposure: in-market only on bar 2 (flag at bars 2) -> [0,1,0,0]
    assert list(result.exposure.values) == [0.0, 1.0, 0.0, 0.0]


# ── Fixture B: short round trip ───────────────────────────────────────
def test_short_round_trip_hand_calculated():
    bars = [
        bar(1, 50, 50.5, 49.5, 50),
        bar(2, 50, 50.5, 49, 49.5),    # short fills at 50*0.998 = 49.90
        bar(3, 48, 49, 47.5, 48.5),    # cover fills at 48*1.002 = 48.096
        bar(4, 48.5, 49, 48, 48.5),
    ]
    script = {
        0: lambda b, ctx: ctx.submit("X", Side.SELL, 10),
        1: lambda b, ctx: ctx.submit("X", Side.BUY, 10),
    }
    result, strat, bt = run(bars, script, initial_cash=10_000, margin_multiplier=2.0)

    assert strat.fills[0].price == pytest.approx(49.90)
    # cash = 10000 + 499 - 1 = 10498 ; equity bar2 close (49.5) = 10498 - 495 = 10003
    assert result.equity_curve[ts(2)] == pytest.approx(10_003.0)

    assert strat.fills[1].price == pytest.approx(48.096)
    # cash = 10498 - 480.96 - 1 = 10016.04 ; realized (49.9-48.096)*10 = 18.04
    assert bt.portfolio.cash == pytest.approx(10_016.04)
    assert bt.portfolio.realized_pnl == pytest.approx(18.04)
    trade = result.trades.iloc[0]
    assert trade["direction"] == "short"
    assert trade["net_pnl"] == pytest.approx(16.04)  # 18.04 - 2.0 fees


# ── No look-ahead ─────────────────────────────────────────────────────
def test_order_never_fills_on_submission_bar():
    # Limit buy at 99 submitted DURING bar1 whose low (98) already crosses it.
    # It must NOT fill on bar1. Bar2 never trades below 99.5 -> still open.
    # Bar3 trades to 98 -> fills at 99 on bar3.
    bars = [
        bar(1, 100, 101, 98, 100),
        bar(2, 100, 101, 99.5, 100.5),
        bar(3, 100, 100.5, 98, 99),
    ]
    script = {0: lambda b, ctx: ctx.submit("X", Side.BUY, 10, OrderType.LIMIT, limit_price=99)}
    result, strat, _ = run(bars, script, cost_model=ZeroCostModel(), initial_cash=10_000)
    assert len(strat.fills) == 1
    assert strat.fills[0].ts == ts(3)
    assert strat.fills[0].price == 99.0


def test_strategy_never_sees_future_bars():
    bars = [bar(d, 100, 101, 99, 100) for d in range(1, 5)]
    seen_at_submit = []
    script = {1: lambda b, ctx: seen_at_submit.append(b.ts)}
    _, strat, _ = run(bars, script, initial_cash=10_000)
    # When on_bar for index 1 ran, the strategy had seen exactly bars 1..2.
    assert seen_at_submit == [ts(2)]
    assert [b.ts for b in strat.bars_seen] == [ts(d) for d in range(1, 5)]


# ── Partial fills / liquidity ─────────────────────────────────────────
def test_partial_fills_respect_volume_cap():
    # participation 10%, volume 50 -> max 5 shares per bar.
    # Market buy 12: fills 5 (bar2 @ open 100), 5 (bar3 @ 102), 2 (bar4 @ 104).
    bars = [
        bar(1, 100, 101, 99, 100, v=50),
        bar(2, 100, 101, 99, 100, v=50),
        bar(3, 102, 103, 101, 102, v=50),
        bar(4, 104, 105, 103, 104, v=50),
    ]
    script = {0: lambda b, ctx: ctx.submit("X", Side.BUY, 12)}
    result, strat, bt = run(
        bars, script, cost_model=ZeroCostModel(), initial_cash=10_000, max_participation=0.1
    )
    assert [f.qty for f in strat.fills] == [5, 5, 2]
    assert [f.price for f in strat.fills] == [100, 102, 104]
    order = bt.orders[0]
    assert order.status == OrderStatus.FILLED
    # avg fill = (5*100 + 5*102 + 2*104) / 12 = 1218/12 = 101.5
    assert order.avg_fill_price == pytest.approx(101.5)
    # position: 12 @ avg 101.5 -> cash = 10000 - 1218 = 8782
    assert bt.portfolio.cash == pytest.approx(8_782.0)


def test_no_liquidity_leaves_order_pending():
    bars = [
        bar(1, 100, 101, 99, 100),
        bar(2, 100, 101, 99, 100, v=0),   # halted: no volume
        bar(3, 100, 101, 99, 100),
    ]
    script = {0: lambda b, ctx: ctx.submit("X", Side.BUY, 10)}
    _, strat, _ = run(bars, script, cost_model=ZeroCostModel(), initial_cash=10_000)
    assert len(strat.fills) == 1
    assert strat.fills[0].ts == ts(3)   # skipped the zero-volume bar entirely


# ── Rejection / cancellation ──────────────────────────────────────────
def test_insufficient_buying_power_rejects():
    bars = [bar(1, 50, 51, 49, 50), bar(2, 50, 51, 49, 50)]
    script = {0: lambda b, ctx: ctx.submit("X", Side.BUY, 100)}  # needs 5000 > 1000
    _, strat, bt = run(bars, script, initial_cash=1_000)
    assert bt.orders[0].status == OrderStatus.REJECTED
    assert "insufficient buying power" in bt.orders[0].reject_reason
    assert strat.fills == []


def test_cancel_prevents_fill():
    bars = [
        bar(1, 100, 101, 99, 100),
        bar(2, 100, 101, 99, 100),      # cancel happens here
        bar(3, 100, 101, 94, 95),       # would have filled the limit
    ]
    holder = {}
    script = {
        0: lambda b, ctx: holder.update(
            o=ctx.submit("X", Side.BUY, 10, OrderType.LIMIT, limit_price=95)
        ),
        1: lambda b, ctx: ctx.cancel(holder["o"].id),
    }
    _, strat, bt = run(bars, script, initial_cash=10_000)
    assert bt.orders[0].status == OrderStatus.CANCELLED
    assert strat.fills == []


def test_day_order_expires_next_date():
    bars = [
        bar(1, 100, 101, 99, 100),
        bar(2, 100, 101, 94, 95),       # next calendar day: DAY order dead
    ]
    script = {
        0: lambda b, ctx: ctx.submit(
            "X", Side.BUY, 10, OrderType.LIMIT, limit_price=95, tif=TimeInForce.DAY
        )
    }
    _, strat, bt = run(bars, script, initial_cash=10_000)
    assert bt.orders[0].status == OrderStatus.CANCELLED
    assert strat.fills == []


# ── Protective stop with a gap open ───────────────────────────────────
def test_gap_through_protective_stop():
    # Long 10 @ 100 (zero costs). Stop sell at 95.
    # Bar4 gaps to open 90: stop fills at 90, NOT 95.
    # Realized = (90 - 100) * 10 = -100.
    bars = [
        bar(1, 100, 101, 99, 100),
        bar(2, 100, 101, 99, 100),     # entry fill @ 100
        bar(3, 100, 101, 97, 98),      # stop submitted after entry; not touched... low 97 > 95? yes
        bar(4, 90, 91, 88, 89),        # gap!
    ]
    script = {
        0: lambda b, ctx: ctx.submit("X", Side.BUY, 10),
        1: lambda b, ctx: ctx.submit("X", Side.SELL, 10, OrderType.STOP, stop_price=95),
    }
    result, strat, bt = run(bars, script, cost_model=ZeroCostModel(), initial_cash=10_000)
    assert strat.fills[1].price == 90.0
    assert bt.portfolio.realized_pnl == pytest.approx(-100.0)
    assert result.trades.iloc[0]["net_pnl"] == pytest.approx(-100.0)


# ── Multi-asset ───────────────────────────────────────────────────────
def test_multi_asset_marking_and_orders():
    # Zero costs. Buy 10 X and 5 Y on bar index 0/1; verify per-symbol fills
    # and combined equity at the end.
    bars = [
        bar(1, 100, 101, 99, 100, sym="X"),
        bar(1, 200, 201, 199, 200, sym="Y"),
        bar(2, 100, 101, 99, 100, sym="X"),   # X fill @ 100
        bar(2, 200, 201, 199, 200, sym="Y"),  # Y fill @ 200
        bar(3, 110, 111, 109, 110, sym="X"),  # X marks 110
        bar(3, 190, 191, 189, 190, sym="Y"),  # Y marks 190
    ]
    script = {
        0: lambda b, ctx: ctx.submit("X", Side.BUY, 10),
        1: lambda b, ctx: ctx.submit("Y", Side.SELL, 5),
    }
    result, strat, bt = run(bars, script, cost_model=ZeroCostModel(), initial_cash=10_000, margin_multiplier=2.0)
    assert {f.symbol for f in strat.fills} == {"X", "Y"}
    # cash = 10000 - 1000 + 1000 = 10000
    # equity = 10000 + 10*110 - 5*190 = 10000 + 1100 - 950 = 10150
    assert bt.portfolio.equity == pytest.approx(10_150.0)
    assert result.equity_curve[ts(3)] == pytest.approx(10_150.0)


# ── Determinism ───────────────────────────────────────────────────────
def test_identical_runs_produce_identical_results():
    bars = [bar(d, 100 + d, 101 + d, 99 + d, 100 + d) for d in range(1, 8)]
    script = {
        0: lambda b, ctx: ctx.submit("X", Side.BUY, 10),
        3: lambda b, ctx: ctx.submit("X", Side.SELL, 10),
    }
    r1, _, _ = run(bars, dict(script), initial_cash=10_000)
    r2, _, _ = run(bars, dict(script), initial_cash=10_000)
    assert r1.equity_curve.equals(r2.equity_curve)
    assert r1.trades.equals(r2.trades)
    assert [f.price for f in r1.fills] == [f.price for f in r2.fills]


# ── Feed integrity ────────────────────────────────────────────────────
def test_out_of_order_bars_raise():
    class BadFeed:
        symbols = ["X"]
        def __iter__(self):
            yield bar(2, 100, 101, 99, 100)
            yield bar(1, 100, 101, 99, 100)
    bt = Backtester(BadFeed(), ScriptedStrategy({}), ZeroCostModel())
    with pytest.raises(ValueError, match="out-of-order"):
        bt.run()


# ── Partial exit keeps episode open ───────────────────────────────────
def test_partial_exit_single_round_trip():
    # Buy 10 @ 100; sell 4 @ 110; sell 6 @ 120 (zero costs).
    # One round trip: qty 10, exit_avg = (4*110 + 6*120)/10 = 116.
    # gross = (110-100)*4 + (120-100)*6 = 40 + 120 = 160.
    bars = [
        bar(1, 100, 101, 99, 100),
        bar(2, 100, 101, 99, 100),
        bar(3, 110, 111, 109, 110),
        bar(4, 120, 121, 119, 120),
    ]
    script = {
        0: lambda b, ctx: ctx.submit("X", Side.BUY, 10),
        1: lambda b, ctx: ctx.submit("X", Side.SELL, 4),
        2: lambda b, ctx: ctx.submit("X", Side.SELL, 6),
    }
    result, _, _ = run(bars, script, cost_model=ZeroCostModel(), initial_cash=10_000)
    assert len(result.trades) == 1
    t = result.trades.iloc[0]
    assert t["qty"] == pytest.approx(10)
    assert t["exit_avg"] == pytest.approx(116.0)
    assert t["gross_pnl"] == pytest.approx(160.0)


# ── Flip produces two round trips ─────────────────────────────────────
def test_flip_splits_into_two_round_trips():
    # Buy 5 @ 100; sell 8 @ 110 (closes 5 long, opens 3 short);
    # buy 3 @ 105 (closes short). Zero costs.
    # RT1: long 5, pnl (110-100)*5 = 50.
    # RT2: short 3 @ 110 covered @ 105, pnl (110-105)*3 = 15.
    bars = [
        bar(1, 100, 101, 99, 100),
        bar(2, 100, 101, 99, 100),
        bar(3, 110, 111, 109, 110),
        bar(4, 105, 106, 104, 105),
        bar(5, 105, 106, 104, 105),
    ]
    script = {
        0: lambda b, ctx: ctx.submit("X", Side.BUY, 5),
        1: lambda b, ctx: ctx.submit("X", Side.SELL, 8),
        2: lambda b, ctx: ctx.submit("X", Side.BUY, 3),
    }
    result, _, bt = run(bars, script, cost_model=ZeroCostModel(),
                        initial_cash=10_000, margin_multiplier=2.0)
    assert len(result.trades) == 2
    rt1, rt2 = result.trades.iloc[0], result.trades.iloc[1]
    assert rt1["direction"] == "long" and rt1["gross_pnl"] == pytest.approx(50.0)
    assert rt2["direction"] == "short" and rt2["gross_pnl"] == pytest.approx(15.0)
    assert bt.portfolio.realized_pnl == pytest.approx(65.0)
    assert not bt.portfolio.has_open_positions()
