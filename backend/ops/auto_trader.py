"""Unattended paper auto-trading loop — the piece that was explicitly
NOT built when the Telegram on/off flag landed (see app/api/v1/
telegram.py's docstring). This is what actually checks setups and acts
while nobody has the app open.

Runs as an in-process asyncio background task started from app.main's
lifespan — NOT a separate Celery worker. The repo's README lists
Celery+Redis in the intended stack, but that path (app/workers/) is
disconnected placeholder scaffolding against a Postgres model the real
file-based research/ops engine never touches; standing up a whole
worker+broker deployment for one polling loop was more new
infrastructure than the job needs. This reuses the running API
process, the real ops_data file store, and the existing Decision
Engine / kill-switch code directly.

SAFETY — every one of these is a hard requirement, not a suggestion:
  - PAPER ONLY. Always calls Alpaca's paper base URL, unconditionally,
    same as the manual Trading page and the Telegram bot. No branch of
    this file can reach live trading.
  - Respects the existing per-user emergency-stop kill switch
    (ops.emergency_stop_active) — skips any user with it set.
  - Consults each user's agent_config.json ("auto_trade": bool) — the
    same flag the Telegram /on and /off commands write. Users not
    opted in are never touched.
  - Cooldown + open-position check per (user, symbol) so a setup that
    stays BUY_NOW for hours doesn't fire a new order every scan cycle.
  - Fixed, conservative position size (AUTO_TRADE_NOTIONAL_USD) — no
    user-configurable sizing yet; that's future work, not a silent
    default to get wrong.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.api.v1.decision import get_decision
from app.api.v1.market import PAPER_TRADING_BASE_URL, _alpaca_headers
from app.core.auth import AuthUser
from app.core.config import settings

logger = logging.getLogger("edgelab.auto_trader")

WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA", "SPY", "AMZN", "GOOGL", "META"]
SCAN_INTERVAL_SECONDS = 300  # 5 min — see module docstring on why not tighter
COOLDOWN = timedelta(hours=1)
AUTO_TRADE_NOTIONAL_USD = 500.0


def _ops_root() -> Path:
    return Path(os.environ.get("EDGELAB_OPS_ROOT", "ops_data"))


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1))


def _users_with_auto_trade_on() -> list[str]:
    root = _ops_root()
    if not root.exists():
        return []
    out = []
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith("_"):
            continue
        cfg = _read_json(child / "agent_config.json", {})
        if cfg.get("auto_trade"):
            out.append(child.name)
    return out


def _emergency_stop_active(user_id: str) -> bool:
    return (_ops_root() / user_id / "emergency_stop.flag").exists()


def _state_path(user_id: str) -> Path:
    return _ops_root() / user_id / "auto_trade_state.json"


def _open_position_symbols() -> set[str]:
    """Shared paper account — same caveat as everywhere else this
    session: not per-EdgeLab-user, whoever's paper account the keys
    point at."""
    req = urllib.request.Request(
        f"{PAPER_TRADING_BASE_URL}/v2/positions", headers=_alpaca_headers(), method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            positions = json.loads(resp.read())
        return {p["symbol"] for p in positions}
    except (urllib.error.URLError, json.JSONDecodeError):
        return set()


def _place_paper_order(symbol: str, side: str, notional_usd: float) -> dict | None:
    body = json.dumps({"symbol": symbol, "notional": str(notional_usd), "side": side, "type": "market", "time_in_force": "day"}).encode()
    req = urllib.request.Request(
        f"{PAPER_TRADING_BASE_URL}/v2/orders", data=body, headers=_alpaca_headers(), method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        logger.warning("auto-trade order failed for %s: %s", symbol, exc.read().decode(errors="replace"))
        return None
    except urllib.error.URLError as exc:
        logger.warning("auto-trade order failed for %s: %s", symbol, exc)
        return None


def _notify_telegram(user_id: str, text: str) -> None:
    if not settings.telegram_bot_token:
        return
    links = _read_json(_ops_root() / "_telegram" / "chat_links.json", {})
    chat_id = next((cid for cid, uid in links.items() if uid == user_id), None)
    if not chat_id:
        return
    body = json.dumps({"chat_id": int(chat_id), "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            resp.read()
    except urllib.error.URLError:
        pass


def scan_user_once(user_id: str) -> None:
    if _emergency_stop_active(user_id):
        return
    state = _read_json(_state_path(user_id), {})
    open_symbols = _open_position_symbols()
    now = datetime.now(UTC)
    fake_user = AuthUser(id=user_id, email=None)
    changed = False

    for symbol in WATCHLIST:
        try:
            decision = get_decision(symbol=symbol, nonce=0, user=fake_user)
        except Exception:  # noqa: BLE001 — one bad symbol shouldn't kill the scan
            continue
        action = decision["action"]
        if action not in ("BUY_NOW", "SELL_NOW"):
            continue
        if symbol in open_symbols:
            continue  # already have a position — don't pile in

        last = state.get(symbol)
        if last and last.get("action") == action:
            last_at = datetime.fromisoformat(last["at"])
            if now - last_at < COOLDOWN:
                continue  # already acted on this same signal recently

        side = "buy" if action == "BUY_NOW" else "sell"
        order = _place_paper_order(symbol, side, AUTO_TRADE_NOTIONAL_USD)
        state[symbol] = {"action": action, "at": now.isoformat(), "order_id": order.get("id") if order else None}
        changed = True
        if order:
            _notify_telegram(
                user_id,
                f"Auto-trade: {side} ~${AUTO_TRADE_NOTIONAL_USD:.0f} of {symbol} (paper)\n{decision['why']}",
            )

    if changed:
        _write_json(_state_path(user_id), state)


def run_scan_once() -> None:
    for user_id in _users_with_auto_trade_on():
        try:
            scan_user_once(user_id)
        except Exception:  # noqa: BLE001 — one user's failure shouldn't stop the rest
            logger.exception("auto-trade scan failed for user %s", user_id)


async def auto_trade_loop() -> None:
    logger.info("auto-trade loop started (interval=%ss)", SCAN_INTERVAL_SECONDS)
    while True:
        try:
            run_scan_once()
        except Exception:  # noqa: BLE001 — the loop must never die
            logger.exception("auto-trade scan cycle failed")
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)
