import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    state = tmp_path / "state"
    monkeypatch.setenv("WORKER_STATE_DIR", str(state))
    monkeypatch.setenv("WORKER_ENV_FILE", str(tmp_path / ".env"))
    from app.server import app
    return TestClient(app)


def test_status_unconfigured_then_configured(client, tmp_path):
    assert client.get("/api/setup/status").json()["configured"] is False
    r = client.post("/api/setup/config", json={
        "destination": "local", "summarizer_provider": "anthropic",
        "summarizer_model": "claude-opus-4-8", "speaker_naming_enabled": True,
    })
    assert r.status_code == 200 and r.json()["ok"] is True
    st = client.get("/api/setup/status").json()
    assert st["configured"] is True
    assert st["destination"] == "local"
    assert st["summarizer_provider"] == "anthropic"
    assert st["summarizer_model"] == "claude-opus-4-8"


def test_models_endpoint_returns_costed_catalog(client):
    body = client.get("/api/setup/models").json()
    assert body["token_profile"]["input_tokens"] == 8000
    models = {m["model"]: m for m in body["models"]}
    assert "claude-opus-4-8" in models
    assert models["claude-opus-4-8"]["cost"]["per_100"] == 7.75
    # constraint: no Opus 4.7/4.6 offered
    assert "claude-opus-4-7" not in models and "claude-opus-4-6" not in models


def test_secrets_written_to_env_file(client, tmp_path):
    r = client.post("/api/setup/secrets", json={"values": {
        "ANTHROPIC_API_KEY": "ak-test", "HF_TOKEN": "hf-test",
    }})
    assert r.status_code == 200
    env_text = (tmp_path / ".env").read_text()
    assert "ANTHROPIC_API_KEY=ak-test" in env_text
    assert "HF_TOKEN=hf-test" in env_text


def test_secrets_rejects_unknown_key(client):
    r = client.post("/api/setup/secrets", json={"values": {"EVIL_KEY": "x"}})
    assert r.status_code == 400


def test_secrets_mixed_batch_rejects_atomically(client, tmp_path):
    r = client.post("/api/setup/secrets", json={"values": {
        "ANTHROPIC_API_KEY": "ok", "EVIL_KEY": "x",
    }})
    assert r.status_code == 400
    env = tmp_path / ".env"
    assert (not env.exists()) or "ANTHROPIC_API_KEY" not in env.read_text()


def test_secrets_rejects_newline_value(client, tmp_path):
    r = client.post("/api/setup/secrets", json={"values": {"ANTHROPIC_API_KEY": "ab\ncd"}})
    assert r.status_code == 400
    env = tmp_path / ".env"
    assert (not env.exists()) or "ANTHROPIC_API_KEY" not in env.read_text()
