"""Walk-forward end-to-end through the real store + SDK, plus strategy
comparison ranking with hand-checked ranks."""
import numpy as np
import pandas as pd
import pytest

from engine.data.schema_types import Timeframe
from engine.data.store import ParquetStore
from engine.execution.costs import SimpleCostModel
from engine.strategies.examples import MACrossover
from engine.validation.compare import StrategyRecord, rank_strategies
from engine.validation.runners import make_store_runner
from engine.validation.splits import WindowSpec, reserve_final_test
from engine.validation.walkforward import validation_consistency, walk_forward

from tests.helpers_data import canon_daily

N_BARS = 60
ROWS = [
    (i, 100 + 0.5 * i + 3 * np.sin(i / 4), 0, 0, 0, 50_000) for i in range(N_BARS)
]
# fill o/h/l/c consistently around the close path
ROWS = [
    (i + 1, c - 0.2, c + 0.6, c - 0.6, c, 50_000)
    for i, (_, c, *_rest) in enumerate(ROWS)
]


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    root = tmp_path_factory.mktemp("wf_store")
    s = ParquetStore(root)
    # canon_daily builds Jan 2024 days 1..60 -> overflows month; build two months
    rows_jan = [r for r in ROWS if r[0] <= 31]
    rows_feb = [(r[0] - 31, *r[1:]) for r in ROWS if r[0] > 31]
    df = pd.concat(
        [canon_daily(rows_jan), _canon_feb(rows_feb)], ignore_index=True
    ).sort_values("ts", kind="stable").reset_index(drop=True)
    df.attrs["adjustment_mode"] = "raw"
    s.write(df)
    return s


def _canon_feb(rows):
    from datetime import UTC, datetime

    from engine.data.schema import normalize

    ts_col = [datetime(2024, 2, d, 21, 0, tzinfo=UTC) for d, *_ in rows]
    raw = pd.DataFrame(
        {
            "ts": ts_col,
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
            "volume": [r[5] for r in rows],
        }
    )
    return normalize(raw, symbol="X", timeframe=Timeframe.D1, source="test")


@pytest.fixture(scope="module")
def runner(store):
    return make_store_runner(
        store=store,
        strategy_factory=MACrossover,
        symbols=["X"],
        timeframe=Timeframe.D1,
        cost_model=SimpleCostModel(),
        initial_cash=100_000,
        max_participation=None,
    )


PARAM_SETS = [
    {"fast": 2, "slow": 5},
    {"fast": 3, "slow": 8},
]


def bar_index(store):
    df = store.read("X", Timeframe.D1)
    return [t.to_pydatetime() for t in df["ts"]]


def test_walk_forward_structure_and_determinism(store, runner):
    index = bar_index(store)
    wf1 = walk_forward(runner, index, WindowSpec(train_size=25, val_size=10),
                       PARAM_SETS, objective="sharpe")
    wf2 = walk_forward(runner, index, WindowSpec(train_size=25, val_size=10),
                       PARAM_SETS, objective="sharpe")
    # 60 bars, train 25, val 10, step 10 -> folds with train_end at pos
    # 24, 34, 44; pos 54 leaves only 5 val bars -> 3 folds.
    assert wf1.n_folds == 3
    assert len(wf1.param_history) == 3
    assert set(wf1.param_history.columns) >= {"fold", "fast", "slow"}
    for fr in wf1.folds:
        assert fr.best_params in PARAM_SETS
        assert "sharpe" in fr.train_metrics
        assert "sharpe" in fr.val_metrics
        assert fr.optimization.n_evals == len(PARAM_SETS)
    # deterministic end to end
    pd.testing.assert_frame_equal(wf1.val_table, wf2.val_table)
    pd.testing.assert_frame_equal(wf1.param_history, wf2.param_history)


def test_walk_forward_aggregate_math(store, runner):
    index = bar_index(store)
    wf = walk_forward(runner, index, WindowSpec(train_size=25, val_size=10),
                      PARAM_SETS, objective="sharpe")
    sharpes = wf.val_table["sharpe"].astype(float)
    assert wf.aggregate["n_folds"] == 3
    assert wf.aggregate["sharpe_mean"] == pytest.approx(sharpes.mean())
    assert wf.aggregate["sharpe_min"] == pytest.approx(sharpes.min())
    assert wf.aggregate["fraction_positive_objective"] == pytest.approx(
        (sharpes > 0).mean()
    )
    vc = validation_consistency(wf)
    assert vc == pytest.approx(sharpes.std(ddof=1))


def test_walk_forward_never_touches_reserved_holdout(store, runner):
    index = bar_index(store)
    work, guard = reserve_final_test(index, test_size=12)
    seen_ranges = []

    def spy_runner(params, start, end):
        seen_ranges.append((start, end))
        return runner(params, start, end)

    walk_forward(spy_runner, work, WindowSpec(train_size=25, val_size=10),
                 PARAM_SETS)
    holdout_start = guard.start
    assert all(end < holdout_start for _, end in seen_ranges)
    # And the guard still evaluates exactly once.
    final = guard.evaluate(runner, PARAM_SETS[0])
    assert "sharpe" in final.metrics
    with pytest.raises(RuntimeError):
        guard.evaluate(runner, PARAM_SETS[0])


# ── comparison ranking, hand-checked ──────────────────────────────────
def test_rank_strategies_hand_computed():
    # Three strategies, two ranked metrics present (sharpe, max_drawdown):
    #   A: sharpe 2.0, dd -0.10  -> rank_sharpe 1, rank_dd 1 -> overall 1.0
    #   B: sharpe 1.0, dd -0.30  -> rank_sharpe 2, rank_dd 3 -> overall 2.5
    #   C: sharpe 0.5, dd -0.20  -> rank_sharpe 3, rank_dd 2 -> overall 2.5
    # B vs C tie on overall -> alphabetical: B before C.
    records = [
        StrategyRecord("A", {"sharpe": 2.0, "max_drawdown": -0.10}),
        StrategyRecord("B", {"sharpe": 1.0, "max_drawdown": -0.30}),
        StrategyRecord("C", {"sharpe": 0.5, "max_drawdown": -0.20}),
    ]
    table = rank_strategies(records)
    assert list(table.index) == ["A", "B", "C"]
    assert table.loc["A", "overall_rank"] == pytest.approx(1.0)
    assert table.loc["B", "overall_rank"] == pytest.approx(2.5)
    assert table.loc["C", "overall_rank"] == pytest.approx(2.5)


def test_rank_directionality_lower_better_metrics():
    # validation_consistency: LOWER is better. mc_sharpe_lower: HIGHER better.
    records = [
        StrategyRecord("steady", {"sharpe": 1.0}, validation_consistency=0.1,
                       mc_sharpe_lower=0.5),
        StrategyRecord("jumpy", {"sharpe": 1.0}, validation_consistency=0.9,
                       mc_sharpe_lower=-0.2),
    ]
    table = rank_strategies(records)
    assert table.index[0] == "steady"
    assert table.loc["steady", "rank_validation_consistency"] == 1.0
    assert table.loc["steady", "rank_mc_sharpe_lower"] == 1.0


def test_context_metrics_not_ranked():
    records = [
        StrategyRecord("many_trades", {"sharpe": 0.5, "n_trades": 500, "exposure": 0.9}),
        StrategyRecord("few_trades", {"sharpe": 1.5, "n_trades": 40, "exposure": 0.2}),
    ]
    table = rank_strategies(records)
    assert "rank_n_trades" not in table.columns
    assert "rank_exposure" not in table.columns
    assert table.index[0] == "few_trades"      # ranked purely on sharpe here
