"""Shared fixtures for ops tests: one synthetic dataset + one experiment,
built once per session. Import via `from tests.ops_fixtures import *` in
conftest or use the fixtures directly."""
import pytest

from engine.data.store import ParquetStore
from engine.strategies.examples import MACrossover
from research.pipeline import run_experiment

from tests.test_research_pipeline import synth_frame


@pytest.fixture(scope="session")
def ops_env(tmp_path_factory):
    root = tmp_path_factory.mktemp("ops_env")
    data = ParquetStore(root / "data")
    data.write(synth_frame(symbol="DEMO", n=140, seed=5))
    exp = run_experiment(
        data_store=data, strategy_cls=MACrossover, symbols=["DEMO"],
        param_values={"fast": [2, 4], "slow": [8, 12]},
        train_size=50, val_size=15, test_size=25,
        mc_iters=50, fan_paths=40, cost_iters=4, seed=11,
        delays=(0, 1), tags=["ops-fixture"],
        registry_path=root / "registry.json",
    )
    return {"root": root, "data_store": data, "experiment": exp}
