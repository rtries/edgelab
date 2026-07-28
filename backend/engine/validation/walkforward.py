"""Walk-forward optimization over WindowSpec folds.

Per fold: every candidate parameter set is evaluated on the TRAIN range;
the best (by objective, tie-broken deterministically) is then evaluated
once on the VALIDATION range. Validation never influences selection
within the fold, and the final holdout (splits.reserve_final_test) never
enters this function at all.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from engine.validation.optimize import OptimizationResult, evaluate_param_sets
from engine.validation.splits import Fold, WindowSpec

AGG_METRICS = ["sharpe", "sortino", "max_drawdown", "profit_factor",
               "expectancy", "win_rate", "n_trades", "total_return"]


@dataclass(slots=True)
class FoldResult:
    fold: Fold
    best_params: dict
    train_metrics: dict
    val_metrics: dict
    optimization: OptimizationResult


@dataclass(slots=True)
class WalkForwardResult:
    objective: str
    folds: list[FoldResult]
    param_history: pd.DataFrame        # one row per fold: chosen params
    train_table: pd.DataFrame          # per-fold train metrics
    val_table: pd.DataFrame            # per-fold validation metrics
    aggregate: dict                    # summary stats over validation folds

    @property
    def n_folds(self) -> int:
        return len(self.folds)


def _aggregate(val_table: pd.DataFrame, objective: str) -> dict:
    out: dict = {"n_folds": int(len(val_table))}
    for metric in AGG_METRICS:
        if metric not in val_table.columns:
            continue
        col = val_table[metric].astype(float)
        out[f"{metric}_mean"] = float(col.mean())
        out[f"{metric}_median"] = float(col.median())
        out[f"{metric}_std"] = float(col.std(ddof=1)) if len(col) > 1 else 0.0
        out[f"{metric}_min"] = float(col.min())
    if objective in val_table.columns:
        col = val_table[objective].astype(float)
        out["fraction_positive_objective"] = float((col > 0).mean())
    return out


def walk_forward(
    runner: Callable[[dict, datetime, datetime], object],
    index: Sequence[datetime],
    window: WindowSpec,
    param_sets: Sequence[dict],
    objective: str = "sharpe",
) -> WalkForwardResult:
    folds = window.folds(index)
    fold_results: list[FoldResult] = []
    for fold in folds:
        opt = evaluate_param_sets(
            runner, param_sets, fold.train_start, fold.train_end,
            objective=objective,
        )
        train_row = opt.table.loc[
            opt.table["_params"].apply(lambda p: p == opt.best_params)
        ].iloc[0]
        train_metrics = {
            k: train_row[k] for k in train_row.index
            if not k.startswith(("p_", "_"))
        }
        val_result = runner(dict(opt.best_params), fold.val_start, fold.val_end)
        fold_results.append(
            FoldResult(
                fold=fold,
                best_params=opt.best_params,
                train_metrics=train_metrics,
                val_metrics=dict(val_result.metrics),
                optimization=opt,
            )
        )

    param_history = pd.DataFrame(
        [{"fold": fr.fold.index, **fr.best_params} for fr in fold_results]
    )
    train_table = pd.DataFrame(
        [{"fold": fr.fold.index, **fr.train_metrics} for fr in fold_results]
    )
    val_table = pd.DataFrame(
        [{"fold": fr.fold.index, **fr.val_metrics} for fr in fold_results]
    )
    return WalkForwardResult(
        objective=objective,
        folds=fold_results,
        param_history=param_history,
        train_table=train_table,
        val_table=val_table,
        aggregate=_aggregate(val_table, objective),
    )


def validation_consistency(result: WalkForwardResult) -> float:
    """Std of the per-fold validation objective — LOWER is more consistent.
    NaN with fewer than 2 folds."""
    if result.objective not in result.val_table.columns or len(result.val_table) < 2:
        return float("nan")
    return float(result.val_table[result.objective].astype(float).std(ddof=1))
