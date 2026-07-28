"""Overfitting detection: structured warnings, deterministic thresholds.

These are heuristics with pinned, documented thresholds — not proofs.
Their job is to force an explicit look at the classic failure modes, and
their absence is never evidence of a genuine edge.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ValidationWarning:
    code: str
    severity: str            # "info" | "warning" | "critical"
    message: str
    evidence: dict

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "evidence": self.evidence,
        }


def check_narrow_peak(
    neighbor_consistency: float, min_consistency: float = 0.5
) -> ValidationWarning | None:
    """Neighbors of the chosen optimum should carry it. Consistency below
    min_consistency means an isolated spike."""
    if neighbor_consistency < min_consistency:
        return ValidationWarning(
            code="narrow_peak",
            severity="critical" if neighbor_consistency < 0.25 else "warning",
            message=(
                f"optimum's neighborhood scores only {neighbor_consistency:.2f}x "
                "the peak — isolated peaks are the signature of curve fitting"
            ),
            evidence={"neighbor_consistency": neighbor_consistency,
                      "threshold": min_consistency},
        )
    return None


def check_train_val_divergence(
    train_score: float, val_score: float, max_decay: float = 0.5
) -> ValidationWarning | None:
    """Validation should retain a reasonable fraction of the train score."""
    if train_score <= 0:
        return None  # nothing to decay from; other checks handle bad strategies
    retained = val_score / train_score
    if val_score <= 0:
        return ValidationWarning(
            code="train_val_divergence",
            severity="critical",
            message=(
                f"train score {train_score:.2f} but validation {val_score:.2f} — "
                "the edge did not leave the training window"
            ),
            evidence={"train": train_score, "validation": val_score},
        )
    if retained < max_decay:
        return ValidationWarning(
            code="train_val_divergence",
            severity="warning",
            message=(
                f"validation retains only {retained:.0%} of the train score "
                f"(threshold {max_decay:.0%})"
            ),
            evidence={"train": train_score, "validation": val_score,
                      "retained": retained},
        )
    return None


def check_few_trades(n_trades: int, min_trades: int = 30) -> ValidationWarning | None:
    if n_trades < min_trades:
        return ValidationWarning(
            code="few_trades",
            severity="critical" if n_trades < max(10, min_trades // 3) else "warning",
            message=(
                f"{n_trades} trades — too few for statistics to mean anything "
                f"(want >= {min_trades})"
            ),
            evidence={"n_trades": n_trades, "min_trades": min_trades},
        )
    return None


def check_complexity(
    n_combos_tested: int, n_trades: int, max_ratio: float = 1.0
) -> ValidationWarning | None:
    """Testing more parameter combinations than you have trades virtually
    guarantees finding a spurious winner."""
    if n_trades <= 0 or n_combos_tested > max_ratio * n_trades:
        return ValidationWarning(
            code="excessive_complexity",
            severity="warning",
            message=(
                f"{n_combos_tested} combinations searched vs {n_trades} trades — "
                "selection bias risk grows with every extra combination"
            ),
            evidence={"n_combos": n_combos_tested, "n_trades": n_trades},
        )
    return None


def check_surface_stability(
    fold_best_params: list[dict],
    param_ranges: dict[str, tuple[float, float]],
    max_dispersion: float = 0.25,
) -> ValidationWarning | None:
    """Chosen parameters jumping across the space between folds means the
    optimization surface is noise. Dispersion per numeric param = std of
    chosen values / (range width); warn if any exceeds max_dispersion."""
    if len(fold_best_params) < 2:
        return None
    import statistics

    dispersions = {}
    for name, (lo, hi) in param_ranges.items():
        width = hi - lo
        if width <= 0:
            continue
        values = [float(p[name]) for p in fold_best_params if name in p]
        if len(values) >= 2:
            dispersions[name] = statistics.pstdev(values) / width
    worst = max(dispersions.values(), default=0.0)
    if worst > max_dispersion:
        return ValidationWarning(
            code="unstable_surface",
            severity="warning",
            message=(
                f"fold-to-fold parameter dispersion up to {worst:.2f} of the "
                "search range — the surface is not stable"
            ),
            evidence={"dispersion_by_param": dispersions,
                      "threshold": max_dispersion},
        )
    return None


@dataclass(slots=True)
class OptimizationRegistry:
    """Counts optimization runs per (dataset fingerprint, strategy hash).
    Re-optimizing the same data over and over is multiple-testing bias
    accumulating silently; this makes it loud. Optionally persisted."""

    path: Path | None = None
    counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.path is not None:
            self.path = Path(self.path)
            if self.path.exists():
                self.counts = json.loads(self.path.read_text())

    @staticmethod
    def _key(dataset_fingerprint: str, strategy_hash: str) -> str:
        return f"{dataset_fingerprint}:{strategy_hash}"

    def register(self, dataset_fingerprint: str, strategy_hash: str) -> int:
        key = self._key(dataset_fingerprint, strategy_hash)
        self.counts[key] = self.counts.get(key, 0) + 1
        if self.path is not None:
            self.path.write_text(json.dumps(self.counts, indent=2))
        return self.counts[key]

    def check(
        self, dataset_fingerprint: str, strategy_hash: str, max_runs: int = 3
    ) -> ValidationWarning | None:
        count = self.counts.get(self._key(dataset_fingerprint, strategy_hash), 0)
        if count > max_runs:
            return ValidationWarning(
                code="repeated_optimization",
                severity="warning",
                message=(
                    f"this dataset/strategy pair has been optimized {count} times "
                    f"(threshold {max_runs}) — every additional pass inflates the "
                    "best result by selection alone"
                ),
                evidence={"runs": count, "max_runs": max_runs},
            )
        return None
