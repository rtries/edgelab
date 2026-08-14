"""Agent status/control — the single endpoint that powers Home and
Agent pages. Aggregates state that already exists across auto_trader,
market (paper account/positions), decision, and the emergency-stop
flag rather than introducing a new source of truth for any of it.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.decision import get_decision
from app.api.v1.market import get_paper_account, list_paper_positions
from app.api.v1.ops import emergency_stop_active
from app.core.auth import AuthUser, get_current_user
from ops.auto_trader import (
    AUTO_TRADE_NOTIONAL_USD,
    WATCHLIST,
    is_auto_trade_enabled,
    read_activity,
    set_auto_trade,
)

router = APIRouter()

CurrentUser = Depends(get_current_user)


@router.get("/agent/status")
def agent_status(user: AuthUser = CurrentUser) -> dict:
    account = get_paper_account(user)
    positions = list_paper_positions(user)
    watched = [s for s in WATCHLIST if s not in {p["symbol"] for p in positions}][:6]
    watchlist_decisions = []
    for symbol in watched:
        try:
            d = get_decision(symbol=symbol, nonce=0, user=user)
            watchlist_decisions.append(
                {"symbol": symbol, "action": d["action"], "why": d["reasons"][0] if d["reasons"] else d["why"]}
            )
        except Exception:  # noqa: BLE001 — one bad symbol shouldn't break the whole status call
            continue

    return {
        "enabled": is_auto_trade_enabled(user.id),
        "emergency_stop_active": emergency_stop_active(user.id),
        "allocation_per_trade_usd": AUTO_TRADE_NOTIONAL_USD,
        "account": account,
        "positions": positions,
        "watchlist": watchlist_decisions,
    }


@router.get("/agent/activity")
def agent_activity(limit: int = 50, user: AuthUser = CurrentUser) -> list[dict]:
    return read_activity(user.id, limit)


@router.post("/agent/enable")
def enable_agent(user: AuthUser = CurrentUser) -> dict:
    set_auto_trade(user.id, True)
    return {"enabled": True}


@router.post("/agent/disable")
def disable_agent(user: AuthUser = CurrentUser) -> dict:
    set_auto_trade(user.id, False)
    return {"enabled": False}
