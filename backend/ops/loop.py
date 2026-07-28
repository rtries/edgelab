"""The live loop — ONE loop for replay, simulated live, paper, and
(later) live. Feeds and brokers are adapters; everything between them is
shared. That is the paper==live guarantee.

Per bar (matching the backtester's ordering exactly):
  1. broker.on_event      -> fills from previously accepted orders
  2. ledger.mark          -> equity at this close
  3. runtime.on_bar       -> signal candidates (strategy's opinion)
  4. pattern features     -> snapshot the market context per candidate
  5. risk.evaluate        -> approved qty or a logged rejection trail
  6. broker.submit        -> the ONLY path to an order

Recovery: the loop checkpoints (ledger + market state + processed-event
count + received bars) every `checkpoint_every` events. resume() rebuilds
strategy state by replaying the checkpointed bars through the runtime in
warm-up mode (submissions discarded — they already happened), restores
the ledger and market state, then continues from the next unprocessed
event. Deterministic feeds make the recovered run equal the
uninterrupted one; the test proves it fill-for-fill.
"""
from __future__ import annotations

import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from engine.calendar import WeekdayCalendar
from engine.portfolio.lots import LotBook, _Lot
from engine.types import Fill, LotMethod, RoundTrip, Side

from ops.deployments import Deployment
from ops.events import Feed, MarketEvent
from ops.execution import EventLog, Ledger, PaperBroker
from ops.risk import MarketState, evaluate
from ops.runtime import StrategyRuntime


def _ledger_state(ledger: Ledger) -> dict:
    p = ledger.portfolio
    return {
        "initial_cash": p.initial_cash,
        "cash": p.cash,
        "realized_pnl": p.realized_pnl,
        "total_fees": p.total_fees,
        "last_price": dict(p.last_price),
        "books": {
            sym: {
                "direction": book.direction,
                "lots": [{"qty": lot.qty, "price": lot.price,
                          "ts": lot.ts.isoformat()} for lot in book.lots],
            }
            for sym, book in p.books.items()
        },
        "round_trips": [
            {"symbol": rt.symbol, "direction": rt.direction, "qty": rt.qty,
             "entry_ts": rt.entry_ts.isoformat(), "exit_ts": rt.exit_ts.isoformat(),
             "entry_avg": rt.entry_avg, "exit_avg": rt.exit_avg,
             "gross_pnl": rt.gross_pnl, "fees": rt.fees}
            for rt in ledger.round_trips
        ],
        "equity_points": [(ts.isoformat(), v) for ts, v in ledger.equity_points],
    }


def _restore_ledger(state: dict) -> Ledger:
    ledger = Ledger(initial_cash=state["initial_cash"])
    p = ledger.portfolio
    p.cash = state["cash"]
    p.realized_pnl = state["realized_pnl"]
    p.total_fees = state["total_fees"]
    p.last_price.update(state["last_price"])
    for sym, book_state in state["books"].items():
        book = LotBook(method=LotMethod.FIFO, direction=book_state["direction"])
        for lot in book_state["lots"]:
            book.lots.append(_Lot(qty=lot["qty"], price=lot["price"],
                                  ts=datetime.fromisoformat(lot["ts"])))
        p.books[sym] = book
    ledger.round_trips = [
        RoundTrip(symbol=rt["symbol"], direction=rt["direction"], qty=rt["qty"],
                  entry_ts=datetime.fromisoformat(rt["entry_ts"]),
                  exit_ts=datetime.fromisoformat(rt["exit_ts"]),
                  entry_avg=rt["entry_avg"], exit_avg=rt["exit_avg"],
                  gross_pnl=rt["gross_pnl"], fees=rt["fees"])
        for rt in state["round_trips"]
    ]
    ledger.equity_points = [
        (datetime.fromisoformat(ts), v) for ts, v in state["equity_points"]
    ]
    return ledger


class LiveLoop:
    def __init__(
        self,
        deployment: Deployment,
        feed: Feed,
        ledger: Ledger,
        broker: PaperBroker,
        log: EventLog,
        stream: str = "paper",
        calendar: WeekdayCalendar | None = None,
        pattern_recorder=None,               # ops.patterns.PatternRecorder | None
        checkpoint_path: Path | None = None,
        checkpoint_every: int = 25,
        emergency_stop_flag=lambda: False,
    ) -> None:
        self.deployment = deployment
        self.feed = feed
        self.ledger = ledger
        self.broker = broker
        self.log = log
        self.stream = stream
        self.calendar = calendar or WeekdayCalendar()
        self.pattern_recorder = pattern_recorder
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path else None
        self.checkpoint_every = checkpoint_every
        self.emergency_stop_flag = emergency_stop_flag

        self.runtime = StrategyRuntime(
            deployment, ledger, working_orders_provider=broker.working_orders
        )
        self.state = MarketState(
            portfolio=ledger.portfolio,
            last_bar_ts={}, last_close={}, last_dollar_volume={},
            last_quote={}, bars_seen={},
            day_start_equity=ledger.portfolio.equity,
            current_day="",
        )
        self.processed_events = 0
        self._bar_history: deque[dict] = deque(maxlen=5000)

    # ── event processing ──────────────────────────────────────────────
    def _update_state(self, event: MarketEvent) -> None:
        if event.kind == "quote":
            self.state.last_quote[event.symbol] = dict(event.data)
            return
        day = event.ts.date().isoformat()
        if day != self.state.current_day:
            self.state.current_day = day
            self.state.day_start_equity = self.ledger.portfolio.equity
        self.state.last_bar_ts[event.symbol] = event.ts
        self.state.last_close[event.symbol] = event.data["close"]
        self.state.last_dollar_volume[event.symbol] = (
            event.data["close"] * event.data["volume"]
        )
        self.state.bars_seen[event.symbol] = (
            self.state.bars_seen.get(event.symbol, 0) + 1
        )

    def process(self, event: MarketEvent) -> None:
        self.state.emergency_stop = bool(self.emergency_stop_flag())
        self._update_state(event)

        # 1) fills for orders accepted on earlier events
        fills: list[Fill] = self.broker.on_event(event)
        for fill in fills:
            self.runtime.on_fill(fill)
            if self.pattern_recorder is not None:
                self.pattern_recorder.on_fill(self.deployment, fill,
                                              self.ledger)

        if event.kind != "bar":
            self.processed_events += 1
            return

        # 2) mark at the close
        self.ledger.mark(event.symbol, event.data["close"], event.ts)

        # 3) strategy's opinion
        candidates = self.runtime.on_bar(event)

        for candidate in candidates:
            # 4) market-context snapshot for the pattern library
            if self.pattern_recorder is not None:
                candidate.features.update(
                    self.pattern_recorder.extract_features(
                        candidate.symbol, self.runtime, self.state
                    )
                )
            position = self.ledger.portfolio.position_qty(candidate.symbol)
            is_closing = (
                position > 0 and candidate.side == Side.SELL
                or position < 0 and candidate.side == Side.BUY
            )
            # 5) risk chain
            result = evaluate(candidate, self.deployment, self.state,
                              self.calendar, is_closing=is_closing)
            if not result.approved:
                rejection = result.rejection
                self.log.write(
                    "signal_rejected", candidate.ts, candidate.received_at,
                    self.deployment.id, symbol=candidate.symbol,
                    side=candidate.side.value, check=rejection.check,
                    reason=rejection.reason, evidence=rejection.evidence,
                )
                continue
            # 6) the only path to an order
            order = self.broker.submit(candidate, result.final_qty)
            if order is not None:
                self.state.recent_signals.append((
                    candidate.deployment_id, candidate.symbol,
                    candidate.side.value,
                    self.state.bars_seen.get(candidate.symbol, 0),
                ))
                if self.pattern_recorder is not None:
                    self.pattern_recorder.on_signal(
                        self.deployment, candidate, order.id
                    )

        self._bar_history.append(event.to_dict())
        self.processed_events += 1
        if (
            self.checkpoint_path is not None
            and self.processed_events % self.checkpoint_every == 0
        ):
            self.checkpoint()

    def run(self, max_events: int | None = None) -> dict:
        for event in self.feed.events():
            if max_events is not None and self.processed_events >= max_events:
                break
            self.process(event)
        if self.checkpoint_path is not None:
            self.checkpoint()
        return self.summary()

    def summary(self) -> dict:
        return {
            "deployment_id": self.deployment.id,
            "stream": self.stream,
            "processed_events": self.processed_events,
            "ledger": self.ledger.to_dict(),
            "n_trades": len(self.ledger.round_trips),
        }

    # ── checkpoint / recovery ─────────────────────────────────────────
    def checkpoint(self) -> None:
        payload = {
            "deployment_id": self.deployment.id,
            "processed_events": self.processed_events,
            "saved_at": datetime.now(UTC).isoformat(),
            "ledger": _ledger_state(self.ledger),
            "market_state": {
                "last_bar_ts": {s: t.isoformat() for s, t in self.state.last_bar_ts.items()},
                "last_close": self.state.last_close,
                "last_dollar_volume": self.state.last_dollar_volume,
                "last_quote": self.state.last_quote,
                "bars_seen": self.state.bars_seen,
                "day_start_equity": self.state.day_start_equity,
                "current_day": self.state.current_day,
                "recent_signals": self.state.recent_signals,
            },
            "bars": list(self._bar_history),
            "broker": self.broker.serialize(),
        }
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path.write_text(json.dumps(payload))

    @classmethod
    def resume(
        cls,
        deployment: Deployment,
        feed: Feed,
        log: EventLog,
        checkpoint_path: Path,
        **kwargs,
    ) -> "LiveLoop":
        payload = json.loads(Path(checkpoint_path).read_text())
        if payload["deployment_id"] != deployment.id:
            raise ValueError("checkpoint belongs to a different deployment")
        ledger = _restore_ledger(payload["ledger"])
        broker = PaperBroker(ledger, log)
        broker.restore(payload["broker"])
        loop = cls(deployment, feed, ledger, broker, log,
                   checkpoint_path=checkpoint_path, **kwargs)
        # restore market state
        ms = payload["market_state"]
        loop.state.last_bar_ts = {
            s: datetime.fromisoformat(t) for s, t in ms["last_bar_ts"].items()
        }
        loop.state.last_close = ms["last_close"]
        loop.state.last_dollar_volume = ms["last_dollar_volume"]
        loop.state.last_quote = ms["last_quote"]
        loop.state.bars_seen = dict(ms["bars_seen"])
        loop.state.day_start_equity = ms["day_start_equity"]
        loop.state.current_day = ms["current_day"]
        loop.state.recent_signals = [tuple(r) for r in ms["recent_signals"]]
        # warm the strategy back up: same bars, submissions discarded
        for bar_dict in payload["bars"]:
            loop.runtime.on_bar(
                MarketEvent(
                    kind="bar", symbol=bar_dict["symbol"],
                    ts=datetime.fromisoformat(bar_dict["ts"]),
                    received_at=datetime.fromisoformat(bar_dict["received_at"]),
                    data=bar_dict["data"],
                ),
                capture=False,
            )
        loop._bar_history.extend(payload["bars"])
        loop.processed_events = payload["processed_events"]
        # skip already-processed events, continue with the rest
        loop._skip = payload["processed_events"]
        return loop

    _skip: int = 0

    def run_resumed(self, max_events: int | None = None) -> dict:
        skipped = 0
        for event in self.feed.events():
            if skipped < self._skip:
                skipped += 1
                continue
            if max_events is not None and self.processed_events >= max_events:
                break
            self.process(event)
        if self.checkpoint_path is not None:
            self.checkpoint()
        return self.summary()
