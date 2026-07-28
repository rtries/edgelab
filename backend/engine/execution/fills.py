"""Single-bar fill simulation.

Given an eligible order and one OHLCV bar, decide whether it executes,
at what raw price, and whether the execution is aggressive or passive.
The caller (Backtester) enforces eligibility (no look-ahead) and volume
participation caps; this module is pure price logic.

Documented assumptions — every one is intentionally conservative:

MARKET     Fills at the bar OPEN (aggressive). Never at a price the bar
           did not trade.

LIMIT buy  If open <= limit: gap in our favor -> fill at OPEN (passive).
           Elif low <= limit: fill at LIMIT (passive). Else no fill.
LIMIT sell Mirror with open >= limit / high >= limit.

STOP buy   Triggers if open >= stop (gap: fill at OPEN — you do NOT get
           the stop price through a gap) else if high >= stop (fill at
           STOP). Aggressive either way.
STOP sell  Mirror with open <= stop / low <= stop.

STOP-LIMIT Trigger latches (order.triggered) exactly like STOP. Once
           triggered it is a limit order. On the triggering bar:
           - gap trigger (open beyond stop): fill at OPEN only if OPEN
             respects the limit, else the order rests as a limit.
           - intrabar trigger: fill at STOP only if STOP respects the
             limit, else it rests. We deliberately do NOT assume any
             favorable intrabar path after the trigger.

ZERO VOLUME  No fill, ever. No liquidity means no execution.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.interfaces import ExecutionCostModel
from engine.types import Bar, Order, OrderType, Side


@dataclass(frozen=True, slots=True)
class FillDecision:
    raw_price: float
    aggressive: bool


def decide_fill(order: Order, bar: Bar) -> FillDecision | None:
    """Pure decision: would this order execute on this bar, and at what
    raw (pre-cost-adjustment) price? Mutates only order.triggered."""
    if bar.volume <= 0:
        return None

    if order.type is OrderType.MARKET:
        return FillDecision(bar.open, aggressive=True)

    if order.type is OrderType.LIMIT:
        price = _limit_price(order.side, order.limit_price, bar)
        return None if price is None else FillDecision(price, aggressive=False)

    if order.type is OrderType.STOP:
        trig = _stop_trigger(order.side, order.stop_price, bar)
        if trig is None:
            return None
        return FillDecision(trig, aggressive=True)

    if order.type is OrderType.STOP_LIMIT:
        assert order.limit_price is not None and order.stop_price is not None
        if order.triggered:
            price = _limit_price(order.side, order.limit_price, bar)
            return None if price is None else FillDecision(price, aggressive=False)

        trig = _stop_trigger(order.side, order.stop_price, bar)
        if trig is None:
            return None
        order.triggered = True
        limit_ok = (
            trig <= order.limit_price if order.side is Side.BUY else trig >= order.limit_price
        )
        if limit_ok:
            return FillDecision(trig, aggressive=True)
        return None  # triggered but limit not marketable -> rests as limit

    raise ValueError(f"unknown order type: {order.type}")


def _limit_price(side: Side, limit: float | None, bar: Bar) -> float | None:
    assert limit is not None, "limit order without limit_price"
    if side is Side.BUY:
        if bar.open <= limit:
            return bar.open
        if bar.low <= limit:
            return limit
    else:
        if bar.open >= limit:
            return bar.open
        if bar.high >= limit:
            return limit
    return None


def _stop_trigger(side: Side, stop: float | None, bar: Bar) -> float | None:
    """Returns the raw execution price if the stop condition is met."""
    assert stop is not None, "stop order without stop_price"
    if side is Side.BUY:
        if bar.open >= stop:
            return bar.open          # gap through the stop
        if bar.high >= stop:
            return stop
    else:
        if bar.open <= stop:
            return bar.open          # gap through the stop
        if bar.low <= stop:
            return stop
    return None


def execution_price(
    decision: FillDecision, side: Side, costs: ExecutionCostModel
) -> float:
    if decision.aggressive:
        return costs.aggressive_price(decision.raw_price, side)
    return costs.passive_price(decision.raw_price, side)
