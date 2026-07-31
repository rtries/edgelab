"""Real market data — thin proxy over Alpaca's market-data API.

Separate from ops/brokers/alpaca.py (which places orders against the
trading API): this only ever reads public price bars, using the same
API key/secret the deployment already has configured. No broker, no
risk engine, no order side effects — just OHLCV for charts.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.auth import AuthUser, get_current_user
from app.core.config import settings

router = APIRouter()

CurrentUser = Depends(get_current_user)

DATA_BASE_URL = "https://data.alpaca.markets"


class Bar(BaseModel):
    t: str
    o: float
    h: float
    l: float  # noqa: E741 — matches Alpaca's field name
    c: float
    v: float


@router.get("/market/bars")
def get_bars(
    symbol: str,
    timeframe: str = "1Day",
    limit: int = Query(120, le=1000),
    user: AuthUser = CurrentUser,
) -> list[Bar]:
    if not settings.alpaca_api_key or not settings.alpaca_api_secret:
        raise HTTPException(
            status_code=500,
            detail="ALPACA_API_KEY / ALPACA_API_SECRET are not configured",
        )
    start = (datetime.now(UTC) - timedelta(days=max(limit * 3, 400))).strftime("%Y-%m-%d")
    qs = urllib.parse.urlencode(
        {"timeframe": timeframe, "start": start, "limit": limit, "feed": "iex", "adjustment": "raw"}
    )
    url = f"{DATA_BASE_URL}/v2/stocks/{symbol.upper()}/bars?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise HTTPException(status_code=exc.code, detail=f"Alpaca market data error: {detail}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"could not reach Alpaca market data: {exc}") from exc

    bars = payload.get("bars") or []
    if not bars:
        raise HTTPException(
            status_code=404,
            detail=f"no bars returned for {symbol} — check the symbol is valid and markets have traded recently",
        )
    return [Bar(t=b["t"], o=b["o"], h=b["h"], l=b["l"], c=b["c"], v=b["v"]) for b in bars]
