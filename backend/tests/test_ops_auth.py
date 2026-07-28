"""Auth: unauthenticated requests are rejected, invalid tokens are
rejected, and two different users never see each other's deployments or
experiments. This is the actual safety property the multi-tenant
launch depends on."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


SECRET = "test-jwt-secret-for-auth-tests"


def make_token(user_id: str, secret: str = SECRET, expired: bool = False) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": f"{user_id}@example.com",
        "aud": "authenticated",
        "iat": now,
        "exp": now - 10 if expired else now + 3600,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGELAB_RESEARCH_ROOT", str(tmp_path / "research"))
    monkeypatch.setenv("EDGELAB_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("EDGELAB_OPS_ROOT", str(tmp_path / "ops"))
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "supabase_jwt_secret", SECRET)
    from app.main import app

    return TestClient(app)


def test_no_token_rejected(client):
    res = client.get("/api/v1/ops/deployments")
    assert res.status_code == 401


def test_garbage_token_rejected(client):
    res = client.get("/api/v1/ops/deployments",
                     headers={"Authorization": "Bearer not-a-real-token"})
    assert res.status_code == 401


def test_wrong_secret_rejected(client):
    token = make_token("alice", secret="wrong-secret")
    res = client.get("/api/v1/ops/deployments",
                     headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


def test_expired_token_rejected(client):
    token = make_token("alice", expired=True)
    res = client.get("/api/v1/ops/deployments",
                     headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


def test_valid_token_accepted(client):
    token = make_token("alice")
    res = client.get("/api/v1/ops/deployments",
                     headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json() == []


def test_users_do_not_see_each_others_deployments(client, tmp_path):
    import dataclasses

    from engine.data.store import ParquetStore
    from engine.strategies.examples import MACrossover
    from ops.deployments import RiskPolicy, deployment_from_experiment
    from research.pipeline import run_experiment
    from research.store import ExperimentStore

    from tests.test_research_pipeline import synth_frame

    alice, bob = make_token("alice"), make_token("bob")
    alice_headers = {"Authorization": f"Bearer {alice}"}
    bob_headers = {"Authorization": f"Bearer {bob}"}

    # Seed an experiment directly into alice's namespace only.
    data = ParquetStore(tmp_path / "data")
    data.write(synth_frame(symbol="DEMO", n=140, seed=5))
    alice_research_root = tmp_path / "research" / "alice"
    exp = run_experiment(
        data_store=data, strategy_cls=MACrossover, symbols=["DEMO"],
        param_values={"fast": [2, 4], "slow": [8, 12]},
        train_size=50, val_size=15, test_size=25,
        mc_iters=20, fan_paths=20, cost_iters=2, seed=11,
        registry_path=alice_research_root / "registry.json",
    )
    ExperimentStore(alice_research_root).save(exp)

    # Alice can see her own experiment; Bob can't.
    res = client.get("/api/v1/research/experiments", headers=alice_headers)
    assert len(res.json()) == 1
    res = client.get("/api/v1/research/experiments", headers=bob_headers)
    assert len(res.json()) == 0

    # Alice deploys it; it shows up only for Alice.
    dep = client.post("/api/v1/ops/deployments",
                      json={"experiment_id": exp["id"]},
                      headers=alice_headers).json()
    res = client.get("/api/v1/ops/deployments", headers=alice_headers)
    assert len(res.json()) == 1
    res = client.get("/api/v1/ops/deployments", headers=bob_headers)
    assert res.json() == []

    # Bob cannot fetch Alice's deployment by id, even knowing it.
    res = client.get(f"/api/v1/ops/deployments/{dep['id']}", headers=bob_headers)
    assert res.status_code == 404

    # Bob's emergency stop never touches Alice's.
    client.post("/api/v1/ops/emergency-stop/on", headers=bob_headers)
    assert client.get("/api/v1/ops/emergency-stop",
                      headers=bob_headers).json()["emergency_stop"] is True
    assert client.get("/api/v1/ops/emergency-stop",
                      headers=alice_headers).json()["emergency_stop"] is False
