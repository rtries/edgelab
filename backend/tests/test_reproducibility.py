"""Reproducibility: manifests, code hashes, and bit-identical reruns."""
from datetime import UTC, datetime

import pytest

from engine import __version__ as ENGINE_VERSION
from engine.data.schema_types import AdjustmentMode, Timeframe
from engine.data.store import ParquetStore
from engine.execution.costs import SimpleCostModel
from engine.run import run_research_backtest, strategy_code_hash
from engine.strategies.examples import MACrossover

from tests.helpers_data import canon_daily

ROWS = [(d, 100 + d, 102 + d, 99 + d, 101 + d, 10_000) for d in range(1, 13)]
START = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2024, 1, 31, tzinfo=UTC)


def make_store(tmp_path):
    store = ParquetStore(tmp_path / "store")
    store.write(canon_daily(ROWS))
    return store


def run_once(store, params=None):
    return run_research_backtest(
        store=store,
        strategy=MACrossover(),
        symbols=["X"],
        timeframe=Timeframe.D1,
        start=START,
        end=END,
        params=params or {"fast": 2, "slow": 3},
        cost_model=SimpleCostModel(),
        adjustment_mode=AdjustmentMode.RAW,
        initial_cash=50_000,
    )


def test_manifest_records_every_required_field(tmp_path):
    result = run_once(make_store(tmp_path))
    m = result.manifest
    required = [
        "strategy_name", "strategy_code_hash", "params", "dataset_fingerprint",
        "dataset_snapshot", "symbols", "timeframe", "start", "end",
        "adjustment_mode", "commission_model", "slippage_model",
        "engine_version", "run_at",
    ]
    for key in required:
        assert key in m, key
    assert m["strategy_name"] == "MACrossover"
    assert m["engine_version"] == ENGINE_VERSION
    assert m["timeframe"] == "1d"
    assert m["adjustment_mode"] == "raw"
    assert m["params"] == {"fast": 2, "slow": 3, "invest_pct": 0.9}
    assert len(m["dataset_fingerprint"]) == 64
    assert "SimpleCostModel" in m["commission_model"]


def test_identical_runs_are_identical_except_run_at(tmp_path):
    store = make_store(tmp_path)
    r1, r2 = run_once(store), run_once(store)
    assert r1.equity_curve.equals(r2.equity_curve)
    assert r1.trades.equals(r2.trades)
    assert [f.price for f in r1.fills] == [f.price for f in r2.fills]
    m1 = {k: v for k, v in r1.manifest.items() if k != "run_at"}
    m2 = {k: v for k, v in r2.manifest.items() if k != "run_at"}
    assert m1 == m2
    assert r1.metrics == r2.metrics


def test_code_hash_is_stable_and_class_specific(tmp_path):
    h1 = strategy_code_hash(MACrossover())
    h2 = strategy_code_hash(MACrossover())
    assert h1 == h2
    from engine.strategies.examples import BuyAndHold
    assert strategy_code_hash(BuyAndHold()) != h1


def test_fingerprint_changes_when_data_changes(tmp_path):
    r1 = run_once(make_store(tmp_path))
    other = ParquetStore(tmp_path / "other")
    changed = list(ROWS)
    changed[5] = (6, 106, 108.5, 105, 107.25, 10_000)   # one close nudged
    other.write(canon_daily(changed))
    r2 = run_once(other)
    assert r1.manifest["dataset_fingerprint"] != r2.manifest["dataset_fingerprint"]


def test_params_recorded_affect_hash_of_run_not_code(tmp_path):
    store = make_store(tmp_path)
    r1 = run_once(store, {"fast": 2, "slow": 3})
    r2 = run_once(store, {"fast": 2, "slow": 4})
    assert r1.manifest["strategy_code_hash"] == r2.manifest["strategy_code_hash"]
    assert r1.manifest["params"] != r2.manifest["params"]


def test_metrics_attached_to_result(tmp_path):
    result = run_once(make_store(tmp_path))
    assert "sharpe" in result.metrics
    assert "max_drawdown" in result.metrics
    assert result.metrics["start_equity"] == pytest.approx(50_000.0)
