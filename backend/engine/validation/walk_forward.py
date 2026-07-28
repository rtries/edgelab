"""Walk-forward optimization (Phase 2).

Split history into rolling (train, test) windows. Optimize parameters on
train only; evaluate frozen parameters on the unseen test window; stitch
the out-of-sample segments into a single honest equity curve. The gap
between in-sample and out-of-sample performance IS the overfitting measure.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, slots=True)
class Window:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def rolling_windows(
    index: pd.DatetimeIndex, train_len: pd.Timedelta, test_len: pd.Timedelta
) -> Iterator[Window]:
    raise NotImplementedError
