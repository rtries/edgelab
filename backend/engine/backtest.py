"""Event-driven backtester.

Per-bar sequence (order matters; tests depend on it):

  1. FILLS   Every open order for the bar's symbol, in submission order,
             is tested against this bar — but only if the bar's timestamp
             is strictly AFTER the order's submission bar (no look-ahead).
             DAY orders submitted on an earlier calendar date are
             cancelled before evaluation. Fills are capped by volume
             participation; remainders stay open (PARTIAL).
  2. MARK    The symbol is marked at the bar close; the equity curve and
             exposure flag are recorded at the bar timestamp.
  3. SIGNAL  strategy.on_bar runs. Submissions are validated immediately
             (risk model veto, then buying-power check) and, if accepted,
             become eligible from the NEXT bar of that symbol. Cancels
             take effect immediately.

Determinism: no randomness anywhere in this module; orders carry a
monotonic integer id and are always processed in id order. Identical
inputs produce byte-identical results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from engine.execution.fills import decide_fill, execution_price
from engine.interfaces import DataFeed, ExecutionCostModel, RiskModel, Strategy
from engine.portfolio.accounting import Portfolio
from engine.types import (
    Bar,
    Fill,
    LotMethod,
    Order,
    OrderStatus,
    OrderType,
    RoundTrip,
    Side,
    TimeInForce,
)

_EPS = 1e-9


@dataclass(slots=True)
class BacktestResult:
    equity_curve: pd.Series            # ts -> equity (marked every bar)
    exposure: pd.Series                # ts -> 1.0 if any position open else 0.0
    fills: list[Fill]
    orders: list[Order]
    trades: pd.DataFrame               # one row per RoundTrip
    final_snapshot: object
    metrics: dict = field(default_factory=dict)   # engine/run.py fills this
    manifest: dict | None = None       # reproducibility record (engine/run.py)

    @property
    def trade_pnls(self) -> pd.Series:
        if self.trades.empty:
            return pd.Series(dtype=float)
        return self.trades["net_pnl"]


class _Context:
    """TradingContext implementation handed to strategies."""

    def __init__(self, engine: "Backtester") -> None:
        self._engine = engine

    @property
    def portfolio(self):  # noqa: ANN201
        return self._engine.portfolio.snapshot(self._engine.current_ts)

    def pending_orders(self, symbol: str | None = None) -> list[Order]:
        return [
            o
            for o in self._engine.orders
            if o.is_open and (symbol is None or o.symbol == symbol)
        ]

    def submit(
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

    def cancel(self, order_id: int) -> bool:
        return self._engine.cancel(order_id)


@dataclass(slots=True)
class _Episode:
    symbol: str
    direction: int
    entry_ts: datetime
    entry_qty: float = 0.0
    entry_notional: float = 0.0
    exit_qty: float = 0.0
    exit_notional: float = 0.0
    gross_pnl: float = 0.0
    fees: float = 0.0


class Backtester:
    def __init__(
        self,
        feed: DataFeed,
        strategy: Strategy,
        cost_model: ExecutionCostModel,
        risk_model: RiskModel | None = None,
        initial_cash: float = 100_000.0,
        margin_multiplier: float = 1.0,
        lot_method: LotMethod = LotMethod.FIFO,
        max_participation: float | None = 0.1,
    ) -> None:
        if max_participation is not None and max_participation <= 0:
            raise ValueError("max_participation must be positive or None")
        self.feed = feed
        self.strategy = strategy
        self.cost_model = cost_model
        self.risk_model = risk_model
        self.portfolio = Portfolio(
            initial_cash=initial_cash,
            margin_multiplier=margin_multiplier,
            lot_method=lot_method,
        )
        self.max_participation = max_participation

        self.orders: list[Order] = []
        self.fills: list[Fill] = []
        self.current_ts: datetime | None = None
        self._next_order_id = 1
        self._last_ts_by_symbol: dict[str, datetime] = {}
        self._equity_points: dict[datetime, float] = {}
        self._exposure_points: dict[datetime, float] = {}
        self._episodes: dict[str, _Episode] = {}
        self._round_trips: list[RoundTrip] = []
        self._ctx = _Context(self)

    # ── public API ────────────────────────────────────────────────────
    def run(self, params: dict | None = None) -> BacktestResult:
        self.strategy.on_start(self._ctx, params or {})
        for bar in self.feed:
            self._check_time_order(bar)
            self.current_ts = bar.ts
            self._process_fills(bar)
            self._mark(bar)
            self.strategy.on_bar(bar, self._ctx)
        return self._build_result()

    def submit(
        self,
        symbol: str,
        side: Side,
        qty: float,
        type: OrderType,  # noqa: A002
        limit_price: float | None,
        stop_price: float | None,
        tif: TimeInForce,
    ) -> Order:
        order = Order(
            id=self._next_order_id,
            symbol=symbol,
            side=side,
            qty=qty,
            type=type,
            limit_price=limit_price,
            stop_price=stop_price,
            tif=tif,
            created_ts=self.current_ts,
            eligible_after=self.current_ts,
        )
        self._next_order_id += 1
        self.orders.append(order)
        self._validate(order)
        return order

    def cancel(self, order_id: int) -> bool:
        for order in self.orders:
            if order.id == order_id and order.is_open:
                order.status = OrderStatus.CANCELLED
                return True
        return False

    # ── validation ────────────────────────────────────────────────────
    def _validate(self, order: Order) -> None:
        if order.type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and order.limit_price is None:
            self._reject(order, "limit order requires limit_price")
            return
        if order.type in (OrderType.STOP, OrderType.STOP_LIMIT) and order.stop_price is None:
            self._reject(order, "stop order requires stop_price")
            return

        if self.risk_model is not None:
            snapshot = self.portfolio.snapshot(self.current_ts)
            if self.risk_model.filter_order(order, snapshot) is None:
                self._reject(order, "vetoed by risk model")
                return

        est_price = (
            order.limit_price
            or order.stop_price
            or self.portfolio.last_price.get(order.symbol, 0.0)
        )
        reason = self.portfolio.check_order(order.symbol, order.side, order.qty, est_price)
        if reason is not None:
            self._reject(order, reason)

    def _reject(self, order: Order, reason: str) -> None:
        order.status = OrderStatus.REJECTED
        order.reject_reason = reason

    # ── event loop internals ──────────────────────────────────────────
    def _check_time_order(self, bar: Bar) -> None:
        if bar.ts.tzinfo is None:
            raise ValueError(f"naive timestamp on bar {bar.symbol} {bar.ts}")
        prev = self._last_ts_by_symbol.get(bar.symbol)
        if prev is not None and bar.ts <= prev:
            raise ValueError(
                f"out-of-order bars for {bar.symbol}: {bar.ts} after {prev}"
            )
        if self.current_ts is not None and bar.ts < self.current_ts:
            raise ValueError(f"global time went backwards at {bar.symbol} {bar.ts}")
        self._last_ts_by_symbol[bar.symbol] = bar.ts

    def _process_fills(self, bar: Bar) -> None:
        for order in self.orders:
            if not order.is_open or order.symbol != bar.symbol:
                continue
            # No look-ahead: never fill on the submission bar.
            if order.eligible_after is not None and bar.ts <= order.eligible_after:
                continue
            # DAY orders die on the first bar of a later calendar date.
            if (
                order.tif is TimeInForce.DAY
                and order.created_ts is not None
                and bar.ts.date() > order.created_ts.date()
            ):
                order.status = OrderStatus.CANCELLED
                continue

            decision = decide_fill(order, bar)
            if decision is None:
                continue

            qty = order.remaining
            if self.max_participation is not None:
                qty = min(qty, self.max_participation * bar.volume)
            if qty <= _EPS:
                continue

            price = execution_price(decision, order.side, self.cost_model)
            fees = self.cost_model.commission(qty)
            fill = Fill(
                order_id=order.id,
                symbol=order.symbol,
                side=order.side,
                qty=qty,
                price=price,
                fees=fees,
                ts=bar.ts,
            )
            order.avg_fill_price = (
                order.avg_fill_price * order.filled_qty + price * qty
            ) / (order.filled_qty + qty)
            order.filled_qty += qty
            order.status = (
                OrderStatus.FILLED if order.remaining <= _EPS else OrderStatus.PARTIAL
            )

            result = self.portfolio.apply_fill(fill)
            self.fills.append(fill)
            self._track_round_trip(fill, result)
            self.strategy.on_fill(fill)

    def _mark(self, bar: Bar) -> None:
        self.portfolio.mark(bar.symbol, bar.close)
        self._equity_points[bar.ts] = self.portfolio.equity
        self._exposure_points[bar.ts] = (
            1.0 if self.portfolio.has_open_positions() else 0.0
        )

    # ── round-trip construction ───────────────────────────────────────
    def _track_round_trip(self, fill: Fill, result) -> None:  # noqa: ANN001
        sym = fill.symbol
        episode = self._episodes.get(sym)

        if result.closed_qty > _EPS:
            assert episode is not None, "closing fill without an open episode"
            close_frac = result.closed_qty / fill.qty
            episode.exit_qty += result.closed_qty
            episode.exit_notional += result.closed_qty * fill.price
            episode.gross_pnl += sum(c.pnl for c in result.closed)
            episode.fees += fill.fees * close_frac
            if abs(self.portfolio.position_qty(sym)) <= _EPS or result.opened_qty > _EPS:
                self._close_episode(sym, fill.ts)
                episode = None

        if result.opened_qty > _EPS:
            if episode is None:
                episode = _Episode(
                    symbol=sym,
                    direction=fill.side.sign,
                    entry_ts=fill.ts,
                )
                self._episodes[sym] = episode
            open_frac = result.opened_qty / fill.qty
            episode.entry_qty += result.opened_qty
            episode.entry_notional += result.opened_qty * fill.price
            episode.fees += fill.fees * open_frac

    def _close_episode(self, symbol: str, ts: datetime) -> None:
        ep = self._episodes.pop(symbol)
        self._round_trips.append(
            RoundTrip(
                symbol=ep.symbol,
                direction=ep.direction,
                qty=ep.exit_qty,
                entry_ts=ep.entry_ts,
                exit_ts=ts,
                entry_avg=ep.entry_notional / ep.entry_qty,
                exit_avg=ep.exit_notional / ep.exit_qty,
                gross_pnl=ep.gross_pnl,
                fees=ep.fees,
            )
        )

    # ── results ───────────────────────────────────────────────────────
    def _build_result(self) -> BacktestResult:
        equity = pd.Series(self._equity_points, dtype=float).sort_index()
        exposure = pd.Series(self._exposure_points, dtype=float).sort_index()
        rows = [
            {
                "symbol": rt.symbol,
                "direction": "long" if rt.direction > 0 else "short",
                "qty": rt.qty,
                "entry_ts": rt.entry_ts,
                "exit_ts": rt.exit_ts,
                "entry_avg": rt.entry_avg,
                "exit_avg": rt.exit_avg,
                "gross_pnl": rt.gross_pnl,
                "fees": rt.fees,
                "net_pnl": rt.net_pnl,
            }
            for rt in self._round_trips
        ]
        trades = pd.DataFrame(rows)
        return BacktestResult(
            equity_curve=equity,
            exposure=exposure,
            fills=self.fills,
            orders=self.orders,
            trades=trades,
            final_snapshot=self.portfolio.snapshot(self.current_ts)
            if self.current_ts
            else None,
        )
