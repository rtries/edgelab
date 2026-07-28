"""Parameter samplers and search execution.

Samplers (all deterministic; random ones take an explicit seed):
- grid_search_space: full cartesian product of each Param's grid
  (min..max by step for numerics; [False, True] for bools; [default] for
  str). Deterministic ordering: params in spec order, values ascending.
- random_search_space: uniform draws snapped to the param grid.
- latin_hypercube_space: one sample per stratum per dimension
  (stratified), permuted per-dimension with the seeded RNG, snapped to
  the grid. Better coverage than random for the same n.

evaluate_param_sets() runs each candidate through a runner
(params, start, end) -> BacktestResult and tabulates result.metrics.
Ties on the objective break by parameter tuple for reproducibility.
NaN/missing objectives sort last (treated as -inf), never win.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from engine.params import Param


def _numeric_grid(p: Param) -> list:
    if p.min is None or p.max is None or p.step is None:
        raise ValueError(
            f"param '{p.name}' needs min/max/step for grid search"
        )
    n = int(math.floor((p.max - p.min) / p.step + 1e-9)) + 1
    values = [p.min + i * p.step for i in range(n)]
    if p.type == "int":
        values = [int(round(v)) for v in values]
    return values


def param_grid_values(spec: Sequence[Param]) -> dict[str, list]:
    out: dict[str, list] = {}
    for p in spec:
        if p.type in ("int", "float"):
            out[p.name] = _numeric_grid(p)
        elif p.type == "bool":
            out[p.name] = [False, True]
        else:
            out[p.name] = [p.default]
    return out


def grid_search_space(spec: Sequence[Param]) -> list[dict]:
    grids = param_grid_values(spec)
    names = [p.name for p in spec]
    combos: list[dict] = [{}]
    for name in names:
        combos = [{**c, name: v} for c in combos for v in grids[name]]
    return combos


def _snap(p: Param, x: float):
    if p.step is not None and p.min is not None:
        k = round((x - p.min) / p.step)
        x = p.min + k * p.step
    x = min(max(x, p.min if p.min is not None else x), p.max if p.max is not None else x)
    return int(round(x)) if p.type == "int" else float(x)


def random_search_space(spec: Sequence[Param], n: int, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        params = {}
        for p in spec:
            if p.type in ("int", "float"):
                params[p.name] = _snap(p, rng.uniform(p.min, p.max))
            elif p.type == "bool":
                params[p.name] = bool(rng.integers(0, 2))
            else:
                params[p.name] = p.default
        out.append(params)
    return out


def latin_hypercube_space(spec: Sequence[Param], n: int, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    numeric = [p for p in spec if p.type in ("int", "float")]
    columns: dict[str, list] = {}
    for p in numeric:
        # one uniform draw inside each of n strata, then permute strata order
        strata = (np.arange(n) + rng.uniform(0.0, 1.0, n)) / n
        rng.shuffle(strata)
        columns[p.name] = [_snap(p, p.min + u * (p.max - p.min)) for u in strata]
    out = []
    for i in range(n):
        params = {}
        for p in spec:
            if p.type in ("int", "float"):
                params[p.name] = columns[p.name][i]
            elif p.type == "bool":
                params[p.name] = bool(rng.integers(0, 2))
            else:
                params[p.name] = p.default
        out.append(params)
    return out


@dataclass(slots=True)
class OptimizationResult:
    table: pd.DataFrame          # one row per candidate: params + metrics
    objective: str
    best_params: dict
    best_score: float
    sampler: str
    n_evals: int


def evaluate_param_sets(
    runner: Callable[[dict, datetime, datetime], object],
    param_sets: Sequence[dict],
    start: datetime,
    end: datetime,
    objective: str = "sharpe",
    sampler: str = "grid",
) -> OptimizationResult:
    if not param_sets:
        raise ValueError("no parameter sets to evaluate")
    rows = []
    for params in param_sets:
        result = runner(dict(params), start, end)
        metrics = dict(result.metrics)
        score = metrics.get(objective, float("nan"))
        rows.append({**{f"p_{k}": v for k, v in params.items()}, **metrics,
                     "_params": dict(params), "_score": score})
    table = pd.DataFrame(rows)

    def sort_key(row):
        s = row["_score"]
        s = -math.inf if (s is None or (isinstance(s, float) and math.isnan(s))) else s
        return (-s, tuple(sorted(row["_params"].items())))

    ordered = sorted(rows, key=sort_key)
    best = ordered[0]
    best_score = best["_score"]
    if isinstance(best_score, float) and math.isnan(best_score):
        best_score = -math.inf
    return OptimizationResult(
        table=table.drop(columns=["_score"]),
        objective=objective,
        best_params=best["_params"],
        best_score=float(best_score),
        sampler=sampler,
        n_evals=len(param_sets),
    )
