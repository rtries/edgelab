"""Telegram bot — check agent status and flip auto-trade on/off from
chat. Uses Telegram's official Bot API (webhook), not any unsupported
access — see the module-level safety notes below before touching the
auto-trade gate.

SAFETY: the /on and /off commands here ONLY ever toggle a per-user
"auto_trade" flag consulted by paper-trading logic. They cannot, and
must never be made to, flip a deployment to live status or bypass
ops/deployments.py's transition() gate or the server-wide ALPACA_PAPER
switch in ops.py's Alpaca run endpoint. Going live stays a deliberate,
explicit action inside the app — never a chat command. If live-via-
Telegram is wanted later, that is a new, separate, carefully-scoped
decision, not an extension of this file.

Linking: a signed-in user requests a short-lived link code from the
app (GET /telegram/link-code), then sends "/link CODE" to the bot.
That ties their Telegram chat_id to their EdgeLab user_id. Everything
else (status/on/off/scan) requires the chat to already be linked.

Auto-trading itself (a background process that watches setups and
acts without anyone's browser open) is NOT implemented by this file —
this only handles the chat interface and the flag. The flag currently
has no consumer; wiring a scheduler to actually check it and place
paper trades unattended is separate, larger, follow-up work.
"""
from __future__ import annotations

import json
import os
import secrets
import string
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.v1.decision import get_decision
from app.core.auth import AuthUser, get_current_user
from app.core.config import settings

router = APIRouter()

CurrentUser = Depends(get_current_user)

WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA", "SPY", "AMZN", "GOOGL", "META"]
LINK_CODE_TTL = timedelta(minutes=15)
TELEGRAM_API = "https://api.telegram.org"


def _shared_root() -> Path:
    base = Path(os.environ.get("EDGELAB_OPS_ROOT", "ops_data"))
    path = base / "_telegram"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _link_codes_path() -> Path:
    return _shared_root() / "link_codes.json"


def _chat_links_path() -> Path:
    return _shared_root() / "chat_links.json"


def _agent_config_path(user_id: str) -> Path:
    base = Path(os.environ.get("EDGELAB_OPS_ROOT", "ops_data")) / user_id
    base.mkdir(parents=True, exist_ok=True)
    return base / "agent_config.json"


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=1))


def _user_id_for_chat(chat_id: int) -> str | None:
    return _read_json(_chat_links_path(), {}).get(str(chat_id))


def _agent_config(user_id: str) -> dict:
    return _read_json(_agent_config_path(user_id), {"auto_trade": False})


def _send_message(chat_id: int, text: str) -> None:
    if not settings.telegram_bot_token:
        return
    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            resp.read()
    except urllib.error.URLError:
        pass  # best-effort — a failed reply shouldn't crash the webhook


# ── linking ──────────────────────────────────────────────────────────
@router.get("/telegram/link-code")
def get_link_code(user: AuthUser = CurrentUser) -> dict:
    codes = _read_json(_link_codes_path(), {})
    # prune expired codes
    now = datetime.now(UTC)
    codes = {
        c: v
        for c, v in codes.items()
        if datetime.fromisoformat(v["expires_at"]) > now
    }
    code = "".join(secrets.choice(string.digits) for _ in range(6))
    codes[code] = {"user_id": user.id, "expires_at": (now + LINK_CODE_TTL).isoformat()}
    _write_json(_link_codes_path(), codes)
    return {"code": code, "expires_in_minutes": int(LINK_CODE_TTL.total_seconds() // 60)}


@router.get("/telegram/status")
def telegram_status(user: AuthUser = CurrentUser) -> dict:
    links = _read_json(_chat_links_path(), {})
    linked = any(v == user.id for v in links.values())
    return {"linked": linked, "auto_trade": _agent_config(user.id).get("auto_trade", False)}


# ── webhook ──────────────────────────────────────────────────────────
@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    if not settings.telegram_webhook_secret or x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=401, detail="bad or missing webhook secret")

    update = await request.json()
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if not chat_id or not text:
        return {"ok": True}

    _handle_command(chat_id, text)
    return {"ok": True}


def _handle_command(chat_id: int, text: str) -> None:
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/start" or cmd == "/help":
        _send_message(
            chat_id,
            "EdgeLab agent bot.\n\n"
            "/link CODE — connect this chat to your EdgeLab account (get a code from Connections in the app)\n"
            "/status — agent status\n"
            "/on — enable paper auto-trade\n"
            "/off — disable paper auto-trade\n"
            "/scan — check current setups\n\n"
            "Paper trading only. This bot can never place a real-money order.",
        )
        return

    if cmd == "/link":
        codes = _read_json(_link_codes_path(), {})
        entry = codes.get(arg)
        if not entry or datetime.fromisoformat(entry["expires_at"]) < datetime.now(UTC):
            _send_message(chat_id, "That code is invalid or expired — get a fresh one from Connections in the app.")
            return
        links = _read_json(_chat_links_path(), {})
        links[str(chat_id)] = entry["user_id"]
        _write_json(_chat_links_path(), links)
        del codes[arg]
        _write_json(_link_codes_path(), codes)
        _send_message(chat_id, "Linked. Try /status.")
        return

    user_id = _user_id_for_chat(chat_id)
    if not user_id:
        _send_message(chat_id, "This chat isn't linked yet. Get a code from Connections in the app, then send /link CODE.")
        return

    if cmd == "/status":
        cfg = _agent_config(user_id)
        state = "ON (paper)" if cfg.get("auto_trade") else "OFF"
        _send_message(chat_id, f"Auto-trade: {state}\nMode: paper only — no live-money path exists via chat.")
        return

    if cmd in ("/on", "/off"):
        cfg = _agent_config(user_id)
        cfg["auto_trade"] = cmd == "/on"
        _write_json(_agent_config_path(user_id), cfg)
        _send_message(
            chat_id,
            f"Paper auto-trade {'enabled' if cfg['auto_trade'] else 'disabled'}.\n"
            + ("Note: unattended background execution isn't wired up yet — this flag is ready, "
               "the scheduler that acts on it is next." if cfg["auto_trade"] else ""),
        )
        return

    if cmd == "/scan":
        fake_user = AuthUser(id=user_id, email=None)
        lines = []
        for symbol in WATCHLIST:
            try:
                d = get_decision(symbol=symbol, nonce=0, user=fake_user)
            except HTTPException:
                continue
            if d["action"] != "NO_TRADE":
                lines.append(f"{symbol}: {d['action']} — {d['why'][:100]}")
        _send_message(chat_id, "\n\n".join(lines) if lines else "Nothing actionable right now.")
        return

    _send_message(chat_id, "Unrecognized command. Send /help.")
