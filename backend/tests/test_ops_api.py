"""Ops API: deployment lifecycle, paper runs, health/drift, patterns,
emergency stop, and nightly research — against temp filesystem roots."""
import pytest
from fastapi.testclient import TestClient

from engine.data.store import ParquetStore
from engine.strategies.examples import MACrossover
from research.pipeline import run_experiment
from research.store import ExperimentStore

from app.core.auth import DEV_USER_ID
from tests.test_research_pipeline import synth_frame


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("ops_api")
    data = ParquetStore(root / "data")
    data.write(synth_frame(symbol="DEMO", n=140, seed=5))
    # AUTH_DISABLED (set below) resolves every per-user root to
    # <EDGELAB_..._ROOT>/<DEV_USER_ID> — seed there directly.
    user_root = root / "research" / DEV_USER_ID
    exp = run_experiment(
        data_store=data, strategy_cls=MACrossover, symbols=["DEMO"],
        param_values={"fast": [2, 4], "slow": [8, 12]},
        train_size=50, val_size=15, test_size=25,
        mc_iters=40, fan_paths=40, cost_iters=4, seed=11,
        tags=["momentum"], registry_path=user_root / "registry.json",
    )
    ExperimentStore(user_root).save(exp)
    return root, exp


@pytest.fixture()
def client(env, monkeypatch):
    root, _ = env
    monkeypatch.setenv("EDGELAB_RESEARCH_ROOT", str(root / "research"))
    monkeypatch.setenv("EDGELAB_DATA_ROOT", str(root / "data"))
    monkeypatch.setenv("EDGELAB_OPS_ROOT", str(root / "ops"))
    from app.core.config import settings
    monkeypatch.setattr(settings, "auth_disabled", True)
    monkeypatch.setattr(settings, "api_env", "development")
    from app.main import app

    return TestClient(app)


def test_deployment_lifecycle_via_api(client, env):
    _, exp = env
    res = client.post("/api/v1/ops/deployments",
                      json={"experiment_id": exp["id"]})
    assert res.status_code == 200
    dep = res.json()
    assert dep["status"] == "proposed"
    dep_id = dep["id"]

    res = client.get(f"/api/v1/ops/deployments/{dep_id}")
    assert res.status_code == 200
    assert res.json()["id"] == dep_id

    # Fixture experiment is 'insufficient' -> paper is correctly refused.
    res = client.post(f"/api/v1/ops/deployments/{dep_id}/transition",
                      json={"to": "paper", "reason": "try"})
    assert res.status_code == 422
    assert "cannot enter paper" in res.json()["detail"]

    res = client.post(f"/api/v1/ops/deployments/{dep_id}/transition",
                      json={"to": "rejected", "reason": "insufficient evidence"})
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"

    listed = client.get("/api/v1/ops/deployments").json()
    assert any(d["id"] == dep_id and d["status"] == "rejected" for d in listed)


def test_deployment_not_found(client):
    res = client.get("/api/v1/ops/deployments/doesnotexist")
    assert res.status_code == 404


def test_paper_run_requires_paper_or_live_status(client, env):
    _, exp = env
    dep = client.post("/api/v1/ops/deployments",
                      json={"experiment_id": exp["id"]}).json()
    res = client.post(f"/api/v1/ops/deployments/{dep['id']}/paper/run", json={})
    assert res.status_code == 422
    assert "require" in res.json()["detail"]


def test_paper_run_and_health_and_drift(client, env, monkeypatch):
    _, exp = env
    # Bypass the confidence gate honestly, the way the deployment tests do:
    # build via API then patch status directly through the transition
    # endpoint isn't possible for 'insufficient' -> so exercise via a
    # forced-strong deployment written directly to the store, mirroring
    # what a real 'strong' experiment would allow through the API.
    import dataclasses
    from ops.deployments import RiskPolicy, deployment_from_experiment

    dep = deployment_from_experiment(
        exp,
        risk=RiskPolicy(sizing_mode="fixed_qty", sizing_value=10,
                        min_dollar_volume=0.0, max_spread_bps=1e9,
                        max_position_pct=100.0, max_gross_exposure_pct=100.0,
                        daily_loss_limit_pct=1.0),
    )
    dep = dataclasses.replace(dep, confidence="strong", id="")
    from app.api.v1.ops import deployment_store
    deployment_store(DEV_USER_ID).save(dep)
    dep_id = dep.id
    res = client.post(f"/api/v1/ops/deployments/{dep_id}/transition",
                      json={"to": "paper", "reason": "validated"})
    assert res.status_code == 200

    run_res = client.post(f"/api/v1/ops/deployments/{dep_id}/paper/run",
                          json={"checkpoint": False})
    assert run_res.status_code == 200
    summary = run_res.json()
    assert summary["deployment_id"] == dep_id
    assert summary["processed_events"] > 0

    logs = client.get(f"/api/v1/ops/deployments/{dep_id}/paper/logs")
    assert logs.status_code == 200
    assert len(logs.json()) > 0

    health = client.get(f"/api/v1/ops/deployments/{dep_id}/health")
    assert health.status_code == 200
    assert "rows" in health.json()

    drift = client.get(f"/api/v1/ops/deployments/{dep_id}/drift")
    assert drift.status_code == 200
    assert drift.json()["status"] in ("healthy", "weakening", "unstable",
                                      "retire_recommended")


def test_emergency_stop_toggle(client):
    assert client.get("/api/v1/ops/emergency-stop").json()["emergency_stop"] is False
    res = client.post("/api/v1/ops/emergency-stop/on")
    assert res.json()["emergency_stop"] is True
    assert client.get("/api/v1/ops/emergency-stop").json()["emergency_stop"] is True
    res = client.post("/api/v1/ops/emergency-stop/off")
    assert res.json()["emergency_stop"] is False


def test_patterns_search_and_similarity_no_match(client):
    res = client.get("/api/v1/ops/patterns", params={"symbol": "NOPE"})
    assert res.status_code == 200 and res.json() == []
    res = client.post("/api/v1/ops/patterns/similar",
                      json={"features": {"no_such_feature": 1.0}, "k": 5})
    assert res.status_code == 200
    assert res.json()["neighbors"] == []
    assert "descriptive" in res.json()["note"].lower()


def test_nightly_and_reports(client):
    res = client.post("/api/v1/ops/research/nightly",
                      json={"symbols": ["DEMO"], "budget": 2, "seed": 3})
    assert res.status_code == 200
    body = res.json()
    assert body["tallies"]["tested"] == 2

    reports = client.get("/api/v1/ops/research/reports")
    assert reports.status_code == 200
    assert len(reports.json()) >= 1

    latest = client.get("/api/v1/ops/research/reports/latest")
    assert latest.status_code == 200
    assert latest.json()["tallies"]["tested"] == 2


def test_research_queue_previews_without_running(client):
    res = client.get("/api/v1/ops/research/queue", params={"symbols": ["DEMO"]})
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_morning_dashboard_aggregate(client):
    res = client.get("/api/v1/ops/morning")
    assert res.status_code == 200
    body = res.json()
    assert "deployments" in body
    assert "deployment_alerts" in body
    assert "latest_research" in body
    assert "emergency_stop" in body
