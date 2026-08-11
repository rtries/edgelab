"""Real market data, plus a paper-only manual trading endpoint.

Bars: a thin proxy over Alpaca's market-data API — read-only, no side
effects, using the same API key/secret the deployment already has
configured.

Manual orders (POST /market/paper-order): DELIBERATELY separate from
ops/brokers/alpaca.py's AlpacaBroker, which places orders on behalf of
a deployment and is gated by that deployment's lifecycle status (paper
vs. live) plus a server-wide ALPACA_PAPER switch — the whole point of
that machinery is that nothing can place a *live* order without
earning "live" status through validated backtests and paper evidence.
A simple "buy any symbol you like" UI doesn't fit that model at all, so
rather than bypass or weaken that gate, this endpoint hardcodes Alpaca's
paper base URL unconditionally — there is no code path here that can
ever place a real-money order, regardless of any deployment or settings
state. If real-money manual trading is wanted later, it needs its own
explicit design, not a shortcut through this endpoint.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import AuthUser, get_current_user
from app.core.config import settings

router = APIRouter()

CurrentUser = Depends(get_current_user)

DATA_BASE_URL = "https://data.alpaca.markets"
PAPER_TRADING_BASE_URL = "https://paper-api.alpaca.markets"


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
    # Alpaca returns bars ascending from `start`, so a plain `limit` cuts
    # off the OLDEST bars in [start, now] rather than the most recent —
    # sort=desc gets the most recent `limit` bars instead; reversed below
    # back into ascending order for charting.
    #
    # Intraday timeframes (Min/Hour) need their own lookback: the daily
    # heuristic (limit*3 days) would ask for hundreds of days of minute
    # bars for a "1D" chart. A handful of calendar days safely covers
    # weekends/holidays while still bounding the request.
    if timeframe.endswith("Min") or timeframe.endswith("Hour"):
        start = (datetime.now(UTC) - timedelta(days=6)).strftime("%Y-%m-%d")
    else:
        start = (datetime.now(UTC) - timedelta(days=max(limit * 3, 400))).strftime("%Y-%m-%d")
    qs = urllib.parse.urlencode(
        {"timeframe": timeframe, "start": start, "limit": limit, "feed": "iex", "adjustment": "raw", "sort": "desc"}
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
    bars.reverse()  # sort=desc above; charts want ascending chronological order
    return [Bar(t=b["t"], o=b["o"], h=b["h"], l=b["l"], c=b["c"], v=b["v"]) for b in bars]


def _alpaca_data_request(path: str) -> dict:
    """GET against Alpaca's market-data API (read-only, same key/secret
    as /market/bars — no order side effects, see module docstring)."""
    if not settings.alpaca_api_key or not settings.alpaca_api_secret:
        raise HTTPException(
            status_code=500,
            detail="ALPACA_API_KEY / ALPACA_API_SECRET are not configured",
        )
    req = urllib.request.Request(
        f"{DATA_BASE_URL}{path}",
        headers={
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise HTTPException(status_code=exc.code, detail=f"Alpaca market data error: {detail}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"could not reach Alpaca market data: {exc}") from exc


class NewsItem(BaseModel):
    id: int
    headline: str
    summary: str
    author: str
    source: str
    url: str
    created_at: str
    symbols: list[str]


@router.get("/market/news")
def get_news(symbol: str, limit: int = Query(10, le=50), user: AuthUser = CurrentUser) -> list[NewsItem]:
    """Real headlines from Alpaca's News API — same bundled data
    entitlement as bars, no separate provider/key needed."""
    qs = urllib.parse.urlencode({"symbols": symbol.upper(), "limit": limit, "sort": "desc"})
    payload = _alpaca_data_request(f"/v1beta1/news?{qs}")
    items = payload.get("news") or []
    return [
        NewsItem(
            id=n["id"],
            headline=n["headline"],
            summary=n.get("summary", ""),
            author=n.get("author", ""),
            source=n.get("source", ""),
            url=n.get("url", ""),
            created_at=n["created_at"],
            symbols=n.get("symbols", []),
        )
        for n in items
    ]


def _alpaca_headers() -> dict:
    if not settings.alpaca_api_key or not settings.alpaca_api_secret:
        raise HTTPException(
            status_code=500,
            detail="ALPACA_API_KEY / ALPACA_API_SECRET are not configured",
        )
    return {
        "APCA-API-KEY-ID": settings.alpaca_api_key,
        "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
        "Content-Type": "application/json",
    }


def _alpaca_paper_request(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{PAPER_TRADING_BASE_URL}{path}", data=data, headers=_alpaca_headers(), method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise HTTPException(status_code=exc.code, detail=f"Alpaca paper trading error: {detail}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"could not reach Alpaca: {exc}") from exc


class PaperOrderRequest(BaseModel):
    symbol: str
    side: str = Field(pattern="^(buy|sell)$")
    qty: float = Field(gt=0)
    order_type: str = Field(default="market", pattern="^(market|limit|stop|stop_limit|bracket)$")
    limit_price: float | None = None
    stop_price: float | None = None
    # bracket-only: the entry order's own type (market or limit), plus the
    # attached take-profit/stop-loss legs Alpaca submits as one order.
    bracket_entry_type: str = Field(default="market", pattern="^(market|limit)$")
    take_profit_price: float | None = None
    stop_loss_price: float | None = None
    time_in_force: str = "day"


@router.post("/market/paper-order")
def submit_paper_order(req: PaperOrderRequest, user: AuthUser = CurrentUser) -> dict:
    """Places a real order in Alpaca's PAPER environment only — see the
    module docstring for why this never touches live trading.

    Supports market/limit/stop/stop_limit, plus bracket orders (entry +
    attached take-profit and stop-loss legs, submitted to Alpaca as one
    order via order_class=bracket) — the advanced-order priority list
    from the product spec, all still paper-only."""
    if req.order_type == "limit" and req.limit_price is None:
        raise HTTPException(status_code=422, detail="limit_price is required for a limit order")
    if req.order_type == "stop" and req.stop_price is None:
        raise HTTPException(status_code=422, detail="stop_price is required for a stop order")
    if req.order_type == "stop_limit" and (req.stop_price is None or req.limit_price is None):
        raise HTTPException(status_code=422, detail="stop_price and limit_price are required for a stop-limit order")
    if req.order_type == "bracket":
        if req.take_profit_price is None or req.stop_loss_price is None:
            raise HTTPException(
                status_code=422, detail="take_profit_price and stop_loss_price are required for a bracket order"
            )
        if req.bracket_entry_type == "limit" and req.limit_price is None:
            raise HTTPException(status_code=422, detail="limit_price is required for a limit-entry bracket order")

    body: dict = {
        "symbol": req.symbol.upper(),
        "qty": str(req.qty),
        "side": req.side,
        "time_in_force": req.time_in_force,
    }
    if req.order_type == "bracket":
        body["type"] = req.bracket_entry_type
        body["order_class"] = "bracket"
        body["take_profit"] = {"limit_price": str(req.take_profit_price)}
        body["stop_loss"] = {"stop_price": str(req.stop_loss_price)}
        if req.bracket_entry_type == "limit":
            body["limit_price"] = str(req.limit_price)
    else:
        body["type"] = req.order_type
        if req.limit_price is not None:
            body["limit_price"] = str(req.limit_price)
        if req.stop_price is not None:
            body["stop_price"] = str(req.stop_price)
    return _alpaca_paper_request("POST", "/v2/orders", body)


@router.get("/market/paper-orders")
def list_paper_orders(limit: int = Query(20, le=100), user: AuthUser = CurrentUser) -> list[dict]:
    """Recent orders from Alpaca's PAPER account — shared across whoever
    has these API keys configured, same as the rest of the Alpaca
    integration; not scoped per EdgeLab user."""
    qs = urllib.parse.urlencode({"status": "all", "limit": limit, "direction": "desc"})
    return _alpaca_paper_request("GET", f"/v2/orders?{qs}")


@router.get("/market/paper-account")
def get_paper_account(user: AuthUser = CurrentUser) -> dict:
    """Equity/cash/buying-power/day-P&L for the shared Alpaca PAPER
    account — same sharing caveat as orders above: not per-EdgeLab-user,
    it's whoever's paper account these API keys point at."""
    return _alpaca_paper_request("GET", "/v2/account")


@router.get("/market/paper-positions")
def list_paper_positions(user: AuthUser = CurrentUser) -> list[dict]:
    """Open positions in the shared Alpaca PAPER account."""
    return _alpaca_paper_request("GET", "/v2/positions")
