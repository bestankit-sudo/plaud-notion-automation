from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from plaud_worker.models import ActionItem, Attendee, Meeting, Section, TranscriptTurn
from plaud_worker.notes_store import NotesStore


@pytest.fixture
def client(monkeypatch, tmp_path):
    state = tmp_path / "state"
    (state / "audio").mkdir(parents=True)
    monkeypatch.setenv("WORKER_STATE_DIR", str(state))
    # seed one meeting + its audio file
    store = NotesStore(state / "notes.db")
    store.upsert(
        Meeting(
            recording_id="rec-1",
            title="Patent Strategy",
            recorded_at=datetime(2026, 6, 2, 21, 33, tzinfo=timezone.utc),
            duration_ms=1634000,
            audio_path="/abs/rec-1.mp3",
            overview=["Filed the provisional"],
            sections=[Section("Next steps", ["draft claims"])],
            action_items=[ActionItem("Sam", "Send the spec", "by Fri")],
            attendees=[Attendee("Sam")],
            transcript=[TranscriptTurn("Sam", "hello")],
        ),
        audio_rel_path="rec-1.mp3",
    )
    store.close()
    (state / "audio" / "rec-1.mp3").write_bytes(b"ID3fake-mp3-bytes")
    from app.server import app
    return TestClient(app)


def test_list_meetings(client):
    r = client.get("/api/meetings")
    assert r.status_code == 200
    body = r.json()
    assert body["destination"] in ("notion", "local")
    assert len(body["meetings"]) == 1
    assert body["meetings"][0]["recording_id"] == "rec-1"
    assert body["meetings"][0]["title"] == "Patent Strategy"


def test_meeting_detail(client):
    r = client.get("/api/meetings/rec-1")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Patent Strategy"
    assert body["overview"] == ["Filed the provisional"]
    assert body["action_items"][0]["owner"] == "Sam"
    assert body["duration_label"]  # non-empty derived label


def test_meeting_detail_404(client):
    assert client.get("/api/meetings/missing").status_code == 404


def test_audio_served(client):
    r = client.get("/api/audio/rec-1")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/mpeg")
    assert r.content == b"ID3fake-mp3-bytes"


def test_audio_missing_404(client):
    assert client.get("/api/audio/nope").status_code == 404


def test_audio_rejects_traversal(client):
    # encoded traversal must not escape the audio dir
    r = client.get("/api/audio/..%2f..%2fsecret")
    assert r.status_code == 404
