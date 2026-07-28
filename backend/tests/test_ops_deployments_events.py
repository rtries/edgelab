"""Deployment manager: immutability, integrity, lifecycle gates.
Event layer: replay determinism, timestamps, normalization."""
import dataclasses
import json

import pytest

from engine.data.schema_types import Timeframe
from ops.deployments import (
    Deployment,
    DeploymentStore,
    RiskPolicy,
    TransitionError,
    deployment_from_experiment,
    flag_for_review,
    transition,
)
from ops.events import AlpacaFeed, MarketEvent, ReplayFeed, SimulatedLiveFeed

from tests.ops_fixtures import ops_env  # noqa: F401


@pytest.fixture()
def deployment(ops_env):
    return deployment_from_experiment(ops_env["experiment"])


def test_deployment_carries_full_provenance(deployment, ops_env):
    exp = ops_env["experiment"]
    assert deployment.experiment_id == exp["id"]
    assert deployment.strategy_code_hash == exp["strategy_code_hash"]
    assert deployment.dataset_fingerprint == exp["dataset"]["fingerprint"]
    assert deployment.params == exp["selected_params"]
    assert deployment.engine_version == exp["engine_version"]
    assert deployment.status == "proposed"
    assert len(deployment.id) == 12


def test_config_change_means_new_deployment(ops_env):
    a = deployment_from_experiment(ops_env["experiment"])
    b = deployment_from_experiment(
        ops_env["experiment"], risk=RiskPolicy(sizing_value=0.2)
    )
    # created_at differs too, but the point stands: different config,
    # different identity.
    assert a.id != b.id


def test_integrity_check_catches_tampering(deployment):
    assert deployment.verify_integrity()
    deployment.params["fast"] = 999           # mutate config after creation
    assert not deployment.verify_integrity()


def test_store_refuses_tampered_configs(tmp_path, deployment):
    store = DeploymentStore(tmp_path)
    store.save(deployment)
    raw_path = tmp_path / "deployments" / f"{deployment.id}.json"
    raw = json.loads(raw_path.read_text())
    raw["params"]["fast"] = 999
    raw_path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="tampered"):
        store.get(deployment.id)


def test_lifecycle_gates(ops_env):
    dep = deployment_from_experiment(ops_env["experiment"])
    # Fixture experiment is 'insufficient' on random data — paper is refused.
    assert dep.confidence == "insufficient"
    with pytest.raises(TransitionError, match="cannot enter paper"):
        transition(dep, "paper", "trying anyway")
    # Rejection is always available and recorded.
    transition(dep, "rejected", "confidence insufficient")
    assert dep.status == "rejected"
    assert dep.status_history[-1]["reason"] == "confidence insufficient"
    with pytest.raises(TransitionError, match="cannot go"):
        transition(dep, "paper", "from rejected")


def test_lifecycle_happy_path_with_forced_confidence(ops_env):
    dep = deployment_from_experiment(ops_env["experiment"])
    # Simulate a strong experiment via a fresh config (new id, honestly).
    dep = dataclasses.replace(dep, confidence="strong", id="")
    transition(dep, "paper", "validated")
    assert dep.status == "paper"
    with pytest.raises(TransitionError, match="paper evidence"):
        transition(dep, "live", "no evidence yet")
    with pytest.raises(TransitionError, match="paper evidence"):
        transition(dep, "live", "too few", paper_evidence={"n_trades": 3, "health": "healthy"})
    transition(dep, "live", "proved out",
               paper_evidence={"n_trades": 25, "health": "healthy"})
    assert dep.status == "live"
    assert dep.status_history[-1]["paper_evidence"]["n_trades"] == 25
    transition(dep, "review", "drift flag")
    transition(dep, "retired", "edge gone")
    assert dep.status == "retired"


def test_moderate_confidence_cannot_go_live(ops_env):
    dep = deployment_from_experiment(ops_env["experiment"])
    dep = dataclasses.replace(dep, confidence="moderate", id="")
    transition(dep, "paper", "ok for paper")
    with pytest.raises(TransitionError, match="cannot go live"):
        transition(dep, "live", "nope",
                   paper_evidence={"n_trades": 100, "health": "healthy"})


def test_review_flag_never_disables(ops_env):
    dep = deployment_from_experiment(ops_env["experiment"])
    dep = dataclasses.replace(dep, confidence="strong", id="")
    transition(dep, "paper", "validated")
    flag_for_review(dep, [{"trigger": "win_rate_collapse", "detail": "..."}])
    assert dep.status == "paper"              # status unchanged
    assert dep.review_required
    assert dep.review_evidence[0]["trigger"] == "win_rate_collapse"


def test_store_roundtrip_and_index(tmp_path, deployment):
    store = DeploymentStore(tmp_path)
    dep_id = store.save(deployment)
    loaded = store.get(dep_id)
    assert loaded.to_dict() == deployment.to_dict()
    rows = store.list()
    assert rows[0]["id"] == dep_id and rows[0]["status"] == "proposed"


# ── events ────────────────────────────────────────────────────────────
def test_replay_feed_deterministic_and_ordered(ops_env):
    feed = ReplayFeed(ops_env["data_store"], ["DEMO"], Timeframe.D1)
    a = list(feed.events())
    b = list(feed.events())
    assert [e.to_dict() for e in a] == [e.to_dict() for e in b]
    assert len(a) == 140
    assert all(e.kind == "bar" for e in a)
    assert all(a[i].ts <= a[i + 1].ts for i in range(len(a) - 1))
    # replay convention: received_at == ts
    assert all(e.received_at == e.ts for e in a)
    assert set(a[0].data) == {"open", "high", "low", "close", "volume"}


def test_simulated_live_feed_seeded_latency(ops_env):
    replay = ReplayFeed(ops_env["data_store"], ["DEMO"], Timeframe.D1)
    sim = SimulatedLiveFeed(replay, seed=4)
    a = list(sim.events())
    b = list(SimulatedLiveFeed(replay, seed=4).events())
    c = list(SimulatedLiveFeed(replay, seed=5).events())
    assert [e.to_dict() for e in a] == [e.to_dict() for e in b]
    assert [e.to_dict() for e in a] != [e.to_dict() for e in c]
    # quote precedes bar per underlying bar; latency separates the stamps
    assert a[0].kind == "quote" and a[1].kind == "bar"
    assert all(e.received_at > e.ts for e in a)
    quote = a[0]
    assert quote.data["bid"] < quote.data["ask"]


def test_alpaca_feed_normalizes_with_fake_transport():
    class FakeTransport:
        def messages(self):
            yield {"T": "b", "S": "SPY", "t": "2026-01-05T21:00:00+00:00",
                   "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1000}
            yield {"T": "q", "S": "SPY", "t": "2026-01-05T21:00:01+00:00",
                   "bp": 1.49, "ap": 1.51}
            yield {"T": "??", "S": "SPY"}          # unknown kinds dropped

    from datetime import UTC, datetime

    fixed = datetime(2026, 1, 5, 21, 0, 5, tzinfo=UTC)
    events = list(AlpacaFeed(FakeTransport(), clock=lambda: fixed).events())
    assert len(events) == 2
    bar, quote = events
    assert bar.kind == "bar" and bar.data["close"] == 1.5
    assert bar.received_at == fixed               # ingest time stamped
    assert quote.kind == "quote"
    assert quote.data["spread_bps"] == pytest.approx(
        (1.51 - 1.49) / 1.50 * 1e4
    )
