"""Canonical schema: normalization, validation, calendar completeness."""
from datetime import UTC, date, datetime, time

import pandas as pd
import pytest

from engine.calendar import WeekdayCalendar
from engine.data.schema import normalize, validate
from engine.data.schema_types import DataValidationError, Timeframe

from tests.helpers_data import canon_daily, raw_daily

# Jan 2024: 1st = Mon. Days 1-5 are Mon-Fri.
GOOD = [(1, 10, 11, 9, 10.5, 100), (2, 10.5, 12, 10, 11, 120), (3, 11, 11.5, 10.5, 11, 90)]


def test_normalize_produces_canonical_utc_sorted():
    df = canon_daily(GOOD)
    assert list(df.columns) == [
        "symbol", "ts", "open", "high", "low", "close", "volume", "timeframe", "source"
    ]
    assert str(df["ts"].dt.tz) == "UTC"
    assert df["ts"].is_monotonic_increasing
    assert df.attrs["adjustment_mode"] == "raw"
    validate(df)  # no raise


def test_naive_timestamps_without_tz_are_refused():
    with pytest.raises(DataValidationError, match="refusing to guess"):
        normalize(raw_daily(GOOD, tz_aware=False), symbol="X", timeframe=Timeframe.D1, source="t")


def test_timezone_conversion_to_utc():
    # 16:00 America/New_York on 2024-01-02 == 21:00 UTC (EST, UTC-5).
    raw = raw_daily([(2, 10, 11, 9, 10, 100)], tz_aware=False)
    df = normalize(raw, symbol="X", timeframe=Timeframe.D1, source="t", tz="America/New_York")
    # Input said 21:00 naive; localized to NY that's 21:00 EST = 02:00 UTC next day
    assert df["ts"].iloc[0] == pd.Timestamp("2024-01-03 02:00:00", tz="UTC")


def test_high_below_close_rejected():
    bad = [(1, 10, 10.2, 9, 10.5, 100)]  # close 10.5 > high 10.2
    df = canon_daily(bad)
    with pytest.raises(DataValidationError, match="OHLC ordering"):
        validate(df)


def test_low_above_open_rejected():
    bad = [(1, 10, 11, 10.4, 10.6, 100)]  # open 10 < low 10.4
    df_ok_shape = canon_daily(bad)
    with pytest.raises(DataValidationError, match="OHLC ordering"):
        validate(df_ok_shape)


def test_nonpositive_price_rejected():
    bad = [(1, 0.0, 1, 0.0, 0.5, 100)]
    with pytest.raises(DataValidationError, match="non-positive"):
        validate(canon_daily(bad))


def test_negative_volume_rejected():
    bad = [(1, 10, 11, 9, 10, -5)]
    with pytest.raises(DataValidationError, match="negative volume"):
        validate(canon_daily(bad))


def test_duplicate_symbol_ts_rejected_never_repaired():
    df = canon_daily([(1, 10, 11, 9, 10, 100), (1, 10, 11, 9, 10.2, 100)])
    n_before = len(df)
    with pytest.raises(DataValidationError, match="duplicate"):
        validate(df)
    assert len(df) == n_before  # untouched: rejected, not repaired


def test_validation_never_mutates_input():
    df = canon_daily(GOOD)
    frozen = df.copy(deep=True)
    validate(df)
    pd.testing.assert_frame_equal(df, frozen)


def test_missing_session_detected_with_calendar():
    # Days 1,2,4 present; day 3 (Wed) is a session -> missing.
    cal = WeekdayCalendar()
    df = canon_daily([(1, 10, 11, 9, 10, 100), (2, 10, 11, 9, 10, 100), (4, 10, 11, 9, 10, 100)])
    report = validate(df, calendar=cal, on_missing="report")
    assert report.missing_sessions == [date(2024, 1, 3)]
    with pytest.raises(DataValidationError, match="missing bars"):
        validate(df, calendar=cal, on_missing="error")


def test_holiday_is_not_a_missing_session():
    cal = WeekdayCalendar(holidays=frozenset({date(2024, 1, 3)}))
    df = canon_daily([(1, 10, 11, 9, 10, 100), (2, 10, 11, 9, 10, 100), (4, 10, 11, 9, 10, 100)])
    report = validate(df, calendar=cal, on_missing="report")
    assert report.missing_sessions == []
    assert report.ok


def test_early_close_reduces_expected_intraday_bars():
    cal = WeekdayCalendar(early_closes=((date(2024, 1, 2), time(18, 0)),))
    # Normal session 14:30-21:00 -> 6.5h -> 6 hourly bars (15:30..20:30, close 21:00 not on the hour grid: bars at 15:30,16:30,17:30,18:30,19:30,20:30)
    normal = cal.expected_bar_times(date(2024, 1, 3), Timeframe.H1)
    early = cal.expected_bar_times(date(2024, 1, 2), Timeframe.H1)
    assert len(normal) == 6
    # Early close 18:00 -> bars 15:30, 16:30, 17:30 = 3
    assert len(early) == 3
    assert early[-1] == datetime(2024, 1, 2, 17, 30, tzinfo=UTC)


def test_daily_expected_bar_is_session_close():
    cal = WeekdayCalendar()
    assert cal.expected_bar_times(date(2024, 1, 2), Timeframe.D1) == [
        datetime(2024, 1, 2, 21, 0, tzinfo=UTC)
    ]
    assert cal.expected_bar_times(date(2024, 1, 6), Timeframe.D1) == []  # Saturday
