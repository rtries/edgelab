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
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.v1.decision import get_decision
from app.core.auth import AuthUser, get_current_user
from ops.auto_trader import (
    AUTO_TRADE_NOTIONAL_USD,
    COOLDOWN,
    _buying_power,
    _emergency_stop_active,
    _notify_telegram,
    _open_position_symbols,
    _ops_root,
    _place_paper_order,
    _read_json,
    _state_path,
    _write_json,
    is_auto_trade_enabled,
    log_event,
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


SIGNAL_MAX_AGE = timedelta(minutes=5)  # stale-signal rejection (spec section 13/26)


def _seen_signals_path(user_id: str) -> Path:
    return _ops_root() / user_id / "tradingview_seen_signals.json"


def _reject(user_id: str, symbol: str | None, reason: str) -> dict:
    log_event(user_id, "rejected", reason, {"symbol": symbol, "source": "tradingview"})
    return {"accepted": True, "acted": False, "reason": reason}


@router.post("/tradingview/signal/{token}")
async def receive_signal(token: str, request: Request) -> dict:
    user_id = _user_for_token(token)
    if not user_id:
        # No user to attribute this to — can't log against an account, just refuse.
        raise HTTPException(status_code=404, detail="unknown webhook token")

    raw = await request.body()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="expected JSON body, e.g. {\"symbol\": \"NVDA\", \"side\": \"buy\"}")

    symbol = str(payload.get("symbol", "")).upper().strip()
    side = str(payload.get("side", "")).lower().strip()
    signal_id = payload.get("signal_id")
    signal_ts = payload.get("timestamp")

    log_event(user_id, "signal_received", f"{side} {symbol}".strip(), {"symbol": symbol, "side": side, "raw": payload})

    if not symbol or side not in ("buy", "sell"):
        raise HTTPException(status_code=422, detail="payload needs symbol and side ('buy'/'sell')")

    # Idempotency — a duplicated/retried webhook delivery must not double-trade.
    if signal_id:
        seen = _read_json(_seen_signals_path(user_id), {})
        if signal_id in seen:
            return _reject(user_id, symbol, f"duplicate signal_id {signal_id} — already processed")
        seen[signal_id] = datetime.now(UTC).isoformat()
        # bound the file — keep the most recent 500 ids
        if len(seen) > 500:
            seen = dict(sorted(seen.items(), key=lambda kv: kv[1])[-500:])
        _write_json(_seen_signals_path(user_id), seen)

    # Freshness — an alert that took too long to arrive is stale, act on nothing.
    if signal_ts:
        try:
            sent_at = datetime.fromisoformat(str(signal_ts).replace("Z", "+00:00"))
            if datetime.now(UTC) - sent_at > SIGNAL_MAX_AGE:
                return _reject(user_id, symbol, f"stale signal — timestamp {signal_ts} is older than {SIGNAL_MAX_AGE}")
        except ValueError:
            pass  # unparseable timestamp isn't grounds to reject; just skip the freshness check

    if _emergency_stop_active(user_id):
        return _reject(user_id, symbol, "emergency stop is active for this account")

    if not is_auto_trade_enabled(user_id):
        return _reject(user_id, symbol, "agent is not enabled for this account — signal received but not acted on")

    # DECISION ENGINE — the alert alone is never sufficient
    try:
        decision = get_decision(symbol=symbol, nonce=0, user=AuthUser(id=user_id, email=None))
    except HTTPException as exc:
        return _reject(user_id, symbol, f"no data for {symbol}: {exc.detail}")

    wanted_action = "BUY_NOW" if side == "buy" else "SELL_NOW"
    if decision["action"] != wanted_action:
        return _reject(
            user_id, symbol,
            f"EdgeLab's current read on {symbol} is {decision['action']}, not {wanted_action} — signal not acted on",
        )

    # RISK ENGINE — same cooldown / open-position / buying-power rules as the background scanner
    if symbol in _open_position_symbols():
        return _reject(user_id, symbol, f"already holding a position in {symbol}")

    if side == "buy":
        bp = _buying_power()
        if bp is None:
            return _reject(user_id, symbol, "couldn't verify buying power")
        if bp < AUTO_TRADE_NOTIONAL_USD:
            return _reject(user_id, symbol, f"insufficient buying power: ${bp:.2f} available, ${AUTO_TRADE_NOTIONAL_USD:.0f} needed")

    state = _read_json(_state_path(user_id), {})
    last = state.get(symbol)
    now = datetime.now(UTC)
    if last and last.get("action") == wanted_action:
        last_at = datetime.fromisoformat(last["at"])
        if now - last_at < COOLDOWN:
            return _reject(user_id, symbol, "cooldown — acted on this signal recently")

    # EXECUTION ENGINE — paper, unconditionally
    order = _place_paper_order(symbol, side, AUTO_TRADE_NOTIONAL_USD)
    if not order:
        return _reject(user_id, symbol, "order placement failed")

    state[symbol] = {"action": wanted_action, "at": now.isoformat(), "order_id": order.get("id")}
    _write_json(_state_path(user_id), state)
    log_event(
        user_id, "executed", f"{side} ~${AUTO_TRADE_NOTIONAL_USD:.0f} of {symbol} (paper) — TradingView signal",
        {"symbol": symbol, "side": side, "order_id": order.get("id"), "source": "tradingview"},
    )
    _notify_telegram(user_id, f"TradingView signal executed: {side} ~${AUTO_TRADE_NOTIONAL_USD:.0f} of {symbol} (paper)")
    return {"accepted": True, "acted": True, "order_id": order.get("id")}

    return {"accepted": True, "acted": True, "order_id": order.get("id")}
