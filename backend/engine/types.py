"""Core value types shared across the engine.

Conventions (load-bearing — tests assume these):
- Order side is BUY/SELL (an action), not long/short (a state). Selling can
  close a long or open a short; the lot book decides.
- Position quantity is signed: positive = long, negative = short.
- All timestamps are timezone-aware.
- Quantities are floats (fractional shares supported); money is float for
  Phase 1 with explicit tolerance in tests (Decimal ledger is a later,
  isolated upgrade behind the same interfaces).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime


class Side(enum.StrEnum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


class OrderType(enum.StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(enum.StrEnum):
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class TimeInForce(enum.StrEnum):
    GTC = "gtc"   # rests until filled or cancelled
    DAY = "day"   # cancelled on the first bar of a later calendar date


class LotMethod(enum.StrEnum):
    FIFO = "fifo"
    LIFO = "lifo"


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(slots=True)
class Order:
    """Engine-owned order state. Strategies create orders only via
    TradingContext.submit(), which assigns ids and enforces validation."""

    id: int
    symbol: str
    side: Side
    qty: float
    type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    tif: TimeInForce = TimeInForce.GTC
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    created_ts: datetime | None = None
    # No-look-ahead gate: the order may only fill on bars with ts strictly
    # greater than this (set to the bar on which it was submitted).
    eligible_after: datetime | None = None
    # Stop-limit: latched once the stop condition has been touched.
    triggered: bool = False
    reject_reason: str | None = None

    @property
    def remaining(self) -> float:
        return self.qty - self.filled_qty

    @property
    def is_open(self) -> bool:
        return self.status in (OrderStatus.PENDING, OrderStatus.PARTIAL)


@dataclass(frozen=True, slots=True)
class Fill:
    order_id: int
    symbol: str
    side: Side
    qty: float
    price: float   # execution price after slippage/spread adjustments
    fees: float
    ts: datetime


@dataclass(frozen=True, slots=True)
class ClosedLot:
    """One lot (or lot fraction) consumed by an opposing fill."""

    qty: float          # positive
    entry_price: float
    exit_price: float
    entry_ts: datetime
    exit_ts: datetime
    direction: int      # +1 the lot was long, -1 the lot was short

    @property
    def pnl(self) -> float:
        """Gross P&L (fees are accounted separately at the portfolio level)."""
        return (self.exit_price - self.entry_price) * self.qty * self.direction


@dataclass(frozen=True, slots=True)
class RoundTrip:
    """A flat-to-flat position episode, built from fills + closed lots."""

    symbol: str
    direction: int              # +1 long episode, -1 short episode
    qty: float                  # total quantity closed over the episode
    entry_ts: datetime
    exit_ts: datetime
    entry_avg: float
    exit_avg: float
    gross_pnl: float
    fees: float

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.fees


@dataclass(slots=True)
class PositionView:
    """Read-only snapshot of one symbol's position, given to strategies."""

    symbol: str
    qty: float          # signed
    avg_price: float
    unrealized_pnl: float

    @property
    def is_flat(self) -> bool:
        return abs(self.qty) < 1e-12


@dataclass(slots=True)
class PortfolioSnapshot:
    """What the strategy sees each bar. Never contains future data."""

    ts: datetime
    cash: float
    equity: float
    buying_power: float
    long_value: float
    short_value: float
    realized_pnl: float
    unrealized_pnl: float
    total_fees: float
    positions: dict[str, PositionView] = field(default_factory=dict)

    @property
    def gross_exposure(self) -> float:
        return self.long_value + self.short_value
