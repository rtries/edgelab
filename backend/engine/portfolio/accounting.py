"""Portfolio ledger: cash, positions, margin, buying power, P&L.

Accounting identities (asserted in tests, hold at every bar):
    equity        = cash + long_value - short_value
    equity        = initial_cash + realized_pnl + unrealized_pnl - total_fees
    long_value    = sum over long positions of  qty * last_price
    short_value   = sum over short positions of |qty| * last_price
    buying_power  = max(0, margin_multiplier * equity - gross_exposure)

Cash mechanics per fill (side.sign = +1 buy / -1 sell):
    cash -= sign * qty * price      (short sale proceeds are credited)
    cash -= fees

Realized P&L is GROSS of fees; fees accumulate separately so the second
identity above stays exact and fee drag is always visible.

Buying-power checks happen at ORDER SUBMISSION (engine-side estimate) and
only against the exposure-INCREASING portion of an order — closing or
reducing a position is always allowed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from engine.portfolio.lots import ApplyResult, LotBook
from engine.types import (
    Fill,
    LotMethod,
    PortfolioSnapshot,
    PositionView,
    Side,
)

_EPS = 1e-9


@dataclass(slots=True)
class Portfolio:
    initial_cash: float
    margin_multiplier: float = 1.0           # 1.0 = cash account, 2.0 = Reg-T style
    lot_method: LotMethod = LotMethod.FIFO

    cash: float = 0.0
    realized_pnl: float = 0.0
    total_fees: float = 0.0
    books: dict[str, LotBook] = field(default_factory=dict)
    last_price: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.cash = self.initial_cash

    # ── prices ────────────────────────────────────────────────────────
    def mark(self, symbol: str, price: float) -> None:
        self.last_price[symbol] = price

    # ── fills ─────────────────────────────────────────────────────────
    def apply_fill(self, fill: Fill) -> ApplyResult:
        book = self.books.setdefault(fill.symbol, LotBook(method=self.lot_method))
        self.cash -= fill.side.sign * fill.qty * fill.price
        self.cash -= fill.fees
        self.total_fees += fill.fees
        result = book.apply(fill.side, fill.qty, fill.price, fill.ts)
        self.realized_pnl += result.realized_pnl
        self.last_price.setdefault(fill.symbol, fill.price)
        return result

    # ── valuation ─────────────────────────────────────────────────────
    def position_qty(self, symbol: str) -> float:
        book = self.books.get(symbol)
        return 0.0 if book is None else book.qty

    @property
    def long_value(self) -> float:
        return sum(
            book.qty * self.last_price[sym]
            for sym, book in self.books.items()
            if book.qty > _EPS
        )

    @property
    def short_value(self) -> float:
        return sum(
            -book.qty * self.last_price[sym]
            for sym, book in self.books.items()
            if book.qty < -_EPS
        )

    @property
    def gross_exposure(self) -> float:
        return self.long_value + self.short_value

    @property
    def unrealized_pnl(self) -> float:
        return sum(
            book.unrealized_pnl(self.last_price[sym])
            for sym, book in self.books.items()
            if abs(book.qty) > _EPS
        )

    @property
    def equity(self) -> float:
        return self.cash + self.long_value - self.short_value

    @property
    def buying_power(self) -> float:
        return max(0.0, self.margin_multiplier * self.equity - self.gross_exposure)

    def has_open_positions(self) -> bool:
        return any(abs(book.qty) > _EPS for book in self.books.values())

    # ── pre-trade check ───────────────────────────────────────────────
    def check_order(
        self, symbol: str, side: Side, qty: float, est_price: float
    ) -> str | None:
        """Returns a rejection reason, or None if the order is acceptable.
        Only the exposure-increasing portion consumes buying power."""
        if qty <= _EPS:
            return "quantity must be positive"
        if est_price <= 0:
            return "no valid price to estimate order cost"
        pos = self.position_qty(symbol)
        if side.sign * pos < 0:  # opposing: part (or all) reduces exposure
            increasing = max(0.0, qty - abs(pos))
        else:
            increasing = qty
        required = increasing * est_price
        if required > self.buying_power + _EPS:
            return (
                f"insufficient buying power: need {required:.2f}, "
                f"have {self.buying_power:.2f}"
            )
        return None

    # ── snapshot for strategies ───────────────────────────────────────
    def snapshot(self, ts: datetime) -> PortfolioSnapshot:
        positions = {}
        for sym, book in self.books.items():
            if abs(book.qty) <= _EPS:
                continue
            positions[sym] = PositionView(
                symbol=sym,
                qty=book.qty,
                avg_price=book.avg_price,
                unrealized_pnl=book.unrealized_pnl(self.last_price[sym]),
            )
        return PortfolioSnapshot(
            ts=ts,
            cash=self.cash,
            equity=self.equity,
            buying_power=self.buying_power,
            long_value=self.long_value,
            short_value=self.short_value,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=self.unrealized_pnl,
            total_fees=self.total_fees,
            positions=positions,
        )
