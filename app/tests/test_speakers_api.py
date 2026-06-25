import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def state(tmp_path, monkeypatch):
    s = tmp_path / "state"
    (s / "diar_full").mkdir(parents=True)
    (s / "transcripts").mkdir(parents=True)
    monkeypatch.setenv("WORKER_STATE_DIR", str(s))
    return s


def _seed_meeting(s, rid):
    e0 = [1.0] + [0.0] * 255
    e1 = [0.0, 1.0] + [0.0] * 254
    (s / "diar_full" / f"{rid}.json").write_text(json.dumps({
        "turns": [{"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
                  {"start": 3.0, "end": 4.0, "speaker": "SPEAKER_01"}],
        "embeddings": {"SPEAKER_00": e0, "SPEAKER_01": e1}}))
    (s / "transcripts" / f"{rid}.json").write_text(json.dumps({
        "language": "en", "text": "x",
        "segments": [{"start": 0.0, "end": 3.0, "text": "hello"},
                     {"start": 3.0, "end": 4.0, "text": "bye"}]}))


def _client(s):
    from plaud_worker.voiceprints import VoiceprintStore
    st = VoiceprintStore(s / "voiceprints.db")
    st.enroll("Sam Rivers", np.array([1.0] + [0.0] * 255, dtype=np.float32))
    st.close()
    from app.server import app
    return TestClient(app)


def test_list_speakers(state):
    _seed_meeting(state, "rec1")
    c = _client(state)
    body = c.get("/api/speakers").json()
    assert body["speakers"][0]["name"] == "Sam Rivers"
    assert body["speakers"][0]["samples"] == 1


def test_meeting_speakers(state):
    _seed_meeting(state, "rec1")
    c = _client(state)
    body = c.get("/api/meetings/rec1/speakers").json()
    assert body["threshold"] == 0.75
    byl = {s["label"]: s for s in body["speakers"]}
    assert byl["SPEAKER_00"]["name"] == "Sam Rivers" and byl["SPEAKER_00"]["enrolled"] is True
    assert byl["SPEAKER_01"]["display"] == "Guest 1" and byl["SPEAKER_01"]["name"] is None


def test_meeting_speakers_missing_cache_empty(state):
    c = _client(state)
    body = c.get("/api/meetings/ghost/speakers").json()
    assert body["speakers"] == []


def test_gated_off(state, monkeypatch):
    (state / "config.json").write_text(json.dumps({"speaker_naming_enabled": False}))
    c = _client(state)
    assert c.get("/api/speakers").status_code == 404
    assert c.get("/api/meetings/rec1/speakers").status_code == 404
