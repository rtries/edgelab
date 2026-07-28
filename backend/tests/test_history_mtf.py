"""Multi-timeframe / point-in-time history: lookahead is structurally impossible."""
from datetime import UTC, datetime

import pandas as pd
import pytest

from engine.data.history import HistoryService
from engine.data.schema import normalize
from engine.data.schema_types import Timeframe

from tests.helpers_data import canon_daily


def hourly_frame(symbol="X"):
    # Three hourly bars on Jan 2 completing 15:30, 16:30, 17:30 UTC.
    ts = [datetime(2024, 1, 2, h, 30, tzinfo=UTC) for h in (15, 16, 17)]
    raw = pd.DataFrame({
        "ts": ts,
        "open": [10.0, 10.2, 10.4], "high": [10.3, 10.5, 10.6],
        "low": [9.9, 10.1, 10.3], "close": [10.2, 10.4, 10.5],
        "volume": [10, 12, 9],
    })
    return normalize(raw, symbol=symbol, timeframe=Timeframe.H1, source="test")


def service():
    daily = canon_daily([
        (1, 10, 11, 9, 10.5, 100),   # completes Jan 1 21:00
        (2, 10, 11, 9, 10.8, 100),   # completes Jan 2 21:00
    ])
    return HistoryService({("X", "1d"): daily, ("X", "1h"): hourly_frame()})


def test_daily_bar_invisible_before_session_close():
    svc = service()
    # Mid-session Jan 2 (16:45 UTC): today's daily candle is NOT complete.
    midday = datetime(2024, 1, 2, 16, 45, tzinfo=UTC)
    visible = svc.history("X", "1d", as_of=midday)
    assert len(visible) == 1                       # only Jan 1's daily bar
    assert visible["ts"].iloc[0] == pd.Timestamp("2024-01-01 21:00", tz="UTC")
    # ...while completed hourly bars ARE visible (15:30 and 16:30, not 17:30).
    hourly = svc.history("X", "1h", as_of=midday)
    assert list(hourly["ts"]) == [
        pd.Timestamp("2024-01-02 15:30", tz="UTC"),
        pd.Timestamp("2024-01-02 16:30", tz="UTC"),
    ]


def test_daily_bar_visible_exactly_at_close():
    svc = service()
    at_close = datetime(2024, 1, 2, 21, 0, tzinfo=UTC)
    visible = svc.history("X", "1d", as_of=at_close)
    assert len(visible) == 2                       # completed == usable


def test_history_never_returns_future_rows():
    svc = service()
    for as_of in [
        datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
        datetime(2024, 1, 2, 15, 30, tzinfo=UTC),
        datetime(2024, 1, 2, 23, 0, tzinfo=UTC),
    ]:
        for tf in ("1d", "1h"):
            visible = svc.history("X", tf, as_of=as_of)
            if len(visible):
                assert visible["ts"].max() <= pd.Timestamp(as_of)


def test_tail_n_returns_most_recent_completed():
    svc = service()
    last1 = svc.history("X", "1h", as_of=datetime(2024, 1, 2, 23, 0, tzinfo=UTC), n=1)
    assert len(last1) == 1
    assert last1["close"].iloc[0] == 10.5          # the 17:30 bar


def test_unknown_series_raises():
    svc = service()
    with pytest.raises(KeyError):
        svc.history("Y", "1d", as_of=datetime(2024, 1, 2, tzinfo=UTC))
