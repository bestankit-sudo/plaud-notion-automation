import pytest
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WORKER_ENV_FILE", str(tmp_path / ".env"))
    from app.server import app
    return TestClient(app)


def test_root_serves_wizard_when_unconfigured(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/")
    assert r.status_code == 200
    assert "Setup" in r.text  # wizard page marker
    assert "/api/setup/models" in r.text or "wizard.js" in r.text


def test_root_serves_viewer_when_configured(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.post("/api/setup/config", json={
        "destination": "local", "summarizer_provider": "anthropic",
        "summarizer_model": "claude-opus-4-8",
    })
    r = client.get("/")
    assert r.status_code == 200
    # viewer markup (from Plan 2a index.html): the meetings list container
    assert 'id="list"' in r.text


def test_wizard_js_served(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/static/wizard.js")
    assert r.status_code == 200
    assert "/api/setup/config" in r.text
    assert "/api/setup/secrets" in r.text
