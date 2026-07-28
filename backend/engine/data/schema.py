"""Canonical OHLCV schema, normalization, and validation.

Canonical DataFrame:
  columns : symbol, ts, open, high, low, close, volume, timeframe, source
  ts      : timezone-aware, UTC, sorted ascending, unique per (symbol, ts)
  ts MEANS the bar's COMPLETION time (close of the candle). This single
  convention is what makes multi-timeframe availability checks trivial and
  lookahead-safe: a bar is usable exactly when now >= ts.
  attrs["adjustment_mode"] : "raw" after normalization; changed only by
  the explicit adjustment layer. Never mixed silently.

Two distinct operations, never conflated:
  normalize(...)  MAY transform: parse/convert timestamps to UTC, order
                  columns, sort rows, attach metadata columns.
  validate(...)   NEVER mutates. It reports and (for hard violations)
                  raises. Corrupted data is rejected, not repaired.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from engine.calendar import WeekdayCalendar
from engine.data.schema_types import (
    AdjustmentMode,
    DataValidationError,
    Timeframe,
)

CANONICAL_COLUMNS = [
    "symbol", "ts", "open", "high", "low", "close", "volume", "timeframe", "source",
]
_PRICE_COLS = ["open", "high", "low", "close"]


@dataclass(slots=True)
class DataQualityReport:
    symbol: str
    timeframe: str
    n_rows: int
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    n_duplicate_keys: int = 0
    n_ohlc_violations: int = 0
    n_nonpositive_prices: int = 0
    n_negative_volume: int = 0
    missing_sessions: list[date] = field(default_factory=list)
    missing_intraday_bars: int = 0
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues and not self.missing_sessions and self.missing_intraday_bars == 0


def normalize(
    df: pd.DataFrame,
    *,
    symbol: str,
    timeframe: Timeframe,
    source: str,
    tz: str | None = None,
) -> pd.DataFrame:
    """Shape raw provider data into the canonical schema. `tz` names the
    input timezone for NAIVE timestamps; tz-aware inputs are converted to
    UTC as-is. Naive timestamps with no tz given are rejected."""
    required = {"ts", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise DataValidationError(f"missing columns for {symbol}: {sorted(missing)}")

    out = df.copy()
    ts = pd.to_datetime(out["ts"])
    if ts.dt.tz is None:
        if tz is None:
            raise DataValidationError(
                f"{symbol}: naive timestamps and no input timezone given; "
                "refusing to guess"
            )
        ts = ts.dt.tz_localize(tz)
    out["ts"] = ts.dt.tz_convert("UTC")

    out["symbol"] = symbol
    out["timeframe"] = str(timeframe)
    out["source"] = source
    for col in [*_PRICE_COLS, "volume"]:
        out[col] = out[col].astype(float)
    out = out[CANONICAL_COLUMNS].sort_values("ts", kind="stable").reset_index(drop=True)
    out.attrs["adjustment_mode"] = str(AdjustmentMode.RAW)
    return out


def validate(
    df: pd.DataFrame,
    *,
    calendar: WeekdayCalendar | None = None,
    on_missing: str = "ignore",   # "ignore" | "report" | "error"
) -> DataQualityReport:
    """Hard checks raise DataValidationError; completeness checks go to the
    report (or raise, per on_missing). Input is never modified."""
    if on_missing not in ("ignore", "report", "error"):
        raise ValueError("on_missing must be ignore | report | error")

    symbol = str(df["symbol"].iloc[0]) if len(df) else "?"
    timeframe = str(df["timeframe"].iloc[0]) if len(df) else "?"
    report = DataQualityReport(
        symbol=symbol,
        timeframe=timeframe,
        n_rows=len(df),
        start=df["ts"].min() if len(df) else None,
        end=df["ts"].max() if len(df) else None,
    )
    issues = report.issues

    if list(df.columns) != CANONICAL_COLUMNS:
        issues.append(f"non-canonical columns: {list(df.columns)}")
        raise DataValidationError(f"{symbol}: schema violation", issues)
    if len(df) == 0:
        return report

    ts = df["ts"]
    if ts.dt.tz is None or str(ts.dt.tz) != "UTC":
        issues.append("timestamps must be tz-aware UTC")
    if not ts.is_monotonic_increasing:
        issues.append("timestamps not sorted ascending")

    dup = df.duplicated(subset=["symbol", "ts"]).sum()
    if dup:
        report.n_duplicate_keys = int(dup)
        issues.append(f"{dup} duplicate (symbol, ts) rows")

    bad_high = (df["high"] < df[["open", "close", "low"]].max(axis=1)).sum()
    bad_low = (df["low"] > df[["open", "close", "high"]].min(axis=1)).sum()
    if bad_high or bad_low:
        report.n_ohlc_violations = int(bad_high + bad_low)
        issues.append(f"{report.n_ohlc_violations} OHLC ordering violations")

    nonpos = (df[_PRICE_COLS] <= 0).any(axis=1).sum()
    if nonpos:
        report.n_nonpositive_prices = int(nonpos)
        issues.append(f"{nonpos} rows with non-positive prices")

    negvol = (df["volume"] < 0).sum()
    if negvol:
        report.n_negative_volume = int(negvol)
        issues.append(f"{negvol} rows with negative volume")

    if issues:
        raise DataValidationError(f"{symbol} {timeframe}: corrupted data rejected", issues)

    # ── completeness vs calendar (soft unless on_missing='error') ─────
    if calendar is not None and on_missing != "ignore":
        tf = Timeframe(timeframe)
        have = set(ts)
        start_d, end_d = ts.min().date(), ts.max().date()
        for session in calendar.sessions(start_d, end_d):
            expected = calendar.expected_bar_times(session, tf)
            missing = [t for t in expected if pd.Timestamp(t) not in have]
            if tf is Timeframe.D1 and missing:
                report.missing_sessions.append(session)
            else:
                report.missing_intraday_bars += len(missing)
        if on_missing == "error" and (
            report.missing_sessions or report.missing_intraday_bars
        ):
            raise DataValidationError(
                f"{symbol} {timeframe}: missing bars",
                [
                    f"missing sessions: {report.missing_sessions}",
                    f"missing intraday bars: {report.missing_intraday_bars}",
                ],
            )
    return report
