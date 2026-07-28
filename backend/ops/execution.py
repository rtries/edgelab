"""Execution layer: one broker interface, paper implementation first.

THE GUARANTEE: paper and live share the loop, runtime, risk engine,
ledger, and log schema. Only the Broker adapter differs. Paper models
what live will face:

  spread        buys lift the ask, sells hit the bid (quote if present,
                else close ± half the modeled spread)
  latency       orders accepted during event t execute on the NEXT bar
                of that symbol — same next-bar discipline as research
  slippage      adverse move in bps on top of spread (policy-modeled)
  partial fills fill qty capped at max_participation × bar volume;
                remainder stays working (GTC) or dies (IOC-style cap)
  commissions   the SAME SimpleCostModel commission math research used,
                so paper costs are comparable to backtests by design
  market hours  orders outside sessions are REJECTED with a log record
  rejections    buying-power failures come from the frozen Portfolio

Every action emits one structured JSON log line with a shared schema:
{stream, ts, received_at, kind, deployment_id, ...}. Live will emit the
same lines with stream="live" — logs are diffable across the two.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from engine.calendar import WeekdayCalendar
from engine.execution.costs import SimpleCostModel
from engine.portfolio.accounting import Portfolio
from engine.types import Fill, LotMethod, RoundTrip, Side

from ops.events import MarketEvent
from ops.risk import SignalCandidate


@dataclass(slots=True)
class WorkingOrder:
    id: int
    deployment_id: str
    symbol: str
    side: Side
    qty: float
    remaining: float
    submitted_ts: datetime
    eligible_after: datetime          # next-bar discipline
    source_signal: dict


class EventLog:
    """Append-only JSONL. Paper and live write the identical schema."""

    def __init__(self, path: Path, stream: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = stream

    def write(self, kind: str, ts: datetime, received_at: datetime,
              deployment_id: str, **payload) -> dict:
        record = {
            "stream": self.stream,
            "kind": kind,
            "ts": ts.isoformat(),
            "received_at": received_at.isoformat(),
            "deployment_id": deployment_id,
            **payload,
        }
        with self.path.open("a") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines()]


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


_EPS = 1e-9


class Ledger:
    """Live-side accounting on the FROZEN Portfolio, plus flat-to-flat
    round-trip pairing that mirrors the backtester's episode rules (fee
    attribution by fill fraction; episode closes when flat)."""

    def __init__(self, initial_cash: float, lot_method: LotMethod = LotMethod.FIFO) -> None:
        self.portfolio = Portfolio(initial_cash=initial_cash, lot_method=lot_method)
        self.round_trips: list[RoundTrip] = []
        self._episodes: dict[str, _Episode] = {}
        self.equity_points: list[tuple[datetime, float]] = []

    def apply_fill(self, fill: Fill) -> None:
        result = self.portfolio.apply_fill(fill)
        sym = fill.symbol
        episode = self._episodes.get(sym)

        if result.closed_qty > _EPS and episode is not None:
            close_frac = result.closed_qty / fill.qty
            episode.exit_qty += result.closed_qty
            episode.exit_notional += result.closed_qty * fill.price
            episode.gross_pnl += sum(c.pnl for c in result.closed)
            episode.fees += fill.fees * close_frac
            if (
                abs(self.portfolio.position_qty(sym)) <= _EPS
                or result.opened_qty > _EPS
            ):
                self._close_episode(sym, fill.ts)
                episode = None

        if result.opened_qty > _EPS:
            if episode is None:
                episode = _Episode(symbol=sym, direction=fill.side.sign,
                                   entry_ts=fill.ts)
                self._episodes[sym] = episode
            open_frac = result.opened_qty / fill.qty
            episode.entry_qty += result.opened_qty
            episode.entry_notional += result.opened_qty * fill.price
            episode.fees += fill.fees * open_frac

    def _close_episode(self, symbol: str, ts: datetime) -> None:
        ep = self._episodes.pop(symbol)
        self.round_trips.append(RoundTrip(
            symbol=ep.symbol, direction=ep.direction, qty=ep.exit_qty,
            entry_ts=ep.entry_ts, exit_ts=ts,
            entry_avg=ep.entry_notional / ep.entry_qty,
            exit_avg=ep.exit_notional / ep.exit_qty,
            gross_pnl=ep.gross_pnl, fees=ep.fees,
        ))

    def mark(self, symbol: str, price: float, ts: datetime) -> None:
        self.portfolio.mark(symbol, price)
        self.equity_points.append((ts, self.portfolio.equity))

    def to_dict(self) -> dict:
        snap = self.portfolio.snapshot(
            self.equity_points[-1][0] if self.equity_points else None
        )
        return {
            "cash": self.portfolio.cash,
            "equity": self.portfolio.equity,
            "realized_pnl": self.portfolio.realized_pnl,
            "total_fees": self.portfolio.total_fees,
            "positions": {
                sym: {"qty": self.portfolio.position_qty(sym),
                      "last": self.portfolio.last_price.get(sym)}
                for sym in self.portfolio.books
                if abs(self.portfolio.position_qty(sym)) > _EPS
            },
            "n_round_trips": len(self.round_trips),
            "snapshot_ts": snap.ts.isoformat() if snap.ts else None,
        }


class Broker(Protocol):
    """Paper and live brokers implement exactly this."""

    def submit(self, candidate: SignalCandidate, qty: float) -> WorkingOrder | None: ...

    def on_event(self, event: MarketEvent) -> list[Fill]: ...

    def working_orders(self, symbol: str | None = None) -> list[WorkingOrder]: ...


class PaperBroker:
    def __init__(
        self,
        ledger: Ledger,
        log: EventLog,
        cost_model: SimpleCostModel | None = None,
        max_participation: float | None = 0.1,
        calendar: WeekdayCalendar | None = None,
    ) -> None:
        self.ledger = ledger
        self.log = log
        self.cost_model = cost_model or SimpleCostModel()
        self.max_participation = max_participation
        self.calendar = calendar or WeekdayCalendar()
        self._orders: list[WorkingOrder] = []
        self._next_id = 1
        self._last_quote: dict[str, dict] = {}

    # ── order intake ──────────────────────────────────────────────────
    def submit(self, candidate: SignalCandidate, qty: float) -> WorkingOrder | None:
        ts = candidate.ts
        if not self.calendar.is_session(ts.date()):
            self.log.write("order_rejected", ts, candidate.received_at,
                           candidate.deployment_id, symbol=candidate.symbol,
                           reason="market closed")
            return None
        error = self.ledger.portfolio.check_order(
            candidate.symbol, candidate.side, qty,
            self.ledger.portfolio.last_price.get(candidate.symbol, 0.0),
        )
        if error is not None:
            self.log.write("order_rejected", ts, candidate.received_at,
                           candidate.deployment_id, symbol=candidate.symbol,
                           reason=error)
            return None
        order = WorkingOrder(
            id=self._next_id,
            deployment_id=candidate.deployment_id,
            symbol=candidate.symbol,
            side=candidate.side,
            qty=qty,
            remaining=qty,
            submitted_ts=ts,
            eligible_after=ts,             # fills on the NEXT bar after ts
            source_signal=candidate.to_dict(),
        )
        self._next_id += 1
        self._orders.append(order)
        self.log.write("order_submitted", ts, candidate.received_at,
                       candidate.deployment_id, order_id=order.id,
                       symbol=order.symbol, side=order.side.value, qty=qty)
        return order

    # ── event processing ──────────────────────────────────────────────
    def on_event(self, event: MarketEvent) -> list[Fill]:
        if event.kind == "quote":
            self._last_quote[event.symbol] = event.data
            return []
        if event.kind != "bar":
            return []
        fills: list[Fill] = []
        for order in list(self._orders):
            if order.symbol != event.symbol or event.ts <= order.eligible_after:
                continue
            fills.extend(self._execute(order, event))
        self._orders = [o for o in self._orders if o.remaining > _EPS]
        return fills

    def _execute(self, order: WorkingOrder, bar: MarketEvent) -> list[Fill]:
        data = bar.data
        quote = self._last_quote.get(order.symbol)
        # Base price: cross the spread.
        if quote:
            base = quote["ask"] if order.side == Side.BUY else quote["bid"]
        else:
            half = data["open"] * self.cost_model.spread_bps / 2e4
            base = data["open"] + (half if order.side == Side.BUY else -half)
        # Adverse slippage on top.
        slip = base * self.cost_model.slippage_bps / 1e4
        price = base + (slip if order.side == Side.BUY else -slip)

        # Liquidity: partial fill against participation cap.
        qty = order.remaining
        if self.max_participation is not None:
            cap = self.max_participation * data["volume"]
            qty = min(qty, cap)
        if qty <= _EPS:
            return []
        commission = max(
            self.cost_model.commission_per_share * qty,
            self.cost_model.min_commission,
        )
        fill = Fill(order_id=order.id, symbol=order.symbol, side=order.side,
                    qty=qty, price=price, fees=commission, ts=bar.ts)
        order.remaining -= qty
        self.ledger.apply_fill(fill)
        self.log.write(
            "fill", bar.ts, bar.received_at, order.deployment_id,
            order_id=order.id, symbol=order.symbol, side=order.side.value,
            qty=qty, price=price, fees=commission,
            partial=order.remaining > _EPS,
            decision_price=self.ledger.portfolio.last_price.get(order.symbol),
        )
        return [fill]

    def working_orders(self, symbol: str | None = None) -> list[WorkingOrder]:
        return [o for o in self._orders if symbol is None or o.symbol == symbol]

    # ── checkpoint support: working orders survive crashes ────────────
    def serialize(self) -> dict:
        return {
            "next_id": self._next_id,
            "last_quote": self._last_quote,
            "orders": [
                {
                    "id": o.id, "deployment_id": o.deployment_id,
                    "symbol": o.symbol, "side": o.side.value, "qty": o.qty,
                    "remaining": o.remaining,
                    "submitted_ts": o.submitted_ts.isoformat(),
                    "eligible_after": o.eligible_after.isoformat(),
                    "source_signal": o.source_signal,
                }
                for o in self._orders
            ],
        }

    def restore(self, state: dict) -> None:
        from datetime import datetime

        self._next_id = state["next_id"]
        self._last_quote = dict(state["last_quote"])
        self._orders = [
            WorkingOrder(
                id=o["id"], deployment_id=o["deployment_id"],
                symbol=o["symbol"], side=Side(o["side"]), qty=o["qty"],
                remaining=o["remaining"],
                submitted_ts=datetime.fromisoformat(o["submitted_ts"]),
                eligible_after=datetime.fromisoformat(o["eligible_after"]),
                source_signal=o["source_signal"],
            )
            for o in state["orders"]
        ]
