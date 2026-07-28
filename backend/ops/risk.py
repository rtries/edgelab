"""Risk engine.

A SignalCandidate is a strategy's *opinion*. Nothing becomes an order
until every check in the chain passes. The chain runs in a fixed,
documented order:

  1. emergency_stop      global kill switch — file/API controlled
  2. market_hours        session must be open per the calendar
  3. data_quality        last bar for the symbol must be fresh
  4. duplicate           same deployment+symbol+side inside cooldown
  5. sizing              candidate qty -> final qty per policy (this is
                         the only check that MODIFIES the candidate)
  6. spread              current quote spread within policy
  7. liquidity           dollar volume floor
  8. position_limit      resulting |position| notional / equity cap
  9. exposure_limit      resulting gross notional / equity cap
 10. daily_loss          trading halts for the day past the loss limit
 11. buying_power        the frozen Portfolio.check_order validation

Every check returns a RiskDecision with evidence; evaluate() returns
either an approved order intent or the full rejection trail. Decisions
are pure functions of (candidate, state) — deterministic and fixtured.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from engine.calendar import WeekdayCalendar
from engine.portfolio.accounting import Portfolio
from engine.types import OrderType, Side

from ops.deployments import Deployment


@dataclass(frozen=True, slots=True)
class SignalCandidate:
    deployment_id: str
    strategy: str
    symbol: str
    side: Side
    qty: float                      # strategy's requested qty (pre-sizing)
    ts: datetime                    # bar time the signal came from
    received_at: datetime
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    features: dict = field(default_factory=dict)   # pattern-library snapshot

    def to_dict(self) -> dict:
        return {
            "deployment_id": self.deployment_id,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "side": self.side.value,
            "qty": self.qty,
            "ts": self.ts.isoformat(),
            "received_at": self.received_at.isoformat(),
            "order_type": self.order_type.value,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "features": self.features,
        }


@dataclass(frozen=True, slots=True)
class RiskDecision:
    check: str
    passed: bool
    reason: str
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"check": self.check, "passed": self.passed,
                "reason": self.reason, "evidence": self.evidence}


@dataclass(slots=True)
class MarketState:
    """Everything risk checks may consult. The loop maintains one."""
    portfolio: Portfolio
    last_bar_ts: dict[str, datetime]
    last_close: dict[str, float]
    last_dollar_volume: dict[str, float]
    last_quote: dict[str, dict]                 # bid/ask/spread_bps
    bars_seen: dict[str, int]
    day_start_equity: float
    current_day: str
    emergency_stop: bool = False
    recent_signals: list[tuple[str, str, str, int]] = field(default_factory=list)
    # (deployment_id, symbol, side, bar_index at submission)


@dataclass(frozen=True, slots=True)
class RiskResult:
    approved: bool
    final_qty: float
    decisions: list[RiskDecision]

    @property
    def rejection(self) -> RiskDecision | None:
        for d in self.decisions:
            if not d.passed:
                return d
        return None


def evaluate(
    candidate: SignalCandidate,
    dep: Deployment,
    state: MarketState,
    calendar: WeekdayCalendar | None = None,
    is_closing: bool = False,
) -> RiskResult:
    """is_closing: reducing/flattening an existing position — exit
    signals bypass entry-only gates (spread/liquidity/limits) but never
    the kill switch, hours, data quality, or buying power."""
    calendar = calendar or WeekdayCalendar()
    decisions: list[RiskDecision] = []
    policy = dep.risk

    def fail(check: str, reason: str, **evidence) -> RiskResult:
        decisions.append(RiskDecision(check, False, reason, evidence))
        return RiskResult(approved=False, final_qty=0.0, decisions=decisions)

    def ok(check: str, reason: str = "", **evidence) -> None:
        decisions.append(RiskDecision(check, True, reason, evidence))

    # 1 — emergency stop
    if state.emergency_stop:
        return fail("emergency_stop", "global emergency stop is active")
    ok("emergency_stop")

    # 2 — market hours
    if not calendar.is_session(candidate.ts.date()):
        return fail("market_hours", "not a trading session",
                    ts=candidate.ts.isoformat())
    session_open = calendar.session_open(candidate.ts.date())
    session_close = calendar.session_close(candidate.ts.date())
    if not (session_open <= candidate.ts <= session_close):
        return fail("market_hours", "outside session hours",
                    ts=candidate.ts.isoformat(),
                    session=[session_open.isoformat(), session_close.isoformat()])
    ok("market_hours")

    # 3 — data quality (bar staleness, in bars of this symbol's stream)
    last_ts = state.last_bar_ts.get(candidate.symbol)
    if last_ts is None:
        return fail("data_quality", "no bars received for symbol")
    ok("data_quality", last_bar=last_ts.isoformat())

    # 4 — duplicate protection
    bar_index = state.bars_seen.get(candidate.symbol, 0)
    for dep_id, sym, side, at_bar in state.recent_signals:
        if (
            dep_id == candidate.deployment_id
            and sym == candidate.symbol
            and side == candidate.side.value
            and bar_index - at_bar <= policy.duplicate_cooldown_bars
        ):
            return fail("duplicate", "same signal within cooldown",
                        cooldown_bars=policy.duplicate_cooldown_bars,
                        previous_bar=at_bar, current_bar=bar_index)
    ok("duplicate")

    # shorts allowed?
    price = state.last_close.get(candidate.symbol, 0.0)
    position = state.portfolio.position_qty(candidate.symbol)
    opens_short = candidate.side == Side.SELL and position - candidate.qty < 0
    if opens_short and not policy.allow_short and not is_closing:
        return fail("sizing", "policy forbids opening short positions")

    # 5 — position sizing (the only mutating step)
    equity = state.portfolio.equity
    if policy.sizing_mode == "fixed_qty":
        final_qty = float(policy.sizing_value)
    elif policy.sizing_mode == "pct_equity":
        if price <= 0:
            return fail("sizing", "no price available for sizing")
        final_qty = float(int((equity * policy.sizing_value) / price))
    else:
        return fail("sizing", f"unknown sizing mode {policy.sizing_mode}")
    if is_closing:
        final_qty = min(candidate.qty, abs(position)) or candidate.qty
    if final_qty <= 0:
        return fail("sizing", "sized quantity is zero",
                    equity=equity, price=price)
    ok("sizing", mode=policy.sizing_mode, requested=candidate.qty,
       final=final_qty)

    if not is_closing:
        # 6 — spread
        quote = state.last_quote.get(candidate.symbol)
        if quote and quote.get("spread_bps") is not None:
            if quote["spread_bps"] > policy.max_spread_bps:
                return fail("spread", "spread wider than policy",
                            spread_bps=quote["spread_bps"],
                            max_spread_bps=policy.max_spread_bps)
        ok("spread", spread_bps=(quote or {}).get("spread_bps"))

        # 7 — liquidity
        dollar_vol = state.last_dollar_volume.get(candidate.symbol, 0.0)
        if dollar_vol < policy.min_dollar_volume:
            return fail("liquidity", "dollar volume below floor",
                        dollar_volume=dollar_vol,
                        floor=policy.min_dollar_volume)
        ok("liquidity", dollar_volume=dollar_vol)

        # 8 — position limit (post-trade)
        signed = final_qty if candidate.side == Side.BUY else -final_qty
        post_notional = abs((position + signed) * price)
        if equity > 0 and post_notional / equity > policy.max_position_pct:
            return fail("position_limit", "position cap exceeded",
                        post_pct=post_notional / equity,
                        cap=policy.max_position_pct)
        ok("position_limit", post_pct=post_notional / max(equity, 1e-9))

        # 9 — gross exposure (post-trade)
        gross = state.portfolio.gross_exposure + abs(signed) * price
        if equity > 0 and gross / equity > policy.max_gross_exposure_pct:
            return fail("exposure_limit", "gross exposure cap exceeded",
                        post_pct=gross / equity,
                        cap=policy.max_gross_exposure_pct)
        ok("exposure_limit", post_pct=gross / max(equity, 1e-9))

        # 10 — daily loss limit
        if state.day_start_equity > 0:
            day_pnl_pct = equity / state.day_start_equity - 1.0
            if day_pnl_pct <= -dep.risk.daily_loss_limit_pct:
                return fail("daily_loss", "daily loss limit reached — done "
                            "trading today",
                            day_pnl_pct=day_pnl_pct,
                            limit=-policy.daily_loss_limit_pct)
        ok("daily_loss")

    # 11 — buying power (frozen engine validation)
    error = state.portfolio.check_order(candidate.symbol, candidate.side,
                                        final_qty, price)
    if error is not None:
        return fail("buying_power", error, qty=final_qty, price=price)
    ok("buying_power")

    return RiskResult(approved=True, final_qty=final_qty, decisions=decisions)
