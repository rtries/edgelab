"""Point-in-time history service.

Serves ONLY bars whose completion time (ts) is <= the requested as-of
moment. Because canonical ts is the bar CLOSE, a daily candle is invisible
until the session actually ends — the multi-timeframe lookahead guard
falls out of the timestamp convention rather than special-case logic.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from engine.data.schema_types import DataValidationError, Timeframe


class HistoryService:
    def __init__(self, frames: dict[tuple[str, str], pd.DataFrame]) -> None:
        """frames: {(symbol, timeframe): canonical df}. All frames must share
        one adjustment mode — mixing adjusted and raw data is refused."""
        modes = {
            df.attrs.get("adjustment_mode", "raw") for df in frames.values()
        }
        if len(modes) > 1:
            raise DataValidationError(
                f"mixed adjustment modes in history frames: {sorted(modes)}"
            )
        self.adjustment_mode = modes.pop() if modes else "raw"
        self._frames = {
            (sym, str(tf)): df.sort_values("ts", kind="stable").reset_index(drop=True)
            for (sym, tf), df in frames.items()
        }

    def history(
        self,
        symbol: str,
        timeframe: Timeframe | str,
        as_of: datetime,
        n: int | None = None,
    ) -> pd.DataFrame:
        """Last n completed bars (all, if n is None) as of `as_of`.
        Structurally cannot return future data."""
        key = (symbol, str(timeframe))
        if key not in self._frames:
            raise KeyError(f"no history loaded for {key}")
        df = self._frames[key]
        visible = df[df["ts"] <= pd.Timestamp(as_of)]
        if n is not None:
            visible = visible.tail(n)
        return visible.reset_index(drop=True)
