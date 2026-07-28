"""Pre-trade risk limits (Phase 1 wires these into the backtester; the same
objects later guard paper and live routing — one risk path for all modes).

Planned checks: max daily loss halt, max position %, max gross exposure,
volatility-targeted sizing, correlation/sector caps, kill switch flag.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.types import Order, PortfolioState


@dataclass(slots=True)
class BasicRiskLimits:
    max_position_pct: float = 0.10      # of equity, per symbol
    max_gross_exposure: float = 1.0     # no leverage by default
    max_daily_loss_pct: float = 0.03    # halt trading for the day beyond this

    def filter_order(self, order: Order, portfolio: PortfolioState) -> Order | None:
        raise NotImplementedError
