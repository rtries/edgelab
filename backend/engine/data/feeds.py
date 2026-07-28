"""Data feeds.

Feed contract (the backtester also asserts this):
- Bars in non-decreasing global time order; strictly increasing per symbol.
- Timezone-aware timestamps only.
"""
from __future__ import annotations

import heapq
from collections.abc import Iterator, Sequence
from pathlib import Path

import pandas as pd

from engine.types import Bar


class InMemoryFeed:
    """Merges per-symbol bar lists into one time-ordered stream.
    Ties on timestamp are broken by symbol name for determinism."""

    def __init__(self, bars: Sequence[Bar]) -> None:
        self._bars = sorted(bars, key=lambda b: (b.ts, b.symbol))
        self._symbols = sorted({b.symbol for b in bars})

    @property
    def symbols(self) -> Sequence[str]:
        return self._symbols

    def __iter__(self) -> Iterator[Bar]:
        return iter(self._bars)


class ParquetFeed:
    """Reads per-symbol parquet files named {SYMBOL}.parquet with columns:
    ts (tz-aware), open, high, low, close, volume. Streams a heap-merge
    so memory stays flat regardless of symbol count."""

    def __init__(self, root: Path, symbols: Sequence[str]) -> None:
        self.root = Path(root)
        self._symbols = list(symbols)

    @property
    def symbols(self) -> Sequence[str]:
        return self._symbols

    def _symbol_iter(self, symbol: str) -> Iterator[Bar]:
        df = pd.read_parquet(self.root / f"{symbol}.parquet")
        for row in df.itertuples(index=False):
            yield Bar(
                symbol=symbol,
                ts=row.ts.to_pydatetime() if hasattr(row.ts, "to_pydatetime") else row.ts,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )

    def __iter__(self) -> Iterator[Bar]:
        streams = [self._symbol_iter(s) for s in self._symbols]
        merged = heapq.merge(*streams, key=lambda b: (b.ts, b.symbol))
        yield from merged


class DataFrameFeed:
    """Builds an execution-bar stream from canonical frames (one timeframe).
    All frames must share one adjustment mode; ties on ts break by symbol."""

    def __init__(self, frames: dict[str, "pd.DataFrame"]) -> None:
        from engine.data.schema_types import DataValidationError

        modes = {df.attrs.get("adjustment_mode", "raw") for df in frames.values()}
        if len(modes) > 1:
            raise DataValidationError(
                f"mixed adjustment modes in feed frames: {sorted(modes)}"
            )
        self.adjustment_mode = modes.pop() if modes else "raw"
        bars: list[Bar] = []
        for symbol, df in frames.items():
            for row in df.itertuples(index=False):
                bars.append(
                    Bar(
                        symbol=symbol,
                        ts=row.ts.to_pydatetime(),
                        open=float(row.open),
                        high=float(row.high),
                        low=float(row.low),
                        close=float(row.close),
                        volume=float(row.volume),
                    )
                )
        self._bars = sorted(bars, key=lambda b: (b.ts, b.symbol))
        self._symbols = sorted(frames)

    @property
    def symbols(self) -> Sequence[str]:
        return self._symbols

    def __iter__(self) -> Iterator[Bar]:
        return iter(self._bars)
