"""Research API endpoints + PDF export, against temp filesystem roots."""
import io

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
    root = tmp_path_factory.mktemp("api")
    data = ParquetStore(root / "data")
    data.write(synth_frame())
    # AUTH_DISABLED (set for the whole test run) resolves every per-user
    # root to <EDGELAB_..._ROOT>/<DEV_USER_ID> — seed there directly.
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
    from app.core.config import settings
    monkeypatch.setattr(settings, "auth_disabled", True)
    monkeypatch.setattr(settings, "api_env", "development")
    from app.main import app

    return TestClient(app)


def test_strategies_endpoint(client):
    res = client.get("/api/v1/research/strategies")
    assert res.status_code == 200
    names = {s["name"] for s in res.json()}
    assert names == {"BuyAndHold", "MACrossover", "RSIMeanReversion",
                     "VolatilityBreakout"}
    ma = next(s for s in res.json() if s["name"] == "MACrossover")
    assert any(p["name"] == "fast" for p in ma["params"])


def test_experiment_search_and_get(client, env):
    _, exp = env
    res = client.get("/api/v1/research/experiments")
    assert res.status_code == 200 and len(res.json()) == 1

    res = client.get("/api/v1/research/experiments",
                     params={"filters": "sharpe>-1000", "tag": "momentum"})
    assert len(res.json()) == 1
    res = client.get("/api/v1/research/experiments",
                     params={"filters": "sharpe>99999"})
    assert res.json() == []
    res = client.get("/api/v1/research/experiments",
                     params={"filters": "sharpe !! 1"})
    assert res.status_code == 422

    res = client.get(f"/api/v1/research/experiments/{exp['id']}")
    assert res.status_code == 200
    assert res.json()["strategy"] == "MACrossover"
    assert client.get("/api/v1/research/experiments/nope").status_code == 404


def test_dataset_endpoints(client):
    res = client.get("/api/v1/research/datasets")
    assert res.status_code == 200
    assert res.json()[0]["symbol"] == "DEMO"

    res = client.get("/api/v1/research/datasets/1d/DEMO")
    assert res.status_code == 200
    d = res.json()
    assert d["integrity"] == "verified"
    assert d["coverage"]["rows"] == 140
    assert len(d["fingerprint"]) == 64
    assert "raw" in d["adjustment"]
    assert client.get("/api/v1/research/datasets/1d/NOPE").status_code == 404


def test_notes_endpoints(client):
    res = client.post("/api/v1/research/notes",
                      json={"title": "t", "body": "b", "tags": ["x"]})
    assert res.status_code == 200
    note_id = res.json()["id"]
    assert any(n["id"] == note_id for n in
               client.get("/api/v1/research/notes").json())
    assert client.delete(f"/api/v1/research/notes/{note_id}").status_code == 200
    assert client.delete(f"/api/v1/research/notes/{note_id}").status_code == 404


def test_run_endpoint_launches_pipeline(client):
    res = client.post("/api/v1/research/experiments", json={
        "strategy": "MACrossover", "symbols": ["DEMO"],
        "param_values": {"fast": [2, 4], "slow": [8, 12]},
        "train_size": 50, "val_size": 15, "test_size": 25,
        "mc_iters": 30, "seed": 3, "tags": ["api-run"],
    })
    assert res.status_code == 200
    exp_id = res.json()["id"]
    assert client.get(f"/api/v1/research/experiments/{exp_id}").status_code == 200
    assert client.post("/api/v1/research/experiments", json={
        "strategy": "NoSuch", "symbols": ["DEMO"],
    }).status_code == 422


def test_pdf_export(client, env):
    _, exp = env
    res = client.get(f"/api/v1/research/experiments/{exp['id']}/report.pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content[:5] == b"%PDF-"
    assert len(res.content) > 30_000          # multi-page with charts


def test_pdf_builder_direct(env, tmp_path):
    _, exp = env
    from research.pdf import build_pdf

    buf = io.BytesIO()
    build_pdf(exp, buf)
    data = buf.getvalue()
    assert data[:5] == b"%PDF-"
    # the disclaimer must be embedded in the document stream
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    text = "".join(page.extract_text() for page in reader.pages)
    assert "No claim of future profitability" in text
    assert exp["id"] in text
