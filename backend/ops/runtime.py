"""Strategy runtime.

Runs the EXACT strategy code research validated — same SDKAdapter, same
params, same history semantics — against a live event stream, with one
inversion: the context's submit() produces SignalCandidates instead of
orders. The runtime's whole job is the core principle:

    Does the current market satisfy this validated strategy?
    NO  -> the strategy stays silent; the runtime does nothing.
    YES -> the strategy tries to trade; that attempt becomes a
           candidate for the risk engine. Orders are someone else's
           decision.

Per-bar ordering mirrors the backtester exactly (fills -> mark ->
on_bar), which is what makes the signal-parity test possible: on the
same bars, the runtime's candidate stream equals the backtester's order
stream.

Runtime contract (also the recovery contract): strategies derive state
from history + context — indicators rebuild from bars; position comes
from ctx.portfolio. That is the SDK's design, and it is what lets a
crashed runtime warm up deterministically by replaying bars through a
discard context.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pandas as pd

from engine.data.history import HistoryService
from engine.params import resolve_params
from engine.sdk import SDKAdapter
from engine.types import Bar, Fill, Order, OrderStatus, OrderType, Side, TimeInForce

from ops.deployments import Deployment
from ops.events import MarketEvent
from ops.execution import Ledger, WorkingOrder
from ops.risk import SignalCandidate

from engine.strategies import examples as example_strategies

STRATEGY_REGISTRY = {
    cls.__name__: cls
    for cls in (
        example_strategies.BuyAndHold,
        example_strategies.MACrossover,
        example_strategies.RSIMeanReversion,
        example_strategies.VolatilityBreakout,
    )
}


class _RuntimeContext:
    """TradingContext whose submit() captures candidates. Reads come from
    the live ledger; working orders map back to engine Orders so SDK
    strategies see a familiar surface."""

    def __init__(self, runtime: "StrategyRuntime", capture: bool) -> None:
        self._runtime = runtime
        self._capture = capture

    @property
    def portfolio(self):  # noqa: ANN201
        return self._runtime.ledger.portfolio.snapshot(self._runtime.now)

    def pending_orders(self, symbol: str | None = None) -> Sequence[Order]:
        working = self._runtime.working_orders_provider(symbol)
        return [
            Order(id=w.id, symbol=w.symbol, side=w.side, qty=w.qty,
                  type=OrderType.MARKET, limit_price=None, stop_price=None,
                  status=OrderStatus.PENDING, filled_qty=w.qty - w.remaining,
                  created_ts=w.submitted_ts)
            for w in working
        ]

    def cancel(self, order_id: int) -> bool:
        return False   # cancels flow through the broker adapter in Phase 6

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
        if self._capture:
            self._runtime.captured.append(SignalCandidate(
                deployment_id=self._runtime.deployment.id,
                strategy=self._runtime.deployment.strategy,
                symbol=symbol,
                side=side,
                qty=qty,
                ts=self._runtime.now,
                received_at=self._runtime.received_at,
                order_type=type,
                limit_price=limit_price,
                stop_price=stop_price,
            ))
        # Placeholder — never an engine order (id -1 is the sentinel the
        # DelayedStrategy wrapper established in Phase 3).
        return Order(id=-1, symbol=symbol, side=side, qty=qty, type=type,
                     limit_price=limit_price, stop_price=stop_price,
                     status=OrderStatus.PENDING)


class StrategyRuntime:
    def __init__(
        self,
        deployment: Deployment,
        ledger: Ledger,
        working_orders_provider=lambda symbol=None: [],
    ) -> None:
        if deployment.strategy not in STRATEGY_REGISTRY:
            raise ValueError(f"unknown strategy {deployment.strategy}")
        self.deployment = deployment
        self.ledger = ledger
        self.working_orders_provider = working_orders_provider
        strategy_cls = STRATEGY_REGISTRY[deployment.strategy]
        self._bars: dict[str, list[dict]] = {s: [] for s in deployment.symbols}
        self._history = HistoryService({})
        resolved = resolve_params(strategy_cls.params, deployment.params)
        self._adapter = SDKAdapter(strategy_cls(), resolved, self._history)
        self._params = resolved
        self._started = False
        self.captured: list[SignalCandidate] = []
        self.now: datetime = datetime.now(UTC)
        self.received_at: datetime = self.now

    # ── history maintenance ───────────────────────────────────────────
    def _append_bar(self, event: MarketEvent) -> None:
        self._bars[event.symbol].append({
            "symbol": event.symbol,
            "ts": pd.Timestamp(event.ts),
            **{k: event.data[k] for k in ("open", "high", "low", "close", "volume")},
            "timeframe": str(self.deployment.timeframe),
            "source": "live",
        })
        frame = pd.DataFrame(self._bars[event.symbol])
        # HistoryService normalizes keys to (symbol, str(timeframe)).
        self._history._frames[(event.symbol, str(self.deployment.timeframe))] = frame  # noqa: SLF001

    def _bar_obj(self, event: MarketEvent) -> Bar:
        d = event.data
        return Bar(symbol=event.symbol, ts=event.ts, open=d["open"],
                   high=d["high"], low=d["low"], close=d["close"],
                   volume=d["volume"])

    # ── stepping ──────────────────────────────────────────────────────
    def on_bar(self, event: MarketEvent, capture: bool = True) -> list[SignalCandidate]:
        """Feed one bar; return any signal candidates it produced.
        capture=False is warm-up mode: identical strategy execution,
        submissions discarded (used by crash recovery)."""
        if event.symbol not in self._bars:
            return []                     # not this deployment's market
        self.now = event.ts
        self.received_at = event.received_at
        self._append_bar(event)
        ctx = _RuntimeContext(self, capture=capture)
        if not self._started:
            self._adapter.on_start(ctx, self._params)
            self._started = True
        self.captured = []
        self._adapter.on_bar(self._bar_obj(event), ctx)
        return list(self.captured)

    def on_fill(self, fill: Fill) -> None:
        self._adapter.on_fill(fill)
