"""Shared test fixtures and factories."""
from __future__ import annotations

from datetime import UTC, datetime

from engine.types import Bar

V = 1_000_000.0  # default volume: large enough that a 10% cap never binds
                 # for the small test quantities unless a test says otherwise


def ts(day: int, month: int = 1, hour: int = 16) -> datetime:
    return datetime(2024, month, day, hour, 0, tzinfo=UTC)


def bar(
    day: int,
    o: float,
    h: float,
    lo: float,
    c: float,
    v: float = V,
    sym: str = "X",
    month: int = 1,
) -> Bar:
    assert lo <= min(o, c) and h >= max(o, c), "malformed test bar"
    return Bar(symbol=sym, ts=ts(day, month), open=o, high=h, low=lo, close=c, volume=v)
