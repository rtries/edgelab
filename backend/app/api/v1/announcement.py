"""A single shared announcement banner for testers — static content,
edited by hand in this file and redeployed, not a CMS. `id` changes
whenever the content changes; the frontend uses it to decide whether a
tester has already dismissed the current one (stored in their own
localStorage, nothing server-side to track per-user).
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

CURRENT = {
    "id": "2026-08-14-tradingview-pivot",
    "date": "2026-08-14",
    "title": "What changed: EdgeLab is now TradingView-first",
    "changed": [
        "Navigation simplified to Home / Agent / Trades / Account — everything else "
        "(Scanner, Markets, backtesting, Monte Carlo, etc.) moved under Research Lab. "
        "Nothing was deleted, it's just not in your way anymore.",
        "New Agent page: one screen for 'what is the bot doing' — start/stop, "
        "today's P/L, current watchlist reads, open positions, and a full activity log "
        "of every signal received/rejected/executed.",
        "TradingView webhook integration: connect an alert to EdgeLab from the "
        "Connections page. A signal is never automatically an order — it goes through "
        "the same validation, risk, and execution pipeline as everything else.",
        "Safety fix: automated orders (both the background scanner and TradingView "
        "signals) now check buying power before firing. They didn't before tonight, "
        "and the shared paper account had gone negative as a result.",
    ],
    "needs_attention": [
        "The shared paper trading account was reset after the buying-power bug above — "
        "if your positions/history look emptier than expected, that's why, not a bug.",
        "The AI setup scoring (confidence %, entry zone, stop, target) is still "
        "placeholder logic — marked with a 'Preview Analysis' badge everywhere it "
        "appears. It does not yet reflect the real backtesting engine.",
        "No strategy has earned 'strong' confidence through real backtesting yet, so "
        "there is still no path to live (real-money) trading — everything is paper.",
        "TradingView integration is new and lightly tested — please report anything "
        "confusing or broken with the feedback button.",
    ],
    "goal": (
        "Make EdgeLab the thing that watches your TradingView setups, validates them "
        "against real evidence, manages risk, and handles the boring execution/paper-"
        "tracking work — without needing you to learn another charting platform or a "
        "quant research tool. TradingView stays your workspace; EdgeLab works in the "
        "background."
    ),
}


@router.get("/announcement")
def get_announcement() -> dict:
    return CURRENT
