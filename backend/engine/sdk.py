"""Strategy SDK — the developer-facing layer over the Phase 1 engine.

    class MyStrategy(SDKStrategy):
        params = [Param("fast", "int", 5, min=2, max=50)]

        def initialize(self, context): ...
        def on_bar(self, context, data): ...   # data = the current Bar

SDKAdapter translates this to the frozen Phase 1 Strategy protocol without
touching engine semantics. The Context exposes ONLY point-in-time state:
- history() is clamped to context.now by construction (a request for
  future data is structurally impossible, not just discouraged);
- prices used for target sizing are the latest COMPLETED bar closes the
  adapter has itself observed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from engine.data.history import HistoryService
from engine.data.schema_types import Timeframe
from engine.interfaces import TradingContext
from engine.strategy import BaseStrategy
from engine.types import Bar, Fill, Order, OrderType, PortfolioSnapshot, Side, TimeInForce

_EPS = 1e-9
logger = logging.getLogger("engine.sdk")


@dataclass(slots=True)
class LogRecord:
    ts: datetime
    message: str


class Context:
    """Everything a strategy may see or do. Built fresh each callback."""

    def __init__(self, adapter: "SDKAdapter", engine_ctx: TradingContext) -> None:
        self._adapter = adapter
        self._engine = engine_ctx

    # ── state ─────────────────────────────────────────────────────────
    @property
    def now(self) -> datetime:
        return self._adapter.now

    @property
    def portfolio(self) -> PortfolioSnapshot:
        return self._engine.portfolio

    @property
    def positions(self) -> dict:
        return self._engine.portfolio.positions

    @property
    def open_orders(self) -> list[Order]:
        return list(self._engine.pending_orders())

    @property
    def params(self) -> dict:
        return dict(self._adapter.params)

    def last_price(self, symbol: str) -> float | None:
        return self._adapter.last_close.get(symbol)

    def history(
        self, symbol: str, timeframe: Timeframe | str, n: int | None = None
    ) -> pd.DataFrame:
        """Completed bars only, as of `now`. Cannot return the future."""
        if self._adapter.history_service is None:
            raise RuntimeError("no HistoryService configured for this run")
        return self._adapter.history_service.history(symbol, timeframe, self.now, n)

    def log(self, message: str) -> None:
        self._adapter.logs.append(LogRecord(ts=self.now, message=str(message)))
        logger.info("[%s] %s", self.now, message)

    # ── orders ────────────────────────────────────────────────────────
    def order(
        self,
        symbol: str,
        side: Side,
        qty: float,
        type: OrderType = OrderType.MARKET,  # noqa: A002
        limit_price: float | None = None,
        stop_price: float | None = None,
        tif: TimeInForce = TimeInForce.GTC,
    ) -> Order:
        return self._engine.submit(symbol, side, qty, type, limit_price, stop_price, tif)

    def buy(self, symbol: str, qty: float, **kw) -> Order:
        """Buy to open (or to cover — the lot book resolves intent)."""
        return self.order(symbol, Side.BUY, qty, **kw)

    def sell(self, symbol: str, qty: float, **kw) -> Order:
        """Sell to close a long."""
        return self.order(symbol, Side.SELL, qty, **kw)

    def short(self, symbol: str, qty: float, **kw) -> Order:
        """Sell to open a short (identical engine side as sell; named for intent)."""
        return self.order(symbol, Side.SELL, qty, **kw)

    def cover(self, symbol: str, qty: float, **kw) -> Order:
        """Buy to close a short."""
        return self.order(symbol, Side.BUY, qty, **kw)

    def cancel_order(self, order_id: int) -> bool:
        return self._engine.cancel(order_id)

    def order_target_quantity(self, symbol: str, target: float) -> Order | None:
        """Market order sizing the position to `target` signed shares.
        delta = target - current; None if already there."""
        current = self.positions[symbol].qty if symbol in self.positions else 0.0
        delta = target - current
        if abs(delta) <= _EPS:
            return None
        side = Side.BUY if delta > 0 else Side.SELL
        return self.order(symbol, side, abs(delta))

    def order_target_percent(self, symbol: str, pct: float) -> Order | None:
        """Target |position value| = pct * equity (signed: -0.5 = 50% short).
        Uses the latest completed close; qty = pct * equity / price."""
        price = self.last_price(symbol)
        if price is None or price <= 0:
            raise RuntimeError(f"no completed bar seen yet for {symbol}; cannot size")
        target_qty = pct * self.portfolio.equity / price
        return self.order_target_quantity(symbol, target_qty)


class SDKStrategy:
    """Subclass and override. `params` declares typed parameters."""

    params: list = []

    def initialize(self, context: Context) -> None:  # noqa: ARG002
        return None

    def on_bar(self, context: Context, data: Bar) -> None:  # noqa: ARG002
        return None

    def on_fill(self, context: Context, fill: Fill) -> None:  # noqa: ARG002
        return None


class SDKAdapter(BaseStrategy):
    """Bridges SDKStrategy onto the frozen Phase 1 Strategy protocol."""

    def __init__(
        self,
        strategy: SDKStrategy,
        params: dict,
        history_service: HistoryService | None = None,
    ) -> None:
        self.strategy = strategy
        self.params = params
        self.history_service = history_service
        self.now: datetime | None = None
        self.last_close: dict[str, float] = {}
        self.logs: list[LogRecord] = []
        self._engine_ctx: TradingContext | None = None

    def on_start(self, ctx: TradingContext, params: dict) -> None:  # noqa: ARG002
        self._engine_ctx = ctx
        self.strategy.initialize(Context(self, ctx))

    def on_bar(self, bar: Bar, ctx: TradingContext) -> None:
        self._engine_ctx = ctx
        self.now = bar.ts
        self.last_close[bar.symbol] = bar.close
        self.strategy.on_bar(Context(self, ctx), bar)

    def on_fill(self, fill: Fill) -> None:
        if self._engine_ctx is not None:
            self.strategy.on_fill(Context(self, self._engine_ctx), fill)
