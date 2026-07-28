"""Bridges validation to the frozen Phase 2 run pipeline."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from engine.data.schema_types import AdjustmentMode, Timeframe
from engine.data.store import ParquetStore
from engine.execution.costs import SimpleCostModel
from engine.run import run_research_backtest
from engine.types import LotMethod


def make_store_runner(
    *,
    store: ParquetStore,
    strategy_factory,                       # () -> SDKStrategy (fresh state per run)
    symbols: list[str],
    timeframe: Timeframe,
    cost_model: SimpleCostModel,
    adjustment_mode: AdjustmentMode = AdjustmentMode.RAW,
    initial_cash: float = 100_000.0,
    margin_multiplier: float = 1.0,
    lot_method: LotMethod = LotMethod.FIFO,
    max_participation: float | None = 0.1,
    slippage_mult: float = 1.0,
    commission_mult: float = 1.0,
):
    """Returns runner(params, start, end) -> BacktestResult. A FRESH
    strategy instance is built per call — walk-forward folds must never
    share indicator state. Cost multipliers support Monte Carlo
    perturbation without touching frozen code."""
    if slippage_mult != 1.0 or commission_mult != 1.0:
        cost_model = replace(
            cost_model,
            slippage_bps=cost_model.slippage_bps * slippage_mult,
            spread_bps=cost_model.spread_bps * slippage_mult,
            commission_per_share=cost_model.commission_per_share * commission_mult,
            min_commission=cost_model.min_commission * commission_mult,
        )

    def runner(params: dict, start: datetime, end: datetime):
        return run_research_backtest(
            store=store,
            strategy=strategy_factory(),
            symbols=symbols,
            timeframe=timeframe,
            start=start,
            end=end,
            params=params,
            cost_model=cost_model,
            adjustment_mode=adjustment_mode,
            initial_cash=initial_cash,
            margin_multiplier=margin_multiplier,
            lot_method=lot_method,
            max_participation=max_participation,
        )

    return runner
