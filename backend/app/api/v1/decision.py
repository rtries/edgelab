"""Decision Engine — ONE typed contract for "should I care about this
stock right now," reused by every consumer (Scanner, Stock page, Session,
Morning Brief) instead of each page re-deriving its own recommendation.

STILL PLACEHOLDER. The confidence/bias/zones/reasons below are the same
deterministic mock logic that used to live only in the frontend
(lib/mock-setup.ts), moved server-side and reshaped into the guided
decision contract from the product spec:

    interesting today? -> why -> action -> entry/stop/target -> evidence

Price and day-range data are real (Alpaca, via market.get_bars). The
decision logic — confidence, bias, zones, reasons — is NOT; every
response carries evidence.is_placeholder=true, and callers must keep
showing a Preview Analysis badge next to anything rendered from here.
When the real research/confidence engine is wired in, this module is
where that swap happens — the response shape doesn't have to change for
every caller to benefit.

SETUP QUALITY != ENTRY TIMING: `confidence` answers "is this a good
setup"; `action` answers "should I act right now". A 90%-confidence
setup can still say WAIT if price has run past the entry zone.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.market import get_bars
from app.core.auth import AuthUser, get_current_user

router = APIRouter()

CurrentUser = Depends(get_current_user)


def _seed(symbol: str, nonce: int) -> int:
    h = 0
    for ch in symbol:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return (h ^ nonce) & 0xFFFFFFFF


def _mulberry32(seed: int):
    """Same generator as the frontend's mulberry32 — deterministic per
    (symbol, nonce) so a decision doesn't jitter on every request, only
    when the caller explicitly asks for a fresh read via `nonce`."""
    state = {"a": seed}

    def rng() -> float:
        state["a"] = (state["a"] + 0x6D2B79F5) & 0xFFFFFFFF
        t = state["a"]
        t = (t ^ (t >> 15)) * (t | 1) & 0xFFFFFFFF
        t = (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) ^ t
        t &= 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    return rng


@router.get("/decision/{symbol}")
def get_decision(symbol: str, nonce: int = Query(0), user: AuthUser = CurrentUser) -> dict:
    symbol = symbol.upper()
    bars = get_bars(symbol=symbol, timeframe="1Day", limit=120, user=user)
    if not bars:
        raise HTTPException(status_code=404, detail=f"no data for {symbol}")
    last_bar = bars[-1]
    last = last_bar.c

    rng = _mulberry32(_seed(symbol, nonce))
    confidence = 0.35 + rng() * 0.6
    if confidence >= 0.75:
        level = "strong"
    elif confidence >= 0.55:
        level = "moderate"
    elif confidence >= 0.4:
        level = "weak"
    else:
        level = "insufficient"
    bias = "long" if rng() > 0.3 else "short"

    zone_width = last * 0.015
    if bias == "long":
        entry_lo, entry_hi = last - zone_width, last - zone_width * 0.2
        stop = entry_lo * 0.97
        risk = abs(entry_lo - stop)
        target = entry_hi + risk * 2.2
    else:
        entry_lo, entry_hi = last + zone_width * 0.2, last + zone_width
        stop = entry_hi * 1.03
        risk = abs(entry_hi - stop)
        target = entry_lo - risk * 2.2

    entry_mid = (entry_lo + entry_hi) / 2
    reward = abs(target - entry_mid)
    risk_reward = 0.0 if risk == 0 else reward / risk

    if level in ("weak", "insufficient"):
        action = "NO_TRADE"
        interesting = "NO" if level == "insufficient" else "MAYBE"
        why = (
            "Evidence does not currently meet EdgeLab's validation threshold for this setup."
            if level == "insufficient"
            else "The setup shows some signal but validation is weak — not enough to act on yet."
        )
    elif entry_lo <= last <= entry_hi:
        action = "BUY_NOW" if bias == "long" else "SELL_NOW"
        interesting = "YES"
        why = (
            f"Price has entered the preferred {'entry' if bias == 'long' else 'short'} zone while the setup "
            f"remains valid. Current stop and target imply approximately 1:{risk_reward:.1f} risk/reward."
        )
    elif (bias == "long" and last > entry_hi) or (bias == "short" and last < entry_lo):
        action = "WAIT"
        interesting = "YES"
        why = (
            f"{symbol} remains a {level} setup, but price is currently outside the preferred "
            f"${entry_lo:.2f}-${entry_hi:.2f} entry range. Entering here would reduce the original "
            "risk/reward. EdgeLab is waiting for a pullback into the entry area."
        )
    else:
        action = "WATCH"
        interesting = "MAYBE"
        why = f"{symbol} is approaching a validated zone but hasn't reached the preferred entry range yet."

    reasons = [
        f"Price is consolidating near its 20-period {'support' if bias == 'long' else 'resistance'} band, "
        "the kind of area this model weighs as a higher-probability entry.",
        f"Recent volatility is {'contracting' if rng() > 0.5 else 'elevated'}, which shapes how wide the "
        "suggested stop needs to be to avoid noise.",
        f"Momentum over the last 10 bars is {'turning up' if bias == 'long' else 'turning down'}, agreeing "
        "with the suggested direction — not a guarantee, one input among several.",
        "This is a probability read on historical pattern behavior, not a prediction. Position size for the "
        "stop distance, not the target.",
    ]
    risks = [
        "Confidence and historical pattern agreement are not guarantees of future performance.",
        "Sudden news or broad market moves can invalidate any setup instantly.",
        "This scoring is currently placeholder logic — see evidence.is_placeholder.",
    ]
    invalidation = [
        f"Setup invalidates if price closes back {'below' if bias == 'long' else 'above'} {stop:.2f}.",
    ]

    return {
        "symbol": symbol,
        "generated_at": datetime.now(UTC).isoformat(),
        "interesting_today": interesting,
        "action": action,
        "why": why,
        "confidence": confidence,
        "confidence_level": level,
        "bias": bias,
        "last_price": last,
        "day_range": [last_bar.l, last_bar.h],
        "entry_zone": [entry_lo, entry_hi],
        "stop": stop,
        "targets": [target],
        "risk_reward": risk_reward,
        "reasons": reasons,
        "risks": risks,
        "invalidation_conditions": invalidation,
        "evidence": {
            "is_placeholder": True,
            "note": "Confidence, bias, zones, and reasons are deterministic placeholder logic, not the real "
            "research engine. Price and day-range data are real (Alpaca).",
        },
    }
