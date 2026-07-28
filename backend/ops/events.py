"""Live market engine: one normalized event model, four feed sources.

Every event carries TWO timestamps:
  ts          — exchange/event time (when the market did it)
  received_at — ingest time (when we learned about it)
Replay sets received_at = ts (a stated simulation convention). The
simulated live feed adds seeded latency so downstream code cannot
quietly assume the two are equal. Broker feeds stamp actual wall time.

Feeds are iterators of MarketEvent, nothing more — the loop, runtime,
risk, and execution layers are IDENTICAL regardless of source. That is
the paper==live guarantee, held by construction.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

import numpy as np

from engine.data.schema_types import Timeframe
from engine.data.store import ParquetStore


@dataclass(frozen=True, slots=True)
class MarketEvent:
    kind: str                  # "bar" | "quote" | "session"
    symbol: str
    ts: datetime               # exchange time
    received_at: datetime      # ingest time
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "symbol": self.symbol,
            "ts": self.ts.isoformat(),
            "received_at": self.received_at.isoformat(),
            "data": self.data,
        }


class Feed(Protocol):
    def events(self) -> Iterator[MarketEvent]: ...


class ReplayFeed:
    """Deterministic historical replay from the Parquet store. Bars for
    all symbols are merged in timestamp order (symbol name breaks ties),
    exactly the ordering the backtester uses."""

    def __init__(
        self,
        store: ParquetStore,
        symbols: list[str],
        timeframe: Timeframe | str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> None:
        self.store = store
        self.symbols = sorted(symbols)
        self.timeframe = timeframe
        self.start = start
        self.end = end

    def events(self) -> Iterator[MarketEvent]:
        rows: list[tuple[datetime, str, dict]] = []
        for sym in self.symbols:
            frame = self.store.read(sym, self.timeframe, self.start, self.end)
            for rec in frame.to_dict(orient="records"):
                ts = rec["ts"].to_pydatetime()
                rows.append((
                    ts,
                    sym,
                    {
                        "open": float(rec["open"]),
                        "high": float(rec["high"]),
                        "low": float(rec["low"]),
                        "close": float(rec["close"]),
                        "volume": float(rec["volume"]),
                    },
                ))
        rows.sort(key=lambda r: (r[0], r[1]))
        for ts, sym, data in rows:
            yield MarketEvent(kind="bar", symbol=sym, ts=ts, received_at=ts, data=data)


class SimulatedLiveFeed:
    """Replay dressed as live: before each bar a synthetic quote (bid/ask
    around the close with seeded spread jitter), and seeded ingest
    latency on every event. Deterministic under its seed — used to prove
    the stack tolerates received_at != ts."""

    def __init__(
        self,
        replay: ReplayFeed,
        seed: int = 0,
        spread_bps_range: tuple[float, float] = (2.0, 10.0),
        latency_ms_range: tuple[int, int] = (5, 250),
    ) -> None:
        self.replay = replay
        self.seed = seed
        self.spread_bps_range = spread_bps_range
        self.latency_ms_range = latency_ms_range

    def events(self) -> Iterator[MarketEvent]:
        rng = np.random.default_rng(self.seed)
        for event in self.replay.events():
            spread_bps = float(rng.uniform(*self.spread_bps_range))
            half = event.data["close"] * spread_bps / 2e4
            latency = timedelta(milliseconds=int(rng.integers(*self.latency_ms_range)))
            yield MarketEvent(
                kind="quote",
                symbol=event.symbol,
                ts=event.ts,
                received_at=event.ts + latency,
                data={
                    "bid": event.data["close"] - half,
                    "ask": event.data["close"] + half,
                    "spread_bps": spread_bps,
                },
            )
            latency2 = timedelta(milliseconds=int(rng.integers(*self.latency_ms_range)))
            yield MarketEvent(
                kind="bar",
                symbol=event.symbol,
                ts=event.ts,
                received_at=event.ts + latency2,
                data=dict(event.data),
            )


class Transport(Protocol):
    """Injected message source for broker feeds — tests provide fakes;
    production provides a websocket/HTTP poller. No network in tests."""

    def messages(self) -> Iterator[dict]: ...


class AlpacaFeed:
    """Normalizes Alpaca-style bar/quote messages into MarketEvent.
    Connectivity lives in the injected transport, mirroring the Phase 2
    provider design. This adapter is the paper-feed and live-feed entry
    point; only the transport (and credentials) differ between the two.
    """

    def __init__(self, transport: Transport, clock=lambda: datetime.now(UTC)) -> None:
        self.transport = transport
        self.clock = clock

    def events(self) -> Iterator[MarketEvent]:
        for msg in self.transport.messages():
            received = self.clock()
            kind = msg.get("T")
            if kind == "b":          # bar
                yield MarketEvent(
                    kind="bar",
                    symbol=msg["S"],
                    ts=datetime.fromisoformat(msg["t"]),
                    received_at=received,
                    data={
                        "open": float(msg["o"]), "high": float(msg["h"]),
                        "low": float(msg["l"]), "close": float(msg["c"]),
                        "volume": float(msg["v"]),
                    },
                )
            elif kind == "q":        # quote
                bid, ask = float(msg["bp"]), float(msg["ap"])
                mid = (bid + ask) / 2 or 1.0
                yield MarketEvent(
                    kind="quote",
                    symbol=msg["S"],
                    ts=datetime.fromisoformat(msg["t"]),
                    received_at=received,
                    data={
                        "bid": bid, "ask": ask,
                        "spread_bps": (ask - bid) / mid * 1e4,
                    },
                )
            # unknown message kinds are dropped, never guessed at
