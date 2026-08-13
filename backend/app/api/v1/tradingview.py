"""TradingView alert intake — paper only.

TradingView has no general trading API; the only officially supported
outbound mechanism is Alerts -> Webhook URL, which does a plain POST of
the alert's message text to a configured URL. Webhooks cannot carry
custom headers, so auth has to live in the URL itself: each user gets
an opaque per-account token baked into their webhook path
(POST /tradingview/signal/{token}).

CRITICAL SEPARATION (per product spec — a TradingView alert must never
directly equal an order): every signal goes through the same pipeline
as the background auto-trader before anything is placed —

    token -> user  =>  AUTHENTICATION
    get_decision()  =>  DECISION ENGINE  (still placeholder — see decision.py)
    cooldown + open-position + kill-switch checks  =>  RISK ENGINE
    _place_paper_order()  =>  EXECUTION ENGINE  (paper base URL, unconditional)

An alert whose symbol EdgeLab's Decision Engine doesn't currently rate
BUY_NOW/SELL_NOW is accepted (200, for TradingView's sake) but not
acted on — the alert firing is not sufficient on its own, matching
"setup quality != entry timing" from the decision contract.

Paper only, same as every other automation surface in this codebase.
There is no live-money path through this file.
"""
from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.v1.decision import get_decision
from app.core.auth import AuthUser, get_current_user
from ops.auto_trader import (
    AUTO_TRADE_NOTIONAL_USD,
    COOLDOWN,
    _emergency_stop_active,
    _notify_telegram,
    _open_position_symbols,
    _ops_root,
    _place_paper_order,
    _read_json,
    _state_path,
    _write_json,
)

router = APIRouter()

CurrentUser = Depends(get_current_user)


def _tokens_path() -> Path:
    path = _ops_root() / "_tradingview"
    path.mkdir(parents=True, exist_ok=True)
    return path / "tokens.json"


def _user_for_token(token: str) -> str | None:
    return _read_json(_tokens_path(), {}).get(token)


@router.get("/tradingview/webhook-url")
def get_webhook_url(request: Request, user: AuthUser = CurrentUser) -> dict:
    tokens = _read_json(_tokens_path(), {})
    existing = next((t for t, uid in tokens.items() if uid == user.id), None)
    token = existing or secrets.token_hex(16)
    if not existing:
        tokens[token] = user.id
        _write_json(_tokens_path(), tokens)
    # Northflank terminates TLS upstream, so request.url.scheme is "http"
    # internally even though the public URL is https — trust
    # X-Forwarded-Proto (set by the proxy) over the raw scheme.
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    base = str(request.base_url).rstrip("/").replace(f"{request.url.scheme}://", f"{scheme}://", 1)
    return {
        "url": f"{base}/api/v1/tradingview/signal/{token}",
        "example_message": json.dumps({"symbol": "{{ticker}}", "side": "buy"}),
    }


@router.post("/tradingview/signal/{token}")
async def receive_signal(token: str, request: Request) -> dict:
    user_id = _user_for_token(token)
    if not user_id:
        raise HTTPException(status_code=404, detail="unknown webhook token")

    raw = await request.body()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="expected JSON body, e.g. {\"symbol\": \"NVDA\", \"side\": \"buy\"}")

    symbol = str(payload.get("symbol", "")).upper().strip()
    side = str(payload.get("side", "")).lower().strip()
    if not symbol or side not in ("buy", "sell"):
        raise HTTPException(status_code=422, detail="payload needs symbol and side ('buy'/'sell')")

    if _emergency_stop_active(user_id):
        return {"accepted": True, "acted": False, "reason": "emergency stop is active for this account"}

    # DECISION ENGINE — the alert alone is never sufficient
    try:
        decision = get_decision(symbol=symbol, nonce=0, user=AuthUser(id=user_id, email=None))
    except HTTPException as exc:
        return {"accepted": True, "acted": False, "reason": f"no data for {symbol}: {exc.detail}"}

    wanted_action = "BUY_NOW" if side == "buy" else "SELL_NOW"
    if decision["action"] != wanted_action:
        return {
            "accepted": True,
            "acted": False,
            "reason": f"EdgeLab's current read on {symbol} is {decision['action']}, not {wanted_action} — signal not acted on",
        }

    # RISK ENGINE — same cooldown / open-position rules as the background scanner
    if symbol in _open_position_symbols():
        return {"accepted": True, "acted": False, "reason": f"already holding a position in {symbol}"}

    state = _read_json(_state_path(user_id), {})
    last = state.get(symbol)
    now = datetime.now(UTC)
    if last and last.get("action") == wanted_action:
        last_at = datetime.fromisoformat(last["at"])
        if now - last_at < COOLDOWN:
            return {"accepted": True, "acted": False, "reason": "cooldown — acted on this signal recently"}

    # EXECUTION ENGINE — paper, unconditionally
    order = _place_paper_order(symbol, side, AUTO_TRADE_NOTIONAL_USD)
    if not order:
        return {"accepted": True, "acted": False, "reason": "order placement failed"}

    state[symbol] = {"action": wanted_action, "at": now.isoformat(), "order_id": order.get("id")}
    _write_json(_state_path(user_id), state)
    _notify_telegram(user_id, f"TradingView signal executed: {side} ~${AUTO_TRADE_NOTIONAL_USD:.0f} of {symbol} (paper)")

    return {"accepted": True, "acted": True, "order_id": order.get("id")}
