"""Incremental (streaming) indicator state, one update per bar.

Each class produces values IDENTICAL to its vectorized counterpart in
indicators.core (equivalence-tested). update() returns None during
warm-up — the streaming twin of the vectorized NaN.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(slots=True)
class IncrementalSMA:
    n: int
    _window: deque = field(default_factory=deque)
    _sum: float = 0.0

    def update(self, x: float) -> float | None:
        self._window.append(x)
        self._sum += x
        if len(self._window) > self.n:
            self._sum -= self._window.popleft()
        if len(self._window) < self.n:
            return None
        return self._sum / self.n


@dataclass(slots=True)
class IncrementalEMA:
    n: int
    _seed: "IncrementalSMA" = field(init=False)
    _value: float | None = None

    def __post_init__(self) -> None:
        self._seed = IncrementalSMA(self.n)

    def update(self, x: float) -> float | None:
        if self._value is None:
            self._value = self._seed.update(x)
            return self._value
        alpha = 2.0 / (self.n + 1.0)
        self._value = self._value + alpha * (x - self._value)
        return self._value


@dataclass(slots=True)
class _IncrementalWilder:
    n: int
    _seed_window: list = field(default_factory=list)
    _value: float | None = None

    def update(self, x: float) -> float | None:
        if self._value is None:
            self._seed_window.append(x)
            if len(self._seed_window) == self.n:
                self._value = sum(self._seed_window) / self.n
            return self._value
        self._value = (self._value * (self.n - 1) + x) / self.n
        return self._value


@dataclass(slots=True)
class IncrementalRSI:
    n: int
    _prev: float | None = None
    _gain: "_IncrementalWilder" = field(init=False)
    _loss: "_IncrementalWilder" = field(init=False)

    def __post_init__(self) -> None:
        self._gain = _IncrementalWilder(self.n)
        self._loss = _IncrementalWilder(self.n)

    def update(self, close: float) -> float | None:
        if self._prev is None:
            self._prev = close
            return None
        change = close - self._prev
        self._prev = close
        ag = self._gain.update(max(change, 0.0))
        al = self._loss.update(max(-change, 0.0))
        if ag is None or al is None:
            return None
        if al == 0.0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + ag / al)


@dataclass(slots=True)
class IncrementalATR:
    n: int
    _prev_close: float | None = None
    _wilder: "_IncrementalWilder" = field(init=False)

    def __post_init__(self) -> None:
        self._wilder = _IncrementalWilder(self.n)

    def update(self, high: float, low: float, close: float) -> float | None:
        if self._prev_close is None:
            self._prev_close = close
            return None
        tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._prev_close = close
        return self._wilder.update(tr)
