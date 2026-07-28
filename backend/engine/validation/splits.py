"""Train/validation windowing and the untouched final test set.

Windows are defined over an ORDERED bar index (the actual timestamps a
dataset contains), in bar counts — exact and deterministic, no calendar
arithmetic ambiguity. "Train 2018-2020, validate 2021, roll" is expressed
by choosing sizes/steps matching those spans in bars.

The final test set is protected structurally: reserve_final_test() splits
the index BEFORE any optimization sees it, and FinalTestSet.evaluate()
runs exactly once — a second call raises. Optimizing on the holdout is
an API impossibility, not a convention.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Fold:
    index: int
    train_start: datetime
    train_end: datetime
    val_start: datetime
    val_end: datetime
    train_positions: tuple[int, int]     # inclusive bar positions
    val_positions: tuple[int, int]


@dataclass(frozen=True, slots=True)
class WindowSpec:
    """train_size/val_size/step in BARS.
    step < val_size  -> overlapping validation windows
    step == val_size -> contiguous, non-overlapping validation (default)
    expanding=True   -> train always starts at bar 0 and grows
    """

    train_size: int
    val_size: int
    step: int | None = None
    expanding: bool = False

    def folds(self, index: Sequence[datetime]) -> list[Fold]:
        if self.train_size < 1 or self.val_size < 1:
            raise ValueError("train_size and val_size must be >= 1")
        step = self.step if self.step is not None else self.val_size
        if step < 1:
            raise ValueError("step must be >= 1")
        n = len(index)
        if n < self.train_size + self.val_size:
            raise ValueError(
                f"index has {n} bars; need >= {self.train_size + self.val_size}"
            )
        out: list[Fold] = []
        k = 0
        train_end_pos = self.train_size - 1
        while train_end_pos + self.val_size < n:
            train_start_pos = 0 if self.expanding else train_end_pos - self.train_size + 1
            val_start_pos = train_end_pos + 1
            val_end_pos = val_start_pos + self.val_size - 1
            out.append(
                Fold(
                    index=k,
                    train_start=index[train_start_pos],
                    train_end=index[train_end_pos],
                    val_start=index[val_start_pos],
                    val_end=index[val_end_pos],
                    train_positions=(train_start_pos, train_end_pos),
                    val_positions=(val_start_pos, val_end_pos),
                )
            )
            k += 1
            train_end_pos += step
        if not out:
            raise ValueError("window spec produced zero folds")
        return out


def reserve_final_test(
    index: Sequence[datetime], test_size: int
) -> tuple[list[datetime], "FinalTestSet"]:
    """Split off the LAST test_size bars before anything else happens.
    Returns (work_index, guard). Optimization code receives work_index and
    can never construct windows over the holdout."""
    if test_size < 1:
        raise ValueError("test_size must be >= 1")
    if test_size >= len(index):
        raise ValueError("test_size must leave room for train/validation")
    work = list(index[:-test_size])
    guard = FinalTestSet(start=index[-test_size], end=index[-1], n_bars=test_size)
    return work, guard


@dataclass(slots=True)
class FinalTestSet:
    """One-shot evaluation guard for the untouched holdout."""

    start: datetime
    end: datetime
    n_bars: int
    _consumed: bool = field(default=False, repr=False)

    @property
    def consumed(self) -> bool:
        return self._consumed

    def evaluate(self, runner: Callable, params: dict):
        """runner(params, start, end) -> BacktestResult. Callable ONCE."""
        if self._consumed:
            raise RuntimeError(
                "final test set already consumed — evaluating it again would "
                "turn the holdout into a validation set"
            )
        self._consumed = True
        return runner(params, self.start, self.end)
