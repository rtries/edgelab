"""Provider-independent interface. Every provider returns CANONICAL frames
(engine.data.schema) with raw prices, ts = bar completion time, UTC."""
from __future__ import annotations

from datetime import date
from typing import Protocol

import pandas as pd

from engine.data.schema_types import Timeframe


class DataProvider(Protocol):
    @property
    def name(self) -> str: ...

    def fetch(
        self, symbol: str, timeframe: Timeframe, start: date, end: date
    ) -> pd.DataFrame: ...
