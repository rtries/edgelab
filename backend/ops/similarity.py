"""Pattern similarity — "when did the market look like this before, and
what happened those times?"

Mechanics: z-score the numeric features across the library (features
with zero variance or missing values are excluded per-query, and the
result says which were used), Euclidean k-nearest-neighbors, outcomes
summarized as a distribution.

THIS IS DESCRIPTIVE, NOT PREDICTIVE. A neighborhood win rate is a
statement about a small historical sample, not a probability for the
next trade. The result object carries `n`, the dispersion of outcomes,
and a fixed framing note so no downstream surface can quietly present
it as a forecast.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ops.patterns import NUMERIC_FEATURES, PatternRecord

FRAMING = (
    "Descriptive, not predictive: these are historical situations with "
    "similar measured features and their recorded outcomes. Sample sizes "
    "are small and past outcomes do not estimate future probabilities."
)


@dataclass(frozen=True, slots=True)
class SimilarityResult:
    query_features: dict
    features_used: list[str]
    neighbors: list[dict]
    outcome_distribution: dict
    note: str = FRAMING

    def to_dict(self) -> dict:
        return {
            "query_features": self.query_features,
            "features_used": self.features_used,
            "neighbors": self.neighbors,
            "outcome_distribution": self.outcome_distribution,
            "note": self.note,
        }


def find_similar(
    library: list[PatternRecord],
    query_features: dict,
    k: int = 10,
) -> SimilarityResult:
    # Features usable for THIS query: numeric, present in the query, and
    # present with variance in the library.
    usable: list[str] = []
    for name in NUMERIC_FEATURES:
        if query_features.get(name) is None:
            continue
        values = [r.features.get(name) for r in library]
        values = [v for v in values if v is not None]
        if len(values) >= 2 and float(np.std(values)) > 0:
            usable.append(name)
    if not usable or not library:
        return SimilarityResult(
            query_features=query_features, features_used=[],
            neighbors=[], outcome_distribution={"n": 0},
        )

    rows, kept = [], []
    for record in library:
        if any(record.features.get(name) is None for name in usable):
            continue
        rows.append([float(record.features[name]) for name in usable])
        kept.append(record)
    if not rows:
        return SimilarityResult(
            query_features=query_features, features_used=usable,
            neighbors=[], outcome_distribution={"n": 0},
        )

    matrix = np.asarray(rows, dtype=float)
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0)
    std[std == 0] = 1.0
    z = (matrix - mean) / std
    q = (np.array([float(query_features[name]) for name in usable]) - mean) / std
    distances = np.linalg.norm(z - q, axis=1)
    order = np.argsort(distances, kind="stable")[:k]

    neighbors = [
        {
            "id": kept[i].id,
            "distance": float(distances[i]),
            "symbol": kept[i].symbol,
            "strategy": kept[i].strategy,
            "ts": kept[i].ts,
            "features": kept[i].features,
            "outcome": kept[i].outcome,
        }
        for i in order
    ]
    pnls = [n["outcome"]["net_pnl"] for n in neighbors
            if n["outcome"] is not None]
    wins = [n["outcome"]["win"] for n in neighbors if n["outcome"] is not None]
    distribution = {
        "n": len(neighbors),
        "n_resolved": len(pnls),
        "win_rate": float(np.mean(wins)) if wins else None,
        "mean_pnl": float(np.mean(pnls)) if pnls else None,
        "median_pnl": float(np.median(pnls)) if pnls else None,
        "pnl_std": float(np.std(pnls, ddof=1)) if len(pnls) > 1 else None,
    }
    return SimilarityResult(
        query_features={name: query_features[name] for name in usable},
        features_used=usable,
        neighbors=neighbors,
        outcome_distribution=distribution,
    )
