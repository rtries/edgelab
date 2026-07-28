"""Smoke test: app imports and health endpoint responds."""
from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_api_ok() -> None:
    client = TestClient(app)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["api"] == "ok"
