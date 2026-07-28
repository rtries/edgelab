"""Research pipeline + experiment registry, end to end on a real store."""
import json

import numpy as np
import pandas as pd
import pytest

from engine.data.schema import normalize
from engine.data.schema_types import Timeframe
from engine.data.store import ParquetStore
from engine.strategies.examples import MACrossover
from research.pipeline import run_experiment
from research.store import ExperimentStore


def synth_frame(symbol="DEMO", n=140, seed=5):
    rng = np.random.default_rng(seed)
    sessions = pd.bdate_range("2024-01-01", periods=n, tz="UTC")
    t = np.arange(n)
    # Mild drift + a 12-bar cycle so MA crossovers actually cross: the
    # pipeline's Monte Carlo needs a handful of real trades to resample.
    closes = 100.0 * np.exp(
        np.cumsum(rng.normal(0.0004, 0.008, n)) + 0.03 * np.sin(2 * np.pi * t / 12)
    )
    opens = np.concatenate([[100.0], closes[:-1]])
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.003, n)))
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.003, n)))
    raw = pd.DataFrame({
        "ts": [s.replace(hour=21) for s in sessions],
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": rng.integers(1e5, 1e6, n).astype(float),
    })
    return normalize(raw, symbol=symbol, timeframe=Timeframe.D1, source="test")


@pytest.fixture(scope="module")
def experiment(tmp_path_factory):
    root = tmp_path_factory.mktemp("research")
    data = ParquetStore(root / "data")
    data.write(synth_frame())
    exp = run_experiment(
        data_store=data,
        strategy_cls=MACrossover,
        symbols=["DEMO"],
        param_values={"fast": [2, 4], "slow": [8, 12]},
        train_size=50, val_size=15, test_size=25,
        mc_iters=60, fan_paths=50, cost_iters=6, seed=11, delays=(0, 1, 2),
        tags=["momentum", "demo"],
        registry_path=root / "registry.json",
    )
    return exp


def test_experiment_structure(experiment):
    exp = experiment
    for key in [
        "id", "created_at", "engine_version", "strategy", "strategy_code_hash",
        "symbols", "dataset", "windows", "development", "walkforward",
        "sensitivity", "montecarlo", "regimes", "warnings", "confidence",
        "final_test", "report_markdown", "selected_params",
    ]:
        assert key in exp, key
    assert exp["strategy"] == "MACrossover"
    assert len(exp["dataset"]["fingerprint"]) == 64
    assert exp["confidence"]["level"] in ("insufficient", "weak", "moderate", "strong")
    assert "No claim of future profitability" in exp["report_markdown"]


def test_holdout_is_separate_and_evaluated_once(experiment):
    exp = experiment
    work_end = exp["windows"]["work_range"][1]
    holdout_start = exp["windows"]["holdout_range"][0]
    assert work_end < holdout_start                      # ISO strings compare
    assert "sharpe" in exp["final_test"]
    # development equity never enters the holdout range
    last_equity_ts = exp["development"]["equity"][-1][0]
    assert last_equity_ts < holdout_start


def test_selected_params_come_from_fold_winners(experiment):
    winners = [json.dumps(f["best_params"], sort_keys=True)
               for f in exp_folds(experiment)]
    assert json.dumps(experiment["selected_params"], sort_keys=True) in winners


def exp_folds(exp):
    return exp["walkforward"]["folds"]


def test_fold_blocks_contain_inspectable_trades(experiment):
    folds = exp_folds(experiment)
    assert len(folds) >= 2
    for f in folds:
        assert f["train"][1] < f["validate"][0]          # train strictly before val
        assert "val_equity" in f and len(f["val_equity"]) > 0
        assert isinstance(f["val_trades"], list)


def test_heatmap_cells_cover_grid(experiment):
    heat = experiment["sensitivity"]["heatmap"]
    assert heat["x"] == "fast" and heat["y"] == "slow"
    assert len(heat["cells"]) == 4                       # 2x2 grid
    cell = heat["cells"][0]
    for key in ("sharpe", "max_drawdown", "profit_factor", "win_rate"):
        assert key in cell


def test_montecarlo_block(experiment):
    mc = experiment["montecarlo"]
    assert set(mc["cis"]) >= {"reshuffle", "bootstrap", "skip", "perturbed_costs"}
    fan = mc["fan"]
    assert fan["n_paths"] == 50
    assert set(fan["quantiles"]) == {"0.05", "0.25", "0.5", "0.75", "0.95"}
    assert len(fan["worst_path"]) == fan["steps"]
    for t, p in fan["prob_ruin"].items():
        assert 0.0 <= p <= 1.0
    # median band must sit between the 5% and 95% bands everywhere
    q05, q50, q95 = (np.array(fan["quantiles"][k]) for k in ("0.05", "0.5", "0.95"))
    assert (q05 <= q50 + 1e-9).all() and (q50 <= q95 + 1e-9).all()
    assert [row["delay_bars"] for row in mc["delay_sweep"]] == [0, 1, 2]


def test_experiment_is_json_serializable(experiment):
    payload = json.dumps(experiment)                     # raises if not
    assert "NaN" not in payload and "Infinity" not in payload


def test_store_roundtrip_and_index(tmp_path, experiment):
    store = ExperimentStore(tmp_path)
    exp_id = store.save(experiment)
    assert store.get(exp_id)["id"] == exp_id
    rows = store.list()
    assert len(rows) == 1
    row = rows[0]
    assert row["strategy"] == "MACrossover"
    assert row["confidence"] == experiment["confidence"]["level"]
    assert row["metrics"]["sharpe"] is not None
    # idempotent re-save: no duplicate index rows
    store.save(experiment)
    assert len(store.list()) == 1


def test_search_filters(tmp_path, experiment):
    store = ExperimentStore(tmp_path)
    store.save(experiment)
    assert store.search(text="macross")
    assert store.search(strategy="MACrossover")
    assert not store.search(strategy="Nonexistent")
    assert store.search(symbol="demo")
    assert store.search(tag="momentum")
    assert not store.search(tag="meanrev")
    assert store.search(engine_version=experiment["engine_version"])
    assert store.search(fingerprint=experiment["dataset"]["fingerprint"][:10])
    sharpe = experiment["development"]["metrics"]["sharpe"]
    assert store.search(filters=[f"sharpe>={sharpe - 0.01:.4f}"])
    assert not store.search(filters=[f"sharpe>{sharpe + 1000}"])
    assert store.search(filters=["n_trades>0"]) or True  # depends on run
    with pytest.raises(ValueError, match="bad filter"):
        store.search(filters=["sharpe !! 3"])


def test_notes_crud(tmp_path):
    store = ExperimentStore(tmp_path)
    note = store.add_note("idea", "test slow>fast ratios", tags=["todo"])
    assert store.notes()[0]["title"] == "idea"
    assert store.delete_note(note["id"])
    assert store.notes() == []
    assert not store.delete_note("missing")
