"""Lot-level position accounting with pluggable FIFO/LIFO matching.

A LotBook holds the open lots of ONE symbol. Fills route through apply(),
which returns exactly what happened, split into:
- closed lots (with realized P&L per consumed lot fraction)
- quantity that opened new exposure (including the tail of a flip)

Invariants (tested):
- All lot quantities are strictly positive; direction is carried separately.
- signed_qty == direction * sum(lot.qty)
- A fill larger than the open position flips the book: old lots close
  first, the remainder opens the opposite direction in the same fill.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from engine.types import ClosedLot, LotMethod, Side

_EPS = 1e-12


@dataclass(slots=True)
class _Lot:
    qty: float
    price: float
    ts: datetime


@dataclass(slots=True)
class ApplyResult:
    closed: list[ClosedLot]
    opened_qty: float          # portion of the fill that opened new exposure
    closed_qty: float          # portion that closed existing exposure

    @property
    def realized_pnl(self) -> float:
        return sum(c.pnl for c in self.closed)


@dataclass(slots=True)
class LotBook:
    method: LotMethod = LotMethod.FIFO
    direction: int = 0                       # +1 long, -1 short, 0 flat
    lots: deque[_Lot] = field(default_factory=deque)

    @property
    def qty(self) -> float:
        """Signed position quantity."""
        return self.direction * sum(lot.qty for lot in self.lots)

    @property
    def avg_price(self) -> float:
        total = sum(lot.qty for lot in self.lots)
        if total < _EPS:
            return 0.0
        return sum(lot.qty * lot.price for lot in self.lots) / total

    def unrealized_pnl(self, last_price: float) -> float:
        return sum(
            (last_price - lot.price) * lot.qty * self.direction for lot in self.lots
        )

    def apply(self, side: Side, qty: float, price: float, ts: datetime) -> ApplyResult:
        assert qty > _EPS, "fill quantity must be positive"
        fill_dir = side.sign
        result = ApplyResult(closed=[], opened_qty=0.0, closed_qty=0.0)

        # Same direction (or flat): purely opens a new lot.
        if self.direction == 0 or fill_dir == self.direction:
            self._open(fill_dir, qty, price, ts)
            result.opened_qty = qty
            return result

        # Opposing fill: consume existing lots, then flip with any remainder.
        remaining = qty
        while remaining > _EPS and self.lots:
            lot = self.lots[0] if self.method is LotMethod.FIFO else self.lots[-1]
            take = min(remaining, lot.qty)
            result.closed.append(
                ClosedLot(
                    qty=take,
                    entry_price=lot.price,
                    exit_price=price,
                    entry_ts=lot.ts,
                    exit_ts=ts,
                    direction=self.direction,
                )
            )
            lot.qty -= take
            remaining -= take
            result.closed_qty += take
            if lot.qty <= _EPS:
                if self.method is LotMethod.FIFO:
                    self.lots.popleft()
                else:
                    self.lots.pop()

        if not self.lots and remaining <= _EPS:
            self.direction = 0
        if remaining > _EPS:  # flip
            self.direction = 0
            self._open(fill_dir, remaining, price, ts)
            result.opened_qty = remaining
        return result

    def _open(self, direction: int, qty: float, price: float, ts: datetime) -> None:
        if self.direction == 0:
            self.direction = direction
        assert direction == self.direction
        self.lots.append(_Lot(qty=qty, price=price, ts=ts))
