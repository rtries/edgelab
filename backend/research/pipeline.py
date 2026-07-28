"""Research pipeline: one call runs the complete Phase 3 validation suite
for a strategy on a dataset and returns a JSON-serializable Experiment.

This is the workspace's unit of record. Everything the terminal displays
comes out of this structure; nothing is computed ad hoc in the UI, so
what you see on screen is exactly what was measured, once, under a seed.

Pipeline (order matters — the holdout reserve happens FIRST):
  1. reserve_final_test() splits the tail holdout off the bar index.
  2. walk_forward() optimizes per fold on the working index only.
  3. "Selected params" = modal fold winner (most recent fold breaks
     ties): the deployment candidate walk-forward actually voted for.
  4. One development run over the working range with selected params
     produces the display equity curve / trades / exposure / monthly
     table. Labeled DEVELOPMENT: parameters were chosen using this data.
  5. Sensitivity grid over the working range (the Parameter Explorer).
  6. Monte Carlo: reshuffle/bootstrap/skip on development trades, a fan
     of seeded reshuffled equity paths (quantile bands, best/worst,
     probability-of-ruin table), cost-perturbation and execution-delay
     engine re-runs.
  7. Regime attribution against the first symbol's closes.
  8. Overfitting warnings incl. the persistent optimization registry.
  9. guard.evaluate() — the single permitted holdout evaluation, run
     with the selected params, stored under final_test. This number is
     the closest thing to "how it would have gone" the platform offers.
 10. build_report() -> confidence rubric + markdown, embedded whole.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from engine import __version__ as ENGINE_VERSION
from engine.data.schema_types import AdjustmentMode, Timeframe
from engine.data.store import ParquetStore
from engine.execution.costs import SimpleCostModel
from engine.run import strategy_code_hash
from engine.validation.montecarlo import (
    bootstrap_trades,
    confidence_intervals,
    delayed_execution_runs,
    perturbed_cost_runs,
    skip_trades,
    trade_reshuffle,
)
from engine.validation.optimize import evaluate_param_sets, grid_search_space
from engine.validation.overfitting import (
    OptimizationRegistry,
    check_complexity,
    check_few_trades,
    check_narrow_peak,
    check_surface_stability,
    check_train_val_divergence,
)
from engine.validation.regimes import RegimeConfig, classify, regime_metrics
from engine.validation.report import build_report, to_markdown
from engine.validation.runners import make_store_runner
from engine.validation.sensitivity import heatmap, summarize
from engine.validation.splits import WindowSpec, reserve_final_test
from engine.validation.walkforward import validation_consistency, walk_forward

RUIN_THRESHOLDS = (0.10, 0.20, 0.30, 0.50)


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _series_points(series: pd.Series, decimate_to: int = 1200) -> list[list]:
    if len(series) > decimate_to:
        idx = np.linspace(0, len(series) - 1, decimate_to).round().astype(int)
        series = series.iloc[np.unique(idx)]
    return [[ts.isoformat(), _json_safe(v)] for ts, v in series.items()]


def _drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1.0


def _monthly_returns(equity: pd.Series) -> list[dict]:
    monthly = equity.resample("ME").last().pct_change().dropna()
    # First month vs initial equity so the first period isn't lost.
    if len(equity):
        first_end = equity.resample("ME").last().iloc[0]
        first = first_end / equity.iloc[0] - 1.0
        rows = [{"year": int(equity.index[0].year), "month": int(equity.index[0].month),
                 "value": _json_safe(first)}]
    else:
        rows = []
    rows += [
        {"year": int(ts.year), "month": int(ts.month), "value": _json_safe(v)}
        for ts, v in monthly.items()
    ]
    return rows


def _trade_rows(trades: pd.DataFrame, cap: int = 2000) -> list[dict]:
    if len(trades) > cap:
        trades = trades.tail(cap)
    return [_json_safe(rec) for rec in trades.to_dict(orient="records")]


def _mc_fan(pnls: np.ndarray, initial: float, n_paths: int, seed: int,
            keep_sample: int = 40) -> dict:
    rng = np.random.default_rng(seed)
    steps = len(pnls) + 1
    matrix = np.empty((n_paths, steps))
    for i in range(n_paths):
        matrix[i] = initial + np.concatenate([[0.0], np.cumsum(rng.permutation(pnls))])
    q = {str(lv): np.quantile(matrix, lv, axis=0).tolist()
         for lv in (0.05, 0.25, 0.5, 0.75, 0.95)}
    end = matrix[:, -1]
    dd = (matrix / np.maximum.accumulate(matrix, axis=1) - 1.0).min(axis=1)
    worst_i, best_i = int(dd.argmin()), int(end.argmax())
    sample_idx = rng.choice(n_paths, size=min(keep_sample, n_paths), replace=False)
    return {
        "n_paths": n_paths,
        "steps": steps,
        "quantiles": q,
        "worst_path": matrix[worst_i].tolist(),
        "best_path": matrix[best_i].tolist(),
        "sample_paths": matrix[np.sort(sample_idx)].tolist(),
        "prob_ruin": {
            str(t): _json_safe(float((dd <= -t).mean())) for t in RUIN_THRESHOLDS
        },
    }


def run_experiment(
    *,
    data_store: ParquetStore,
    strategy_cls,
    symbols: list[str],
    timeframe: Timeframe = Timeframe.D1,
    param_values: dict[str, list] | None = None,
    objective: str = "sharpe",
    train_size: int = 60,
    val_size: int = 20,
    test_size: int = 25,
    expanding: bool = False,
    mc_iters: int = 500,
    fan_paths: int = 400,
    cost_iters: int = 24,
    delays: tuple[int, ...] = (0, 1, 2),
    seed: int = 7,
    cost_model: SimpleCostModel | None = None,
    initial_cash: float = 100_000.0,
    tags: list[str] | None = None,
    registry_path: Path | None = None,
    description: str = "",
) -> dict:
    cost_model = cost_model or SimpleCostModel()
    strategy_name = strategy_cls.__name__
    code_hash = strategy_code_hash(strategy_cls())

    runner = make_store_runner(
        store=data_store, strategy_factory=strategy_cls, symbols=symbols,
        timeframe=timeframe, cost_model=cost_model, initial_cash=initial_cash,
        max_participation=None,
    )

    # Parameter sets: explicit value lists override each Param's own grid.
    spec = strategy_cls.params
    if param_values:
        names = [p.name for p in spec if p.name in param_values]
        combos: list[dict] = [{}]
        for name in names:
            combos = [{**c, name: v} for c in combos for v in param_values[name]]
        param_sets = combos
        param_ranges = {n: (min(param_values[n]), max(param_values[n])) for n in names}
    else:
        param_sets = grid_search_space(spec)
        param_ranges = {p.name: (p.min, p.max) for p in spec if p.min is not None}

    # 1) Holdout FIRST.
    frame = data_store.read(symbols[0], timeframe)
    index = [t.to_pydatetime() for t in frame["ts"]]
    work, guard = reserve_final_test(index, test_size)

    # 2) Walk-forward on the working index only.
    window = WindowSpec(train_size=train_size, val_size=val_size, expanding=expanding)
    wf = walk_forward(runner, work, window, param_sets, objective=objective)

    # 3) Deployment candidate: modal fold winner; latest fold breaks ties.
    counted = Counter(json.dumps(fr.best_params, sort_keys=True) for fr in wf.folds)
    top = counted.most_common()
    max_count = top[0][1]
    tied = {k for k, c in top if c == max_count}
    for fr in reversed(wf.folds):
        key = json.dumps(fr.best_params, sort_keys=True)
        if key in tied:
            selected_params = dict(fr.best_params)
            break

    # 4) Development run for display (params chosen on this data — labeled).
    dev = runner(selected_params, work[0], work[-1])
    equity = dev.equity_curve
    trades = dev.trades
    pnls = np.asarray(dev.trade_pnls, dtype=float)
    span_years = max((work[-1] - work[0]).days / 365.25, 1e-9)

    # 5) Sensitivity over the working range.
    opt = evaluate_param_sets(runner, param_sets, work[0], work[-1],
                              objective=objective)
    sens = summarize(opt)
    numeric_axes = [
        c[2:] for c in opt.table.columns
        if c.startswith("p_") and opt.table[c].nunique() > 1
    ]
    heat = None
    if len(numeric_axes) >= 2:
        x, y = numeric_axes[0], numeric_axes[1]
        heat = {
            "x": x, "y": y,
            "x_values": sorted(opt.table[f"p_{x}"].unique().tolist()),
            "y_values": sorted(opt.table[f"p_{y}"].unique().tolist()),
            "objective": objective,
            "cells": [
                {
                    "x": _json_safe(row[f"p_{x}"]), "y": _json_safe(row[f"p_{y}"]),
                    "sharpe": _json_safe(row.get("sharpe")),
                    "max_drawdown": _json_safe(row.get("max_drawdown")),
                    "profit_factor": _json_safe(row.get("profit_factor")),
                    "win_rate": _json_safe(row.get("win_rate")),
                    "n_trades": _json_safe(row.get("n_trades")),
                }
                for _, row in opt.table.iterrows()
            ],
        }

    # 6) Monte Carlo.
    mc_cis: dict = {}
    mc_block: dict = {}
    if len(pnls) >= 3:
        methods = {
            "reshuffle": trade_reshuffle(pnls, initial_cash, span_years, mc_iters, seed),
            "bootstrap": bootstrap_trades(pnls, initial_cash, span_years, mc_iters, seed + 1),
            "skip": skip_trades(pnls, initial_cash, span_years, mc_iters, seed + 2),
        }
        for name, mc in methods.items():
            mc_cis[name] = {
                metric: {col: _json_safe(mc.ci.loc[metric, col]) for col in mc.ci.columns}
                for metric in mc.ci.index
            }
        mc_block["fan"] = _mc_fan(pnls, initial_cash, fan_paths, seed + 3)
        mc_block["histograms"] = {
            "end_equity": _json_safe(methods["bootstrap"].samples["end_equity"].tolist()),
            "max_drawdown": _json_safe(methods["bootstrap"].samples["max_drawdown"].tolist()),
        }

        def run_with_costs(s_mult: float, c_mult: float):
            pert = make_store_runner(
                store=data_store, strategy_factory=strategy_cls, symbols=symbols,
                timeframe=timeframe, cost_model=cost_model,
                initial_cash=initial_cash, max_participation=None,
                slippage_mult=s_mult, commission_mult=c_mult,
            )
            return pert(selected_params, work[0], work[-1])

        cost_mc = perturbed_cost_runs(run_with_costs, n_iter=cost_iters, seed=seed + 4)
        mc_cis["perturbed_costs"] = {
            metric: {col: _json_safe(cost_mc.ci.loc[metric, col]) for col in cost_mc.ci.columns}
            for metric in cost_mc.ci.index
        }

        from engine.data.feeds import DataFrameFeed  # noqa: F401  (doc pointer)
        from engine.metrics.performance import full_report
        from engine.validation.montecarlo import DelayedStrategy
        from engine.backtest import Backtester
        from engine.data.history import HistoryService
        from engine.params import resolve_params
        from engine.run import run_research_backtest  # noqa: F401
        from engine.sdk import SDKAdapter

        def run_with_delay(d: int):
            frames = {sym: data_store.read(sym, timeframe, work[0], work[-1])
                      for sym in symbols}
            history = HistoryService({(s, str(timeframe)): f for s, f in frames.items()})
            adapter = SDKAdapter(strategy_cls(),
                                 resolve_params(spec, selected_params), history)
            wrapped = DelayedStrategy(adapter, delay_bars=d)
            feed = DataFrameFeed(frames)
            bt = Backtester(feed, wrapped, cost_model, initial_cash=initial_cash,
                            max_participation=None)
            result = bt.run(resolve_params(spec, selected_params))
            result.metrics = full_report(result.equity_curve, result.trade_pnls,
                                         result.exposure)
            return result

        delay_table = delayed_execution_runs(run_with_delay, delays=delays)
        mc_block["delay_sweep"] = _json_safe(delay_table.to_dict(orient="records"))

    # 7) Regimes.
    closes = frame.set_index("ts")["close"]
    labels = classify(closes, RegimeConfig())
    regime_block = {}
    if len(equity):
        for col in ("vol_regime", "trend_regime", "trending"):
            table = regime_metrics(equity, labels[col])
            regime_block[col] = _json_safe(table.to_dict(orient="index"))

    # 8) Warnings.
    warnings = []
    n_trades = int(dev.metrics.get("n_trades", 0))
    for w in (
        check_narrow_peak(sens.neighbor_consistency),
        check_train_val_divergence(
            float(wf.train_table[objective].astype(float).mean()),
            float(wf.val_table[objective].astype(float).mean()),
        ),
        check_few_trades(n_trades),
        check_complexity(len(param_sets), n_trades),
        check_surface_stability([fr.best_params for fr in wf.folds], param_ranges),
    ):
        if w is not None:
            warnings.append(w)
    snapshot = data_store.snapshot(symbols, timeframe, work[0], index[-1])
    if registry_path is not None:
        Path(registry_path).parent.mkdir(parents=True, exist_ok=True)
    registry = OptimizationRegistry(path=registry_path)
    registry.register(snapshot.fingerprint, code_hash)
    reg_warning = registry.check(snapshot.fingerprint, code_hash)
    if reg_warning is not None:
        warnings.append(reg_warning)

    # 9) The one holdout evaluation.
    final = guard.evaluate(runner, selected_params)
    final_metrics = _json_safe(dict(final.metrics))

    # 10) Report.
    report = build_report(
        strategy_name=strategy_name,
        strategy_description=description or (strategy_cls.__doc__ or "").strip(),
        parameters=selected_params,
        dataset_fingerprint=snapshot.fingerprint,
        optimization_summary={"n_evals": opt.n_evals, "best_score": _json_safe(opt.best_score),
                              "sampler": opt.sampler},
        walkforward_aggregate=_json_safe(wf.aggregate),
        validation_summary={"validation_consistency": _json_safe(validation_consistency(wf))},
        regime_table=regime_block.get("trend_regime", {}),
        mc_cis=mc_cis,
        sensitivity=sens.to_dict(),
        warnings=warnings,
        final_test=final_metrics,
    )

    created_at = datetime.now(UTC)
    exp_id = hashlib.sha256(
        f"{strategy_name}|{snapshot.fingerprint}|{json.dumps(selected_params, sort_keys=True)}"
        f"|{seed}|{created_at.isoformat()}".encode()
    ).hexdigest()[:12]

    fold_blocks = []
    for fr in wf.folds:
        fold_run = runner(fr.best_params, fr.fold.val_start, fr.fold.val_end)
        fold_blocks.append({
            "index": fr.fold.index,
            "train": [fr.fold.train_start.isoformat(), fr.fold.train_end.isoformat()],
            "validate": [fr.fold.val_start.isoformat(), fr.fold.val_end.isoformat()],
            "best_params": _json_safe(fr.best_params),
            "train_metrics": _json_safe(fr.train_metrics),
            "val_metrics": _json_safe(fr.val_metrics),
            "val_equity": _series_points(fold_run.equity_curve, 400),
            "val_trades": _trade_rows(fold_run.trades, cap=300),
        })

    return {
        "id": exp_id,
        "created_at": created_at.isoformat(),
        "engine_version": ENGINE_VERSION,
        "strategy": strategy_name,
        "strategy_code_hash": code_hash,
        "description": description or (strategy_cls.__doc__ or "").strip(),
        "symbols": sorted(symbols),
        "timeframe": str(timeframe),
        "objective": objective,
        "seed": seed,
        "tags": sorted(tags or []),
        "selected_params": _json_safe(selected_params),
        "param_sets_tested": len(param_sets),
        "dataset": _json_safe(snapshot.to_dict()),
        "windows": {
            "train_size": train_size, "val_size": val_size,
            "test_size": test_size, "expanding": expanding,
            "work_range": [work[0].isoformat(), work[-1].isoformat()],
            "holdout_range": [guard.start.isoformat(), guard.end.isoformat()],
        },
        "development": {
            "note": ("DEVELOPMENT RANGE: parameters were selected using this "
                     "data via walk-forward. Read final_test for the holdout."),
            "metrics": _json_safe(dict(dev.metrics)),
            "equity": _series_points(equity),
            "drawdown": _series_points(_drawdown(equity)),
            "exposure": _series_points(dev.exposure, 600),
            "monthly_returns": _monthly_returns(equity),
            "trades": _trade_rows(trades),
            "trade_pnls": _json_safe(pnls.tolist()),
        },
        "walkforward": {
            "aggregate": _json_safe(wf.aggregate),
            "validation_consistency": _json_safe(validation_consistency(wf)),
            "param_history": _json_safe(wf.param_history.to_dict(orient="records")),
            "folds": fold_blocks,
        },
        "sensitivity": {**sens.to_dict(), "heatmap": heat},
        "montecarlo": {"cis": mc_cis, **mc_block,
                       "iters": mc_iters, "seed": seed},
        "regimes": regime_block,
        "warnings": [w.to_dict() for w in warnings],
        "confidence": report.interpretation["confidence"],
        "final_test": final_metrics,
        "report_markdown": to_markdown(report),
    }
