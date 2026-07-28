"""Parameter sensitivity: surfaces, neighborhoods, stability regions.

Everything operates on an OptimizationResult table over a REGULAR grid
(param_grid_values ordering). Definitions — pinned, hand-fixtured:

- neighbors(point): Manhattan neighbors — combos differing by exactly one
  grid step in exactly one parameter.
- neighbor_consistency(best) = clip(mean(objective over neighbors)
  / objective(best), 0, 1); 0 if objective(best) <= 0.
  A value near 1 means the peak's neighborhood performs like the peak; a
  value near 0 means an isolated spike — the classic overfit signature.
- stability region: connected component (via Manhattan adjacency) of the
  top-quantile combos. plateau_fraction(best) = |component containing
  best| / |all combos| when best is inside the top-quantile set, else 0.
- robustness_score = sqrt(neighbor_consistency * plateau_fraction).
  Geometric mean: BOTH a supportive neighborhood and a broad plateau are
  required for a high score. Prefer broad stable regions over peaks.
- heatmap(x, y): pivot of mean objective over the other parameters.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import pandas as pd

from engine.validation.optimize import OptimizationResult


def _param_columns(table: pd.DataFrame) -> list[str]:
    return [c for c in table.columns if c.startswith("p_")]


def _grid_axes(table: pd.DataFrame) -> dict[str, list]:
    return {c: sorted(table[c].unique().tolist()) for c in _param_columns(table)}


def _point_key(row, cols) -> tuple:
    return tuple(row[c] for c in cols)


def _neighbor_keys(key: tuple, axes: dict[str, list], cols: list[str]) -> list[tuple]:
    out = []
    for i, col in enumerate(cols):
        values = axes[col]
        pos = values.index(key[i])
        for d in (-1, 1):
            j = pos + d
            if 0 <= j < len(values):
                out.append(key[:i] + (values[j],) + key[i + 1 :])
    return out


def neighbor_consistency(opt: OptimizationResult) -> float:
    table, cols = opt.table, _param_columns(opt.table)
    axes = _grid_axes(table)
    scores = {
        _point_key(row, cols): row[opt.objective] for _, row in table.iterrows()
    }
    best_key = tuple(opt.best_params[c[2:]] for c in cols)
    peak = scores[best_key]
    if peak is None or peak <= 0:
        return 0.0
    neigh = [scores[k] for k in _neighbor_keys(best_key, axes, cols) if k in scores]
    if not neigh:
        return 0.0
    return float(max(0.0, min(1.0, (sum(neigh) / len(neigh)) / peak)))


def stability_regions(opt: OptimizationResult, quantile: float = 0.75) -> list[set[tuple]]:
    """Connected components of the top-(1-quantile) combos, largest first."""
    table, cols = opt.table, _param_columns(opt.table)
    axes = _grid_axes(table)
    threshold = table[opt.objective].quantile(quantile)
    top = {
        _point_key(row, cols)
        for _, row in table.iterrows()
        if row[opt.objective] >= threshold
    }
    components: list[set[tuple]] = []
    unvisited = set(top)
    while unvisited:
        seed = next(iter(sorted(unvisited)))
        component, queue = {seed}, deque([seed])
        unvisited.discard(seed)
        while queue:
            node = queue.popleft()
            for nk in _neighbor_keys(node, axes, cols):
                if nk in unvisited:
                    unvisited.discard(nk)
                    component.add(nk)
                    queue.append(nk)
        components.append(component)
    return sorted(components, key=len, reverse=True)


def plateau_fraction(opt: OptimizationResult, quantile: float = 0.75) -> float:
    cols = _param_columns(opt.table)
    best_key = tuple(opt.best_params[c[2:]] for c in cols)
    for component in stability_regions(opt, quantile):
        if best_key in component:
            return len(component) / len(opt.table)
    return 0.0


def robustness_score(opt: OptimizationResult, quantile: float = 0.75) -> float:
    return float(
        (neighbor_consistency(opt) * plateau_fraction(opt, quantile)) ** 0.5
    )


def heatmap(opt: OptimizationResult, x: str, y: str) -> pd.DataFrame:
    """Mean objective over all other params, indexed y (rows) x (cols)."""
    return opt.table.pivot_table(
        index=f"p_{y}", columns=f"p_{x}", values=opt.objective, aggfunc="mean"
    )


@dataclass(frozen=True, slots=True)
class SensitivitySummary:
    neighbor_consistency: float
    plateau_fraction: float
    robustness_score: float
    n_combos: int

    def to_dict(self) -> dict:
        return {
            "neighbor_consistency": self.neighbor_consistency,
            "plateau_fraction": self.plateau_fraction,
            "robustness_score": self.robustness_score,
            "n_combos": self.n_combos,
        }


def summarize(opt: OptimizationResult, quantile: float = 0.75) -> SensitivitySummary:
    return SensitivitySummary(
        neighbor_consistency=neighbor_consistency(opt),
        plateau_fraction=plateau_fraction(opt, quantile),
        robustness_score=robustness_score(opt, quantile),
        n_combos=len(opt.table),
    )
