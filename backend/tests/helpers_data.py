"""Canonical-frame factories for data-layer tests."""
from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from engine.data.schema import normalize


def raw_daily(rows: list[tuple], tz_aware: bool = True) -> pd.DataFrame:
    """rows: (day, o, h, l, c, v) in Jan 2024. ts stamped at 21:00 UTC
    (session close) when tz_aware, else naive."""
    ts = [
        datetime(2024, 1, d, 21, 0, tzinfo=UTC if tz_aware else None)
        for d, *_ in rows
    ]
    return pd.DataFrame(
        {
            "ts": ts,
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
            "volume": [r[5] for r in rows],
        }
    )


def canon_daily(rows: list[tuple], symbol: str = "X", source: str = "test") -> pd.DataFrame:
    from engine.data.schema_types import Timeframe

    return normalize(raw_daily(rows), symbol=symbol, timeframe=Timeframe.D1, source=source)
