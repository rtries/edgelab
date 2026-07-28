"""Pattern library — every executed setup, snapshotted with its market
context and, once the position closes, its outcome.

This is a HISTORICAL DATABASE, not a signal source. Records answer "what
did the market look like when this deployment traded, and what
happened?" — they never answer "what will happen".

Feature notes (honesty over completeness):
  breadth      requires a tracked universe; on daily single-symbol data
               it is recorded as None (Phase 6: universe service)
  vwap_rel     true VWAP requires intraday data; on daily bars we record
               the close's position inside the bar's high-low range
               (close_range_pct) and keep vwap_rel None
Everything recorded is defined and computable from the data actually
present — no proxies dressed up as the real thing.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from engine.types import Fill
from engine.validation.regimes import RegimeConfig, classify

from ops.deployments import Deployment
from ops.execution import Ledger
from ops.risk import MarketState, SignalCandidate


@dataclass(slots=True)
class PatternRecord:
    id: str
    deployment_id: str
    strategy: str
    symbol: str
    side: str
    ts: str
    order_id: int
    features: dict
    outcome: dict | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "deployment_id": self.deployment_id,
            "strategy": self.strategy, "symbol": self.symbol,
            "side": self.side, "ts": self.ts, "order_id": self.order_id,
            "features": self.features, "outcome": self.outcome,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PatternRecord":
        return cls(**d)


NUMERIC_FEATURES = [
    "atr_pct", "trailing_vol", "gap_pct", "rvol", "close_range_pct",
    "spread_bps", "dollar_volume",
]


def extract_features_from_frame(
    frame: pd.DataFrame,
    quote: dict | None = None,
    dollar_volume: float | None = None,
    sector: str = "unknown",
) -> dict:
    """Market-context snapshot from a canonical bar frame (last row =
    current bar). Pure and unit-testable."""
    n = len(frame)
    closes = frame["close"].astype(float)
    row = frame.iloc[-1]
    features: dict = {
        "sector": sector,
        "time_of_day": int(pd.Timestamp(row["ts"]).hour),
        "spread_bps": (quote or {}).get("spread_bps"),
        "dollar_volume": dollar_volume,
        "breadth": None,        # requires a universe — see module note
        "vwap_rel": None,       # requires intraday data — see module note
    }
    # regimes (Phase 3 classifier on trailing closes)
    if n >= 25:
        table = classify(closes, RegimeConfig())
        features["vol_regime"] = str(table["vol_regime"].iloc[-1])
        features["trend_regime"] = str(table["trend_regime"].iloc[-1])
    else:
        features["vol_regime"] = features["trend_regime"] = None
    # ATR% (14)
    if n >= 15:
        high, low = frame["high"].astype(float), frame["low"].astype(float)
        prev_close = closes.shift(1)
        tr = pd.concat([
            high - low, (high - prev_close).abs(), (low - prev_close).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        features["atr_pct"] = float(atr / closes.iloc[-1])
    else:
        features["atr_pct"] = None
    # trailing vol (20-bar, annualized)
    if n >= 21:
        returns = closes.pct_change().dropna().iloc[-20:]
        features["trailing_vol"] = float(returns.std(ddof=1) * np.sqrt(252))
    else:
        features["trailing_vol"] = None
    # gap vs previous close
    if n >= 2:
        features["gap_pct"] = float(
            row["open"] / closes.iloc[-2] - 1.0
        )
    else:
        features["gap_pct"] = None
    # relative volume vs 20-bar average
    if n >= 21:
        avg_vol = float(frame["volume"].iloc[-21:-1].mean())
        features["rvol"] = float(row["volume"] / avg_vol) if avg_vol > 0 else None
    else:
        features["rvol"] = None
    # close position within the bar range (daily-data stand-in, named as such)
    bar_range = float(row["high"] - row["low"])
    features["close_range_pct"] = (
        float((row["close"] - row["low"]) / bar_range) if bar_range > 0 else None
    )
    return features


class PatternRecorder:
    """Wired into the live loop: extract_features per candidate,
    on_signal per accepted order, on_fill to resolve outcomes when round
    trips close."""

    def __init__(self, store: "PatternStore",
                 sector_map: dict[str, str] | None = None) -> None:
        self.store = store
        self.sector_map = sector_map or {}
        self._unresolved: list[PatternRecord] = []
        self._seen_round_trips: int = 0

    def extract_features(self, symbol: str, runtime, state: MarketState) -> dict:
        frame = pd.DataFrame(runtime._bars[symbol])  # noqa: SLF001
        return extract_features_from_frame(
            frame,
            quote=state.last_quote.get(symbol),
            dollar_volume=state.last_dollar_volume.get(symbol),
            sector=self.sector_map.get(symbol, "unknown"),
        )

    def on_signal(self, dep: Deployment, candidate: SignalCandidate,
                  order_id: int) -> PatternRecord:
        record = PatternRecord(
            id=uuid.uuid4().hex[:12],
            deployment_id=dep.id,
            strategy=dep.strategy,
            symbol=candidate.symbol,
            side=candidate.side.value,
            ts=candidate.ts.isoformat(),
            order_id=order_id,
            features=dict(candidate.features),
        )
        self._unresolved.append(record)
        self.store.save(record)
        return record

    def on_fill(self, dep: Deployment, fill: Fill, ledger: Ledger) -> None:
        """Resolve outcomes for each round trip that closed since the
        last call: the oldest unresolved record for that symbol gets the
        trip's result."""
        new_trips = ledger.round_trips[self._seen_round_trips:]
        for trip in new_trips:
            for record in self._unresolved:
                if record.symbol == trip.symbol and record.outcome is None:
                    record.outcome = {
                        "net_pnl": trip.net_pnl,
                        "gross_pnl": trip.gross_pnl,
                        "win": trip.net_pnl > 0,
                        "holding_bars": max(
                            (trip.exit_ts - trip.entry_ts).days, 1),
                        "direction": "long" if trip.direction > 0 else "short",
                    }
                    self.store.save(record)
                    break
        self._unresolved = [r for r in self._unresolved if r.outcome is None]
        self._seen_round_trips = len(ledger.round_trips)


class PatternStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        (self.root / "patterns").mkdir(parents=True, exist_ok=True)

    def save(self, record: PatternRecord) -> None:
        (self.root / "patterns" / f"{record.id}.json").write_text(
            json.dumps(record.to_dict())
        )

    def all(self) -> list[PatternRecord]:
        records = [
            PatternRecord.from_dict(json.loads(p.read_text()))
            for p in sorted((self.root / "patterns").glob("*.json"))
        ]
        records.sort(key=lambda r: r.ts)
        return records

    def search(
        self,
        strategy: str | None = None,
        symbol: str | None = None,
        vol_regime: str | None = None,
        trend_regime: str | None = None,
        outcome: str | None = None,     # "win" | "loss" | "open"
    ) -> list[PatternRecord]:
        out = []
        for r in self.all():
            if strategy and r.strategy != strategy:
                continue
            if symbol and r.symbol != symbol:
                continue
            if vol_regime and r.features.get("vol_regime") != vol_regime:
                continue
            if trend_regime and r.features.get("trend_regime") != trend_regime:
                continue
            if outcome == "open" and r.outcome is not None:
                continue
            if outcome == "win" and not (r.outcome or {}).get("win"):
                continue
            if outcome == "loss" and (
                r.outcome is None or r.outcome.get("win")
            ):
                continue
            out.append(r)
        return out
