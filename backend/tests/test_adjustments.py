"""Corporate actions: split, reverse split, dividend. Hand-calculated."""
from datetime import date

import pytest

from engine.data.adjustments import Dividend, Split, adjust
from engine.data.schema_types import AdjustmentMode, DataValidationError

from tests.helpers_data import canon_daily


def test_split_back_adjustment():
    # Raw closes: d1=100, d2=102, d3=51 with a 2-for-1 split ex d3.
    # Bars BEFORE d3: prices / 2, volume * 2.
    # Adjusted closes: [50, 51, 51]; volumes [200, 240, 100].
    df = canon_daily([(1, 99, 101, 98, 100, 100), (2, 100, 103, 99, 102, 120),
                      (3, 50, 52, 49, 51, 100)])
    out = adjust(df, splits=[Split(date(2024, 1, 3), 2.0)], mode=AdjustmentMode.SPLIT)
    assert list(out["close"]) == pytest.approx([50.0, 51.0, 51.0])
    assert list(out["open"]) == pytest.approx([49.5, 50.0, 50.0])
    assert list(out["volume"]) == pytest.approx([200.0, 240.0, 100.0])
    assert out.attrs["adjustment_mode"] == "split"
    # Raw input untouched
    assert list(df["close"]) == pytest.approx([100.0, 102.0, 51.0])


def test_reverse_split():
    # 1-for-2 reverse split (ratio 0.5) ex d2: prices before double, volume halves.
    # Raw closes [50 (d1), 100 (d2)] -> adjusted [100, 100]; volumes [100, 80] -> [50, 80].
    df = canon_daily([(1, 49, 51, 48, 50, 100), (2, 99, 101, 98, 100, 80)])
    out = adjust(df, splits=[Split(date(2024, 1, 2), 0.5)], mode=AdjustmentMode.SPLIT)
    assert list(out["close"]) == pytest.approx([100.0, 100.0])
    assert list(out["volume"]) == pytest.approx([50.0, 80.0])


def test_dividend_total_return():
    # Closes [100 (d1), 101 (d2), 100 (d3)], $1.00 dividend ex d3.
    # Prior close = 101 -> factor = (101 - 1)/101 = 100/101.
    # TR closes: d1 = 100 * 100/101 = 99.00990099, d2 = 101 * 100/101 = 100.0, d3 = 100.
    df = canon_daily([(1, 100, 100.5, 99, 100, 100), (2, 100, 101.5, 100, 101, 100),
                      (3, 100, 100.5, 99, 100, 100)])
    out = adjust(df, dividends=[Dividend(date(2024, 1, 3), 1.0)], mode=AdjustmentMode.TOTAL_RETURN)
    assert out["close"].iloc[0] == pytest.approx(99.00990099, rel=1e-9)
    assert out["close"].iloc[1] == pytest.approx(100.0)
    assert out["close"].iloc[2] == pytest.approx(100.0)


def test_split_then_dividend_combined():
    # 2:1 split ex d2, then $0.50 dividend ex d3.
    # Raw closes [100 (d1), 51 (d2), 50 (d3)], volumes [100,100,100].
    # After split: closes [50, 51, 50].
    # Dividend ex d3: prior split-adj close = 51. Dividend declared post-split,
    # its ex_date has no later splits, so d' = 0.50.
    # factor = (51 - 0.5)/51 = 50.5/51.
    # d1 = 50 * 50.5/51 = 49.50980392 ; d2 = 51 * 50.5/51 = 50.5 ; d3 = 50.
    df = canon_daily([(1, 99, 101, 98, 100, 100), (2, 50, 52, 49, 51, 100),
                      (3, 49, 51, 48, 50, 100)])
    out = adjust(
        df,
        splits=[Split(date(2024, 1, 2), 2.0)],
        dividends=[Dividend(date(2024, 1, 3), 0.5)],
        mode=AdjustmentMode.TOTAL_RETURN,
    )
    assert out["close"].iloc[0] == pytest.approx(49.50980392, rel=1e-8)
    assert out["close"].iloc[1] == pytest.approx(50.5)
    assert out["close"].iloc[2] == pytest.approx(50.0)


def test_raw_mode_is_passthrough_with_label():
    df = canon_daily([(1, 10, 11, 9, 10, 100)])
    out = adjust(df, mode=AdjustmentMode.RAW)
    assert list(out["close"]) == [10.0]
    assert out.attrs["adjustment_mode"] == "raw"


def test_double_adjustment_refused():
    df = canon_daily([(1, 10, 11, 9, 10, 100), (2, 10, 11, 9, 10, 100)])
    once = adjust(df, splits=[Split(date(2024, 1, 2), 2.0)], mode=AdjustmentMode.SPLIT)
    with pytest.raises(DataValidationError, match="already in mode"):
        adjust(once, splits=[Split(date(2024, 1, 2), 2.0)], mode=AdjustmentMode.SPLIT)


def test_dividend_larger_than_close_rejected():
    df = canon_daily([(1, 1.0, 1.1, 0.9, 1.0, 100), (2, 1.0, 1.1, 0.9, 1.0, 100)])
    with pytest.raises(DataValidationError, match="corrupt"):
        adjust(df, dividends=[Dividend(date(2024, 1, 2), 2.0)], mode=AdjustmentMode.TOTAL_RETURN)


def test_mixed_modes_refused_by_feed_and_history():
    from engine.data.feeds import DataFrameFeed
    from engine.data.history import HistoryService

    raw = canon_daily([(1, 10, 11, 9, 10, 100)], symbol="A")
    adj = adjust(
        canon_daily([(1, 10, 11, 9, 10, 100)], symbol="B"),
        splits=[Split(date(2024, 1, 2), 2.0)],
        mode=AdjustmentMode.SPLIT,
    )
    with pytest.raises(DataValidationError, match="mixed adjustment"):
        DataFrameFeed({"A": raw, "B": adj})
    with pytest.raises(DataValidationError, match="mixed adjustment"):
        HistoryService({("A", "1d"): raw, ("B", "1d"): adj})
