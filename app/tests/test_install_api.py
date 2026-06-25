import pytest
from fastapi.testclient import TestClient

import app.install_api as install_api
from app.install.runner import FakeRunner


def fake_run(mapping):
    return lambda argv: mapping.get(tuple(argv), (127, ""))


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("RIFFADO_ENV_FILE", str(tmp_path / "riffado.env"))
    from app.server import app
    return TestClient(app)


def test_status_lists_steps(client, monkeypatch):
    monkeypatch.setattr(install_api, "_run", fake_run({("/opt/homebrew/bin/brew", "--version"): (0, "Homebrew")}))
    body = client.get("/api/install/status").json()
    ids = [s["id"] for s in body["steps"]]
    assert ids[0] == "brew" and "launchd" in ids
    brew = next(s for s in body["steps"] if s["id"] == "brew")
    assert brew["done"] is True


def test_stream_runs_step_and_emits_frames(client, monkeypatch):
    # fake machine: brew present, ffmpeg NOT installed (so the step runs)
    run = fake_run({
        ("/opt/homebrew/bin/brew", "--version"): (0, "Homebrew"),
        ("/opt/homebrew/bin/brew", "--prefix"): (0, "/opt/homebrew\n"),
        ("ffmpeg", "-version"): (1, "not found"),
    })
    monkeypatch.setattr(install_api, "_run", run)
    monkeypatch.setattr(install_api, "_runner", FakeRunner({
        ("/opt/homebrew/bin/brew", "install", "ffmpeg"): (0, ["==> Pouring ffmpeg", "ok"]),
    }))
    r = client.get("/api/install/stream/ffmpeg")
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert "event: log" in r.text
    assert "install ffmpeg" in r.text  # the $ <cmd> line
    assert "==> Pouring ffmpeg" in r.text
    assert "event: done" in r.text


def test_stream_unknown_step_404(client):
    assert client.get("/api/install/stream/nope").status_code == 404


def test_stream_skips_when_already_done(client, monkeypatch):
    # ffmpeg already installed -> skip without running the runner
    run = fake_run({
        ("/opt/homebrew/bin/brew", "--version"): (0, "Homebrew"),
        ("ffmpeg", "-version"): (0, "ffmpeg version 7"),
    })
    monkeypatch.setattr(install_api, "_run", run)
    fr = FakeRunner({})
    monkeypatch.setattr(install_api, "_runner", fr)
    r = client.get("/api/install/stream/ffmpeg")
    assert "event: skip" in r.text and "event: done" in r.text
    assert fr.calls == []  # nothing ran


def test_riffado_secrets_written(client, tmp_path):
    r = client.post("/api/install/riffado/secrets")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert set(body["written"]) == {"BETTER_AUTH_SECRET", "ENCRYPTION_KEY", "POSTGRES_PASSWORD"}
    assert (tmp_path / "riffado.env").exists()


def test_launchd_render(client, monkeypatch):
    monkeypatch.setattr(install_api, "_run", fake_run({("/opt/homebrew/bin/brew", "--prefix"): (0, "/opt/homebrew\n")}))
    body = client.get("/api/install/launchd").json()
    assert "com.example.plaudautomation.web" in body["web"]
    assert ".venv-ml/bin/python" in body["worker"]
    assert body["load_argv"][0][0] == "launchctl"
    assert isinstance(body["port_in_use"], bool)
