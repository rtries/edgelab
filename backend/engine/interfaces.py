"""Protocols defining the engine's plug points."""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Protocol

from engine.types import (
    Bar,
    Fill,
    Order,
    OrderType,
    PortfolioSnapshot,
    Side,
    TimeInForce,
)


class DataFeed(Protocol):
    """Yields bars in non-decreasing global time order. The engine asserts
    per-symbol monotonicity and will raise on out-of-order data."""

    def __iter__(self) -> Iterator[Bar]: ...

    @property
    def symbols(self) -> Sequence[str]: ...


class TradingContext(Protocol):
    """The only mutation surface strategies get. Orders submitted while
    processing bar t become eligible starting with the NEXT bar of that
    symbol; cancels take effect immediately."""

    @property
    def portfolio(self) -> PortfolioSnapshot: ...

    def pending_orders(self, symbol: str | None = None) -> Sequence[Order]: ...

    def submit(
        self,
        symbol: str,
        side: Side,
        qty: float,
        type: OrderType = OrderType.MARKET,
        limit_price: float | None = None,
        stop_price: float | None = None,
        tif: TimeInForce = TimeInForce.GTC,
    ) -> Order: ...

    def cancel(self, order_id: int) -> bool: ...


class Strategy(Protocol):
    def on_start(self, ctx: TradingContext, params: dict) -> None: ...

    def on_bar(self, bar: Bar, ctx: TradingContext) -> None: ...

    def on_fill(self, fill: Fill) -> None: ...


class ExecutionCostModel(Protocol):
    """Prices aggressive vs passive executions and computes commissions."""

    def aggressive_price(self, raw_price: float, side: Side) -> float: ...

    def passive_price(self, raw_price: float, side: Side) -> float: ...

    def commission(self, qty: float) -> float: ...


class RiskModel(Protocol):
    """Pre-trade veto hook, applied at submission before buying-power checks.
    Return None to veto, or the (possibly resized) order to allow."""

    def filter_order(self, order: Order, portfolio: PortfolioSnapshot) -> Order | None: ...


class Clock(Protocol):
    """Injectable time source (real engine uses bar timestamps only)."""

    def now(self) -> datetime: ...
