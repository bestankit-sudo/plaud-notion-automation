import pytest
from fastapi.testclient import TestClient

import app.setup_api as setup_api


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WORKER_ENV_FILE", str(tmp_path / ".env"))
    from app.server import app
    return TestClient(app)


def test_riffado_test_ok(client, monkeypatch):
    captured = {}

    def fake(base_url, api_key):
        captured.update(base_url=base_url, api_key=api_key)
        return {"ok": True, "detail": "ok"}

    monkeypatch.setattr(setup_api.conn_check, "check_riffado", fake)
    r = client.post("/api/setup/test/riffado", json={"base_url": "http://x", "api_key": "k"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert captured == {"base_url": "http://x", "api_key": "k"}


def test_anthropic_test_failure_passthrough(client, monkeypatch):
    monkeypatch.setattr(setup_api.conn_check, "check_anthropic",
                        lambda key: {"ok": False, "detail": "authentication failed (check the key/token)"})
    r = client.post("/api/setup/test/anthropic", json={"key": "bad"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and "auth" in body["detail"].lower()


def test_each_service_endpoint_wired(client, monkeypatch):
    for svc, field in [("notion", "token"), ("openai", "key"), ("hf", "token")]:
        monkeypatch.setattr(setup_api.conn_check, f"check_{svc}",
                            lambda v: {"ok": True, "detail": "ok"})
        r = client.post(f"/api/setup/test/{svc}", json={field: "v"})
        assert r.status_code == 200 and r.json()["ok"] is True
