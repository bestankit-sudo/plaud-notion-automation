from pathlib import Path

from app import paths


def test_state_dir_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_STATE_DIR", str(tmp_path / "st"))
    assert paths.state_dir() == tmp_path / "st"
    assert paths.notes_db() == tmp_path / "st" / "notes.db"
    assert paths.audio_dir() == tmp_path / "st" / "audio"


def test_state_dir_default_is_worker_state(monkeypatch):
    monkeypatch.delenv("WORKER_STATE_DIR", raising=False)
    sd = paths.state_dir()
    assert sd.name == "state"
    assert sd.parent.name == "worker"
    assert paths.notes_db() == sd / "notes.db"
