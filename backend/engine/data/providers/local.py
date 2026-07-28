"""Local-file providers: CSV and Parquet.

File layout: one file per symbol, columns ts, open, high, low, close,
volume. Timestamps may be tz-aware or naive (pass `tz` for naive files —
guessing is refused by normalize()).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from engine.data.schema import normalize, validate
from engine.data.schema_types import Timeframe


class _FileProvider:
    suffix = ""

    def __init__(self, root: Path, tz: str | None = None, source: str | None = None) -> None:
        self.root = Path(root)
        self.tz = tz
        self._source = source or self.name

    @property
    def name(self) -> str:
        raise NotImplementedError

    def _read(self, path: Path) -> pd.DataFrame:
        raise NotImplementedError

    def fetch(
        self, symbol: str, timeframe: Timeframe, start: date, end: date
    ) -> pd.DataFrame:
        path = self.root / f"{symbol}{self.suffix}"
        raw = self._read(path)
        df = normalize(raw, symbol=symbol, timeframe=timeframe, source=self._source, tz=self.tz)
        mask = (df["ts"].dt.date >= start) & (df["ts"].dt.date <= end)
        df = df.loc[mask].reset_index(drop=True)
        df.attrs["adjustment_mode"] = "raw"
        validate(df)
        return df


class CSVProvider(_FileProvider):
    suffix = ".csv"

    @property
    def name(self) -> str:
        return "csv"

    def _read(self, path: Path) -> pd.DataFrame:
        return pd.read_csv(path)


class ParquetProvider(_FileProvider):
    suffix = ".parquet"

    @property
    def name(self) -> str:
        return "parquet"

    def _read(self, path: Path) -> pd.DataFrame:
        return pd.read_parquet(path)
