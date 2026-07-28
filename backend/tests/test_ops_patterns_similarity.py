"""Pattern library: feature extraction, recorder wired to signal/fill
lifecycle, filesystem persistence, search. Similarity: kNN mechanics,
descriptive framing."""
import dataclasses
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from engine.data.schema_types import Timeframe
from engine.types import Fill, Side
from ops.deployments import deployment_from_experiment
from ops.execution import Ledger
from ops.patterns import (
    NUMERIC_FEATURES,
    PatternRecord,
    PatternRecorder,
    PatternStore,
    extract_features_from_frame,
)
from ops.risk import MarketState, SignalCandidate
from ops.similarity import find_similar

from tests.ops_fixtures import ops_env  # noqa: F401


def synthetic_frame(n=40, seed=1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts0 = datetime(2026, 1, 1, 21, 0, tzinfo=UTC)
    closes = 100 + np.cumsum(rng.normal(0, 1, n))
    rows = []
    for i in range(n):
        c = closes[i]
        o = c + rng.normal(0, 0.3)
        h = max(o, c) + abs(rng.normal(0, 0.3))
        low = min(o, c) - abs(rng.normal(0, 0.3))
        rows.append({"ts": ts0 + timedelta(days=i), "open": o, "high": h,
                     "low": low, "close": c,
                     "volume": float(rng.integers(1000, 5000))})
    return pd.DataFrame(rows)


def test_extract_features_shape_and_bounds():
    frame = synthetic_frame(n=40)
    feats = extract_features_from_frame(
        frame, quote={"spread_bps": 5.0}, dollar_volume=1e6, sector="tech")
    assert feats["sector"] == "tech"
    assert feats["spread_bps"] == 5.0
    assert feats["vol_regime"] is not None
    assert feats["trend_regime"] is not None
    assert 0.0 <= feats["close_range_pct"] <= 1.0
    assert feats["atr_pct"] > 0
    assert feats["breadth"] is None and feats["vwap_rel"] is None    # honest gaps


def test_extract_features_handles_short_history():
    frame = synthetic_frame(n=3)
    feats = extract_features_from_frame(frame)
    assert feats["vol_regime"] is None
    assert feats["atr_pct"] is None
    assert feats["trailing_vol"] is None


def test_recorder_on_signal_and_on_fill_resolve_outcome(tmp_path, ops_env):
    exp = ops_env["experiment"]
    dep = deployment_from_experiment(exp)
    dep = dataclasses.replace(dep, id="")
    store = PatternStore(tmp_path)
    recorder = PatternRecorder(store)

    ts1 = datetime(2026, 1, 5, 21, 0, tzinfo=UTC)
    candidate = SignalCandidate(
        deployment_id=dep.id, strategy=dep.strategy, symbol="DEMO",
        side=Side.BUY, qty=10, ts=ts1, received_at=ts1,
        features={"atr_pct": 0.02, "rvol": 1.2},
    )
    record = recorder.on_signal(dep, candidate, order_id=1)
    assert record.outcome is None
    loaded = store.all()
    assert len(loaded) == 1 and loaded[0].outcome is None

    ledger = Ledger(initial_cash=100_000)
    ledger.apply_fill(Fill(order_id=1, symbol="DEMO", side=Side.BUY, qty=10,
                           price=100.0, fees=1.0, ts=ts1))
    recorder.on_fill(dep, ledger.round_trips[-1] if ledger.round_trips else None, ledger)
    # not closed yet -> still unresolved
    assert store.all()[0].outcome is None

    ts2 = ts1 + timedelta(days=1)
    ledger.apply_fill(Fill(order_id=2, symbol="DEMO", side=Side.SELL, qty=10,
                           price=105.0, fees=1.0, ts=ts2))
    recorder.on_fill(dep, None, ledger)
    resolved = store.all()[0]
    assert resolved.outcome is not None
    assert resolved.outcome["win"] is True
    assert resolved.outcome["net_pnl"] > 0


def test_pattern_store_search_filters(tmp_path):
    store = PatternStore(tmp_path)
    for i, (vol, out) in enumerate([("low_vol", True), ("high_vol", False),
                                    ("low_vol", False)]):
        store.save(PatternRecord(
            id=f"r{i}", deployment_id="d1", strategy="MACrossover",
            symbol="DEMO", side="buy", ts=f"2026-01-0{i+1}T21:00:00+00:00",
            order_id=i, features={"vol_regime": vol, "trend_regime": "up"},
            outcome={"win": out, "net_pnl": 1.0 if out else -1.0},
        ))
    assert len(store.search(vol_regime="low_vol")) == 2
    assert len(store.search(outcome="win")) == 1
    assert len(store.search(outcome="loss")) == 2
    assert len(store.search(strategy="Nope")) == 0


# ── similarity ───────────────────────────────────────────────────────
def _library(n=30, seed=0) -> list[PatternRecord]:
    rng = np.random.default_rng(seed)
    records = []
    for i in range(n):
        atr = float(rng.uniform(0.005, 0.05))
        rvol = float(rng.uniform(0.5, 3.0))
        win = atr < 0.02          # deterministic relationship for the test
        records.append(PatternRecord(
            id=f"p{i}", deployment_id="d1", strategy="MACrossover",
            symbol="DEMO", side="buy", ts=f"2026-01-{(i % 28) + 1:02d}T21:00:00+00:00",
            order_id=i, features={"atr_pct": atr, "rvol": rvol},
            outcome={"win": win, "net_pnl": 10.0 if win else -8.0},
        ))
    return records


def test_similarity_returns_neighbors_and_distribution():
    library = _library()
    result = find_similar(library, {"atr_pct": 0.01, "rvol": 1.0}, k=5)
    assert result.features_used == ["atr_pct", "rvol"]
    assert len(result.neighbors) == 5
    # nearest neighbors should skew toward the low-atr/win cluster
    assert result.outcome_distribution["n_resolved"] == 5
    assert result.outcome_distribution["win_rate"] is not None
    assert "descriptive" in result.note.lower()
    assert "not predictive" in result.note.lower()


def test_similarity_excludes_zero_variance_and_missing_features():
    library = [
        PatternRecord(id="a", deployment_id="d", strategy="S", symbol="X",
                      side="buy", ts="2026-01-01T21:00:00+00:00", order_id=1,
                      features={"atr_pct": 0.01, "rvol": None}, outcome=None),
        PatternRecord(id="b", deployment_id="d", strategy="S", symbol="X",
                      side="buy", ts="2026-01-02T21:00:00+00:00", order_id=2,
                      features={"atr_pct": 0.01, "rvol": None}, outcome=None),
    ]
    # atr_pct has zero variance across the library -> excluded
    result = find_similar(library, {"atr_pct": 0.015, "rvol": 1.0}, k=5)
    assert "atr_pct" not in result.features_used
    assert "rvol" not in result.features_used   # missing in the library
    assert result.neighbors == []


def test_similarity_empty_library():
    result = find_similar([], {"atr_pct": 0.01}, k=5)
    assert result.neighbors == []
    assert result.outcome_distribution == {"n": 0}
