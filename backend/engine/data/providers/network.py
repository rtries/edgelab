"""Network provider adapters: Yahoo Finance, Alpaca, Polygon.

Isolation rules (enforced by design, tested without internet):
- HTTP happens only through an injected `transport(url, params, headers)
  -> dict` callable. Tests inject fakes; production uses _http_transport.
- Credentials come from environment variables (or explicit constructor
  args). NOTHING is hardcoded. Missing creds raise MissingCredentialsError
  at construction, not mid-fetch.
- Every adapter returns CANONICAL frames with ts = bar COMPLETION time:
  * Daily bars are re-stamped to the calendar's session close for their
    trading date (providers stamp daily bars at open/midnight — ambiguous
    and lookahead-prone if used as-is).
  * Intraday bars from providers that stamp bar START (Alpaca, Polygon)
    get + timeframe.delta.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from engine.calendar import WeekdayCalendar
from engine.data.schema import normalize, validate
from engine.data.schema_types import MissingCredentialsError, Timeframe

Transport = Callable[[str, dict[str, Any], dict[str, str]], dict]


def _http_transport(url: str, params: dict[str, Any], headers: dict[str, str]) -> dict:
    import httpx

    resp = httpx.get(url, params=params, headers=headers, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def _to_session_close(ts_utc: pd.Series, calendar: WeekdayCalendar) -> pd.Series:
    return ts_utc.map(lambda t: calendar.session_close(t.date()))


class YahooProvider:
    """Yahoo v8 chart API. No API key. Returns RAW quotes (not adjclose)."""

    BASE = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    _INTERVAL = {Timeframe.D1: "1d", Timeframe.H1: "1h", Timeframe.M1: "1m"}

    def __init__(
        self,
        transport: Transport | None = None,
        calendar: WeekdayCalendar | None = None,
    ) -> None:
        self.transport = transport or _http_transport
        self.calendar = calendar or WeekdayCalendar()

    @property
    def name(self) -> str:
        return "yahoo"

    def fetch(
        self, symbol: str, timeframe: Timeframe, start: date, end: date
    ) -> pd.DataFrame:
        params = {
            "period1": int(datetime.combine(start, datetime.min.time(), tzinfo=UTC).timestamp()),
            "period2": int(datetime.combine(end, datetime.max.time(), tzinfo=UTC).timestamp()),
            "interval": self._INTERVAL[timeframe],
        }
        payload = self.transport(self.BASE.format(symbol=symbol), params, {})
        result = payload["chart"]["result"][0]
        quote = result["indicators"]["quote"][0]
        raw = pd.DataFrame(
            {
                "ts": pd.to_datetime(result["timestamp"], unit="s", utc=True),
                "open": quote["open"],
                "high": quote["high"],
                "low": quote["low"],
                "close": quote["close"],
                "volume": quote["volume"],
            }
        ).dropna()
        if timeframe is Timeframe.D1:
            raw["ts"] = _to_session_close(raw["ts"], self.calendar)
        df = normalize(raw, symbol=symbol, timeframe=timeframe, source=self.name)
        validate(df)
        return df


class AlpacaProvider:
    """Alpaca Market Data v2. Credentials: ALPACA_API_KEY / ALPACA_API_SECRET."""

    BASE = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"
    _TF = {Timeframe.D1: "1Day", Timeframe.H1: "1Hour", Timeframe.M1: "1Min"}

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        transport: Transport | None = None,
        calendar: WeekdayCalendar | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("ALPACA_API_SECRET", "")
        if not self.api_key or not self.api_secret:
            raise MissingCredentialsError(
                "Alpaca credentials missing: set ALPACA_API_KEY and ALPACA_API_SECRET"
            )
        self.transport = transport or _http_transport
        self.calendar = calendar or WeekdayCalendar()

    @property
    def name(self) -> str:
        return "alpaca"

    def fetch(
        self, symbol: str, timeframe: Timeframe, start: date, end: date
    ) -> pd.DataFrame:
        params = {
            "timeframe": self._TF[timeframe],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "adjustment": "raw",
            "limit": 10_000,
        }
        headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }
        payload = self.transport(self.BASE.format(symbol=symbol), params, headers)
        bars = payload.get("bars") or []
        raw = pd.DataFrame(
            {
                "ts": pd.to_datetime([b["t"] for b in bars], utc=True),
                "open": [b["o"] for b in bars],
                "high": [b["h"] for b in bars],
                "low": [b["l"] for b in bars],
                "close": [b["c"] for b in bars],
                "volume": [b["v"] for b in bars],
            }
        )
        if timeframe is Timeframe.D1:
            raw["ts"] = _to_session_close(raw["ts"], self.calendar)
        else:
            raw["ts"] = raw["ts"] + timeframe.delta  # Alpaca stamps bar START
        df = normalize(raw, symbol=symbol, timeframe=timeframe, source=self.name)
        validate(df)
        return df


class PolygonProvider:
    """Polygon aggregates v2. Credential: POLYGON_API_KEY."""

    BASE = "https://api.polygon.io/v2/aggs/ticker/{symbol}/range/{mult}/{span}/{start}/{end}"
    _RANGE = {Timeframe.D1: (1, "day"), Timeframe.H1: (1, "hour"), Timeframe.M1: (1, "minute")}

    def __init__(
        self,
        api_key: str | None = None,
        transport: Transport | None = None,
        calendar: WeekdayCalendar | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("POLYGON_API_KEY", "")
        if not self.api_key:
            raise MissingCredentialsError("Polygon credential missing: set POLYGON_API_KEY")
        self.transport = transport or _http_transport
        self.calendar = calendar or WeekdayCalendar()

    @property
    def name(self) -> str:
        return "polygon"

    def fetch(
        self, symbol: str, timeframe: Timeframe, start: date, end: date
    ) -> pd.DataFrame:
        mult, span = self._RANGE[timeframe]
        url = self.BASE.format(
            symbol=symbol, mult=mult, span=span, start=start.isoformat(), end=end.isoformat()
        )
        payload = self.transport(url, {"adjusted": "false", "apiKey": self.api_key}, {})
        results = payload.get("results") or []
        raw = pd.DataFrame(
            {
                "ts": pd.to_datetime([r["t"] for r in results], unit="ms", utc=True),
                "open": [r["o"] for r in results],
                "high": [r["h"] for r in results],
                "low": [r["l"] for r in results],
                "close": [r["c"] for r in results],
                "volume": [r["v"] for r in results],
            }
        )
        if timeframe is Timeframe.D1:
            raw["ts"] = _to_session_close(raw["ts"], self.calendar)
        else:
            raw["ts"] = raw["ts"] + timeframe.delta  # Polygon stamps bar START
        df = normalize(raw, symbol=symbol, timeframe=timeframe, source=self.name)
        validate(df)
        return df
