"""Strategy base classes."""
from __future__ import annotations

from collections.abc import Callable

from engine.interfaces import TradingContext
from engine.types import Bar, Fill


class BaseStrategy:
    """No-op implementations of every hook; subclass what you need."""

    def on_start(self, ctx: TradingContext, params: dict) -> None:  # noqa: ARG002
        return None

    def on_bar(self, bar: Bar, ctx: TradingContext) -> None:  # noqa: ARG002
        return None

    def on_fill(self, fill: Fill) -> None:  # noqa: ARG002
        return None


class ScriptedStrategy(BaseStrategy):
    """Executes a fixed script keyed by global bar index (0-based, across
    all symbols in feed order). Used for deterministic engine tests."""

    def __init__(self, script: dict[int, Callable[[Bar, TradingContext], None]]) -> None:
        self.script = script
        self.bar_index = -1
        self.fills: list[Fill] = []
        self.bars_seen: list[Bar] = []

    def on_bar(self, bar: Bar, ctx: TradingContext) -> None:
        self.bar_index += 1
        self.bars_seen.append(bar)
        action = self.script.get(self.bar_index)
        if action is not None:
            action(bar, ctx)

    def on_fill(self, fill: Fill) -> None:
        self.fills.append(fill)
