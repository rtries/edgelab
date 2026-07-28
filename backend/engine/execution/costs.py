"""Execution cost model.

Semantics:
- AGGRESSIVE executions (market orders, triggered stops) cross the spread
  and eat slippage: price is adjusted against the trader by
  (slippage_bps + spread_bps / 2).
- PASSIVE executions (resting limit orders) are assumed to trade at the
  limit (or better on favorable gaps) with no slippage/spread penalty —
  the penalty for passivity is modeled by fills simply not happening
  unless price trades through the limit.
- Commission applies to every fill, including each partial fill
  (min_commission per execution, as real brokers charge).

Defaults are conservative on purpose. Validation phases stress-test
multiples of these; an edge that dies at 2x costs is not an edge.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.types import Side


@dataclass(frozen=True, slots=True)
class SimpleCostModel:
    commission_per_share: float = 0.005
    min_commission: float = 1.0
    slippage_bps: float = 1.0
    spread_bps: float = 0.5

    @property
    def _adverse_frac(self) -> float:
        return (self.slippage_bps + self.spread_bps / 2.0) / 10_000.0

    def aggressive_price(self, raw_price: float, side: Side) -> float:
        adj = 1.0 + self._adverse_frac if side is Side.BUY else 1.0 - self._adverse_frac
        return raw_price * adj

    def passive_price(self, raw_price: float, side: Side) -> float:
        return raw_price

    def commission(self, qty: float) -> float:
        return max(self.min_commission, abs(qty) * self.commission_per_share)


@dataclass(frozen=True, slots=True)
class ZeroCostModel:
    """Frictionless execution — for isolating accounting logic in tests only.
    Never use in research: costless backtests are how people fool themselves."""

    def aggressive_price(self, raw_price: float, side: Side) -> float:
        return raw_price

    def passive_price(self, raw_price: float, side: Side) -> float:
        return raw_price

    def commission(self, qty: float) -> float:
        return 0.0
