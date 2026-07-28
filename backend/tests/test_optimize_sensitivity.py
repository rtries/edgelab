"""Samplers and sensitivity math on hand-built surfaces."""
import pytest

from engine.params import Param
from engine.validation import sensitivity as sens
from engine.validation.optimize import (
    OptimizationResult,
    evaluate_param_sets,
    grid_search_space,
    latin_hypercube_space,
    param_grid_values,
    random_search_space,
)

from tests.helpers import ts

SPEC = [
    Param("fast", "int", 3, min=2, max=4, step=1),
    Param("slow", "int", 6, min=5, max=7, step=1),
]


def test_grid_enumeration_deterministic():
    combos = grid_search_space(SPEC)
    # 3 x 3 = 9 combos; spec order; later params vary fastest.
    assert len(combos) == 9
    assert combos[0] == {"fast": 2, "slow": 5}
    assert combos[1] == {"fast": 2, "slow": 6}
    assert combos[-1] == {"fast": 4, "slow": 7}
    assert grid_search_space(SPEC) == combos   # rerun identical


def test_grid_float_step_and_bool():
    spec = [Param("x", "float", 0.2, min=0.1, max=0.3, step=0.1),
            Param("flag", "bool", True)]
    values = param_grid_values(spec)
    assert values["x"] == pytest.approx([0.1, 0.2, 0.3])
    assert values["flag"] == [False, True]
    assert len(grid_search_space(spec)) == 6


def test_grid_requires_bounds():
    with pytest.raises(ValueError, match="min/max/step"):
        grid_search_space([Param("x", "int", 3)])


def test_random_search_seeded_and_snapped():
    a = random_search_space(SPEC, n=20, seed=42)
    b = random_search_space(SPEC, n=20, seed=42)
    c = random_search_space(SPEC, n=20, seed=43)
    assert a == b            # same seed -> identical
    assert a != c            # different seed -> different draws
    for params in a:
        assert params["fast"] in (2, 3, 4)     # snapped to grid, in bounds
        assert params["slow"] in (5, 6, 7)
        assert isinstance(params["fast"], int)


def test_latin_hypercube_stratification():
    spec = [Param("x", "float", 0.5, min=0.0, max=1.0)]  # no step: raw strata
    n = 10
    samples = latin_hypercube_space(spec, n=n, seed=7)
    xs = sorted(p["x"] for p in samples)
    # exactly one sample per stratum [i/n, (i+1)/n)
    for i, x in enumerate(xs):
        assert i / n <= x < (i + 1) / n, (i, x)
    assert latin_hypercube_space(spec, n=n, seed=7) == samples   # deterministic


class StubResult:
    def __init__(self, metrics):
        self.metrics = metrics


def surface_runner(surface):
    """runner whose sharpe comes from a dict keyed (fast, slow)."""
    def runner(params, start, end):
        return StubResult({"sharpe": surface[(params["fast"], params["slow"])]})
    return runner


def make_opt(surface) -> OptimizationResult:
    return evaluate_param_sets(
        surface_runner(surface), grid_search_space(SPEC), ts(1), ts(10), "sharpe"
    )


# Hand-built 3x3 surfaces, rows fast (2,3,4) x cols slow (5,6,7):
ISOLATED = {  # spike at (3,6); all 4 neighbors 0.1
    (2, 5): 0.05, (2, 6): 0.10, (2, 7): 0.05,
    (3, 5): 0.10, (3, 6): 1.00, (3, 7): 0.10,
    (4, 5): 0.05, (4, 6): 0.10, (4, 7): 0.05,
}
PLATEAU = {  # broad flat top: everything 0.8 except one weak corner
    (2, 5): 0.80, (2, 6): 0.80, (2, 7): 0.80,
    (3, 5): 0.80, (3, 6): 0.80, (3, 7): 0.80,
    (4, 5): 0.80, (4, 6): 0.80, (4, 7): 0.10,
}


def test_best_selection_and_tiebreak():
    opt = make_opt(ISOLATED)
    assert opt.best_params == {"fast": 3, "slow": 6}
    assert opt.best_score == 1.0
    # PLATEAU has 8 tied combos at 0.8: deterministic tie-break -> smallest
    # sorted param tuple: fast=2, slow=5.
    opt2 = make_opt(PLATEAU)
    assert opt2.best_params == {"fast": 2, "slow": 5}


def test_neighbor_consistency_hand_computed():
    # ISOLATED best (3,6): neighbors (2,6),(4,6),(3,5),(3,7) all 0.10.
    # consistency = mean(0.1 x4) / 1.0 = 0.1.
    assert sens.neighbor_consistency(make_opt(ISOLATED)) == pytest.approx(0.1)
    # PLATEAU best (2,5): neighbors (3,5)=0.8,(2,6)=0.8 -> 0.8/0.8 = 1.0.
    assert sens.neighbor_consistency(make_opt(PLATEAU)) == pytest.approx(1.0)


def test_plateau_fraction_hand_computed():
    # ISOLATED: q75 of [0.05 x4, 0.1 x4, 1.0] -> threshold 0.1; top set = the
    # four 0.1 neighbors + peak = 5 points, all Manhattan-connected through
    # the center -> one component of 5; best inside -> 5/9.
    assert sens.plateau_fraction(make_opt(ISOLATED)) == pytest.approx(5 / 9)
    # PLATEAU: threshold = q75 of [0.8 x8, 0.1] = 0.8 -> component of 8 -> 8/9.
    assert sens.plateau_fraction(make_opt(PLATEAU)) == pytest.approx(8 / 9)


def test_robustness_score_prefers_plateau_over_spike():
    r_spike = sens.robustness_score(make_opt(ISOLATED))
    r_plateau = sens.robustness_score(make_opt(PLATEAU))
    # spike: sqrt(0.1 * 5/9) = sqrt(0.0555556) = 0.2357023
    assert r_spike == pytest.approx(0.2357023, rel=1e-5)
    # plateau: sqrt(1.0 * 8/9) = 0.9428090
    assert r_plateau == pytest.approx(0.9428090, rel=1e-5)
    assert r_plateau > r_spike


def test_summarize_bundles_the_numbers():
    summary = sens.summarize(make_opt(PLATEAU))
    assert summary.n_combos == 9
    assert summary.robustness_score == pytest.approx(0.9428090, rel=1e-5)


def test_heatmap_pivot():
    hm = sens.heatmap(make_opt(ISOLATED), x="slow", y="fast")
    assert hm.loc[3, 6] == 1.0
    assert hm.loc[2, 5] == 0.05
    assert hm.shape == (3, 3)


def test_nan_objective_never_wins():
    surface = dict(ISOLATED)
    surface[(3, 6)] = float("nan")
    opt = make_opt(surface)
    assert opt.best_params != {"fast": 3, "slow": 6}
    assert opt.best_score == pytest.approx(0.10)
