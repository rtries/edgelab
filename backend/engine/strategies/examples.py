"""Example strategies — ENGINE VERIFICATION ONLY.

These exist to exercise the SDK, indicators, and engine deterministically.
They are not trading advice, carry no claim of profitability, and were
chosen for having easily hand-checkable behavior on synthetic fixtures.
"""
from __future__ import annotations

from collections import deque

from engine.indicators.incremental import (
    IncrementalATR,
    IncrementalRSI,
    IncrementalSMA,
)
from engine.params import Param
from engine.sdk import Context, SDKStrategy
from engine.types import Bar


class BuyAndHold(SDKStrategy):
    """Buys a target percent of equity on the first completed bar and holds."""

    params = [
        Param("invest_pct", "float", 0.95, min=0.0, max=1.0,
              description="fraction of equity to hold"),
    ]

    def initialize(self, context: Context) -> None:
        self._entered: set[str] = set()

    def on_bar(self, context: Context, data: Bar) -> None:
        if data.symbol not in self._entered:
            self._entered.add(data.symbol)
            context.order_target_percent(data.symbol, context.params["invest_pct"])


class MACrossover(SDKStrategy):
    """Long when fast SMA > slow SMA, flat otherwise. Acts on crossings."""

    params = [
        Param("fast", "int", 5, min=2, max=200, step=1, description="fast SMA length"),
        Param("slow", "int", 10, min=3, max=400, step=1, description="slow SMA length"),
        Param("invest_pct", "float", 0.9, min=0.0, max=1.0),
    ]

    def initialize(self, context: Context) -> None:
        p = context.params
        if p["fast"] >= p["slow"]:
            raise ValueError("fast must be < slow")
        self._fast: dict[str, IncrementalSMA] = {}
        self._slow: dict[str, IncrementalSMA] = {}
        self._above: dict[str, bool | None] = {}

    def on_bar(self, context: Context, data: Bar) -> None:
        p = context.params
        sym = data.symbol
        fast = self._fast.setdefault(sym, IncrementalSMA(p["fast"])).update(data.close)
        slow = self._slow.setdefault(sym, IncrementalSMA(p["slow"])).update(data.close)
        if fast is None or slow is None:
            return
        above = fast > slow
        prev = self._above.get(sym)
        self._above[sym] = above
        if prev is None or above == prev:
            return
        if above:
            context.log(f"{sym}: fast crossed above slow -> long")
            context.order_target_percent(sym, p["invest_pct"])
        else:
            context.log(f"{sym}: fast crossed below slow -> flat")
            context.order_target_quantity(sym, 0.0)


class RSIMeanReversion(SDKStrategy):
    """Long when Wilder RSI < entry level; flat when RSI > exit level."""

    params = [
        Param("period", "int", 14, min=2, max=100),
        Param("entry", "float", 30.0, min=1.0, max=50.0),
        Param("exit", "float", 55.0, min=50.0, max=99.0),
        Param("invest_pct", "float", 0.9, min=0.0, max=1.0),
    ]

    def initialize(self, context: Context) -> None:
        self._rsi: dict[str, IncrementalRSI] = {}

    def on_bar(self, context: Context, data: Bar) -> None:
        p = context.params
        sym = data.symbol
        value = self._rsi.setdefault(sym, IncrementalRSI(p["period"])).update(data.close)
        if value is None:
            return
        holding = sym in context.positions and context.positions[sym].qty > 0
        if not holding and value < p["entry"]:
            context.order_target_percent(sym, p["invest_pct"])
        elif holding and value > p["exit"]:
            context.order_target_quantity(sym, 0.0)


class VolatilityBreakout(SDKStrategy):
    """Enters long when close exceeds the prior `lookback`-bar high; exits
    on an ATR trailing stop below the highest close since entry."""

    params = [
        Param("lookback", "int", 10, min=2, max=200),
        Param("atr_period", "int", 5, min=2, max=100),
        Param("atr_mult", "float", 2.0, min=0.5, max=10.0),
        Param("invest_pct", "float", 0.9, min=0.0, max=1.0),
    ]

    def initialize(self, context: Context) -> None:
        self._highs: dict[str, deque] = {}
        self._atr: dict[str, IncrementalATR] = {}
        self._peak: dict[str, float] = {}

    def on_bar(self, context: Context, data: Bar) -> None:
        p = context.params
        sym = data.symbol
        highs = self._highs.setdefault(sym, deque(maxlen=p["lookback"]))
        atr_value = self._atr.setdefault(sym, IncrementalATR(p["atr_period"])).update(
            data.high, data.low, data.close
        )
        prior_high = max(highs) if len(highs) == p["lookback"] else None
        holding = sym in context.positions and context.positions[sym].qty > 0

        if holding:
            self._peak[sym] = max(self._peak.get(sym, data.close), data.close)
            if atr_value is not None and data.close < self._peak[sym] - p["atr_mult"] * atr_value:
                context.log(f"{sym}: ATR trailing stop hit -> flat")
                context.order_target_quantity(sym, 0.0)
                self._peak.pop(sym, None)
        elif prior_high is not None and atr_value is not None and data.close > prior_high:
            context.log(f"{sym}: breakout above {prior_high:.4f} -> long")
            context.order_target_percent(sym, p["invest_pct"])
            self._peak[sym] = data.close

        highs.append(data.high)
