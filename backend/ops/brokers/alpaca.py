"""Alpaca broker — places real orders through Alpaca's Trading API.

Shares the exact same `Broker` protocol as `PaperBroker`, so it drops
into the identical `LiveLoop` used everywhere else — same risk engine,
same runtime, same event log schema. Nothing about the *system* changes
when you switch from paper to live; only which broker object gets
handed to `LiveLoop`.

SAFETY DESIGN — read this before wiring credentials anywhere:

  - `paper: bool` selects Alpaca's own paper-trading endpoint
    (`paper-api.alpaca.markets`) vs the live one (`api.alpaca.markets`).
    Alpaca's paper environment is real order-matching against real
    market data with fake money — a genuinely useful second layer of
    testing beyond our own PaperBroker's fill simulation.
  - This class never decides paper vs. live on its own. The caller
    (the ops API) is responsible for only constructing a live-mode
    AlpacaBroker when the deployment's lifecycle status is actually
    "live" — the same gate documented in ops/deployments.py. An
    AlpacaBroker existing in your code is not itself dangerous; what's
    dangerous is calling it with a live base URL for a deployment that
    hasn't earned that status yet.
  - Fills are reconciled by polling Alpaca's order-status endpoint on
    every `on_event` call, comparing `filled_qty` against what we last
    saw per order. This is simpler and more testable than running a
    separate trade-updates websocket, at the cost of fill latency being
    bounded by how often `on_event` fires (i.e. by market data cadence)
    rather than being instant. For a 2-3 person test deployment this
    tradeoff is the right one; a busier deployment would want the
    websocket stream instead (Phase 6 recommendation).
  - `cancel_order` exists for operator-triggered cancellation via the
    API. Strategy-triggered cancellation through the SDK's
    `ctx.cancel()` is still not wired end-to-end (documented limitation
    carried over from Phase 5) — this only covers manual/API-driven
    cancels.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from engine.types import Fill, OrderType, Side

from ops.events import MarketEvent
from ops.execution import EventLog, WorkingOrder
from ops.risk import SignalCandidate

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"


class HTTPTransport(Protocol):
    """Injected so tests never touch the real network. Production uses
    `UrllibTransport`; tests supply a fake that returns canned JSON."""

    def request(
        self, method: str, url: str, headers: dict, body: dict | None = None
    ) -> tuple[int, dict]: ...


class UrllibTransport:
    def request(
        self, method: str, url: str, headers: dict, body: dict | None = None
    ) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            payload = json.loads(raw) if raw else {"message": str(exc)}
            return exc.code, payload


class AlpacaError(Exception):
    """Raised on any non-2xx response from Alpaca's API."""

    def __init__(self, status: int, payload: dict) -> None:
        self.status = status
        self.payload = payload
        super().__init__(f"Alpaca API error {status}: {payload}")


@dataclass(slots=True)
class _Tracked:
    working: WorkingOrder
    alpaca_order_id: str
    last_filled_qty: float = 0.0


class AlpacaBroker:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        log: EventLog,
        paper: bool = True,
        transport: HTTPTransport | None = None,
        poll_min_interval_seconds: float = 1.0,
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError("Alpaca API key and secret are required")
        self.base_url = PAPER_BASE_URL if paper else LIVE_BASE_URL
        self.paper = paper
        self._headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
            "Content-Type": "application/json",
        }
        self.log = log
        self.transport = transport or UrllibTransport()
        self.poll_min_interval_seconds = poll_min_interval_seconds
        self._orders: dict[int, _Tracked] = {}
        self._next_id = 1
        self._last_poll: float = 0.0

    # ── HTTP helpers ─────────────────────────────────────────────────
    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        status, payload = self.transport.request(
            method, self.base_url + path, self._headers, body
        )
        if status >= 300:
            raise AlpacaError(status, payload)
        return payload

    # ── order intake ────────────────────────────────────────────────
    def submit(self, candidate: SignalCandidate, qty: float) -> WorkingOrder | None:
        ts = candidate.ts
        order_type_map = {
            OrderType.MARKET: "market",
            OrderType.LIMIT: "limit",
            OrderType.STOP: "stop",
            OrderType.STOP_LIMIT: "stop_limit",
        }
        body = {
            "symbol": candidate.symbol,
            "qty": str(qty),
            "side": candidate.side.value,
            "type": order_type_map[candidate.order_type],
            "time_in_force": "day",
        }
        if candidate.limit_price is not None:
            body["limit_price"] = str(candidate.limit_price)
        if candidate.stop_price is not None:
            body["stop_price"] = str(candidate.stop_price)

        try:
            resp = self._request("POST", "/v2/orders", body)
        except AlpacaError as exc:
            self.log.write(
                "order_rejected", ts, candidate.received_at,
                candidate.deployment_id, symbol=candidate.symbol,
                reason=f"Alpaca {exc.status}: {exc.payload}",
            )
            return None

        order = WorkingOrder(
            id=self._next_id,
            deployment_id=candidate.deployment_id,
            symbol=candidate.symbol,
            side=candidate.side,
            qty=qty,
            remaining=qty,
            submitted_ts=ts,
            eligible_after=ts,
            source_signal=candidate.to_dict(),
        )
        self._orders[order.id] = _Tracked(working=order, alpaca_order_id=resp["id"])
        self._next_id += 1
        self.log.write(
            "order_submitted", ts, candidate.received_at, candidate.deployment_id,
            order_id=order.id, alpaca_order_id=resp["id"], symbol=order.symbol,
            side=order.side.value, qty=qty, mode="paper" if self.paper else "live",
        )
        return order

    def cancel_order(self, order_id: int) -> bool:
        tracked = self._orders.get(order_id)
        if tracked is None:
            return False
        try:
            self._request("DELETE", f"/v2/orders/{tracked.alpaca_order_id}")
        except AlpacaError:
            return False
        return True

    # ── fill reconciliation ──────────────────────────────────────────
    def on_event(self, event: MarketEvent) -> list[Fill]:
        if not self._orders:
            return []
        now = time.monotonic()
        if now - self._last_poll < self.poll_min_interval_seconds:
            return []
        self._last_poll = now

        fills: list[Fill] = []
        for order_id, tracked in list(self._orders.items()):
            try:
                resp = self._request(
                    "GET", f"/v2/orders/{tracked.alpaca_order_id}"
                )
            except AlpacaError:
                continue
            filled_qty = float(resp.get("filled_qty") or 0.0)
            new_qty = filled_qty - tracked.last_filled_qty
            if new_qty > 1e-9:
                avg_price = float(resp.get("filled_avg_price") or 0.0)
                fill = Fill(
                    order_id=order_id, symbol=tracked.working.symbol,
                    side=tracked.working.side, qty=new_qty, price=avg_price,
                    fees=0.0,  # Alpaca is commission-free on equities
                    ts=event.ts,
                )
                fills.append(fill)
                tracked.last_filled_qty = filled_qty
                tracked.working.remaining = tracked.working.qty - filled_qty
                self.log.write(
                    "fill", event.ts, event.received_at,
                    tracked.working.deployment_id, order_id=order_id,
                    alpaca_order_id=tracked.alpaca_order_id,
                    symbol=tracked.working.symbol, side=tracked.working.side.value,
                    qty=new_qty, price=avg_price, fees=0.0,
                    partial=resp.get("status") != "filled",
                    alpaca_status=resp.get("status"),
                )
            status = resp.get("status")
            if status in ("filled", "canceled", "expired", "rejected"):
                del self._orders[order_id]

        return fills

    def working_orders(self, symbol: str | None = None) -> list[WorkingOrder]:
        return [
            t.working for t in self._orders.values()
            if symbol is None or t.working.symbol == symbol
        ]
