import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.speakers_api as sp


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


def test_snippet_bad_label(state):
    _seed_meeting(state, "rec1")
    c = _client(state)
    assert c.get("/api/audio/rec1/snippet?label=../etc").status_code == 400
    assert c.get("/api/audio/rec1/snippet?label=SPEAKER_99").status_code == 404  # not in meeting


def test_snippet_extracts_and_caches(state, monkeypatch):
    _seed_meeting(state, "rec1")
    (state / "audio").mkdir(parents=True, exist_ok=True)
    (state / "audio" / "rec1.mp3").write_bytes(b"ID3fake")
    calls = []

    def fake_extract(audio, ranges, out):
        calls.append((audio, tuple(ranges), out))
        Path(out).write_bytes(b"ID3snippet")

    monkeypatch.setattr(sp, "_extract", fake_extract)
    monkeypatch.setattr(sp.shutil, "which", lambda _x: "/opt/homebrew/bin/ffmpeg")
    c = _client(state)
    r = c.get("/api/audio/rec1/snippet?label=SPEAKER_00")
    assert r.status_code == 200 and r.content == b"ID3snippet"
    assert (state / "snippets_panel" / "rec1_SPEAKER_00.mp3").exists()
    # second call is cached -> no second extract
    c.get("/api/audio/rec1/snippet?label=SPEAKER_00")
    assert len(calls) == 1


def _seed_notes(state, rid, transcript_speaker):
    from plaud_worker.notes_store import NotesStore
    from plaud_worker.models import Meeting, TranscriptTurn, Attendee
    ns = NotesStore(state / "notes.db")
    ns.upsert(Meeting(recording_id=rid, title="T", recorded_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
                      attendees=[Attendee(transcript_speaker)],
                      transcript=[TranscriptTurn(transcript_speaker, "hello")]),
              audio_rel_path=f"{rid}.mp3")
    ns.close()


def test_name_enrolls_and_relabels(state):
    _seed_meeting(state, "rec1")
    _seed_notes(state, "rec1", "Guest 1")  # SPEAKER_01 displays as Guest 1
    c = _client(state)
    r = c.post("/api/meetings/rec1/speakers/SPEAKER_01/name", json={"name": "Akash Jain"})
    assert r.status_code == 200 and r.json()["enrolled"] is True
    # the voice is now enrolled -> appears in the library
    names = [s["name"] for s in c.get("/api/speakers").json()["speakers"]]
    assert "Akash Jain" in names
    # this meeting's transcript was relabeled locally
    m = c.get("/api/meetings/rec1").json()
    assert any(t["speaker"] == "Akash Jain" for t in m["transcript"])
    assert not any(t["speaker"] == "Guest 1" for t in m["transcript"])
    # audit log written
    assert (state / "speaker_log.jsonl").exists()


def test_name_bad_input(state):
    _seed_meeting(state, "rec1")
    c = _client(state)
    assert c.post("/api/meetings/rec1/speakers/BAD/name", json={"name": "X"}).status_code == 400
    assert c.post("/api/meetings/rec1/speakers/SPEAKER_00/name", json={"name": "  "}).status_code == 400


def test_meeting_speakers_uses_persisted_labelmap(state):
    _seed_meeting(state, "rec1")
    from plaud_worker import naming
    naming.write_labelmap("rec1", state, {"SPEAKER_00": {"label": "SPEAKER_00", "display": "Pinned Name",
                                                          "name": "Pinned Name", "score": 0.9,
                                                          "enrolled": True, "total_speech_sec": 3.0}})
    c = _client(state)
    byl = {s["label"]: s for s in c.get("/api/meetings/rec1/speakers").json()["speakers"]}
    assert byl["SPEAKER_00"]["display"] == "Pinned Name"


def test_name_updates_labelmap_and_logs_proto(state):
    _seed_meeting(state, "rec1")
    _seed_notes(state, "rec1", "Guest 1")
    c = _client(state)
    c.post("/api/meetings/rec1/speakers/SPEAKER_01/name", json={"name": "Akash Jain", "scope": "this"})
    from plaud_worker import naming
    lm = naming.load_labelmap("rec1", state)
    assert lm["SPEAKER_01"]["display"] == "Akash Jain" and lm["SPEAKER_01"]["enrolled"] is True
    import json as _j
    last = [_j.loads(x) for x in (state / "speaker_log.jsonl").read_text().splitlines()][-1]
    assert last["old_display"] == "Guest 1" and isinstance(last["proto_id"], int) and last["scope"] == "this"


def test_backfill_relabels_other_meetings(state):
    # rec1 named in-request (scope this); rec2 has the same voice as Guest, back-filled
    _seed_meeting(state, "rec1"); _seed_notes(state, "rec1", "Guest 1")
    _seed_meeting(state, "rec2"); _seed_notes(state, "rec2", "Guest 1")
    import app.speakers_api as sp
    c = _client(state)
    # enroll SPEAKER_01's voice as Akash on rec1 (scope this so the request doesn't block on backfill)
    c.post("/api/meetings/rec1/speakers/SPEAKER_01/name", json={"name": "Akash Jain", "scope": "this"})
    # now run backfill synchronously and assert rec2 got relabeled
    from plaud_worker.voiceprints import VoiceprintStore  # noqa
    res = sp._backfill("Akash Jain", state, enqueue_notion=False)
    assert "rec2" in res["relabeled"]
    m2 = c.get("/api/meetings/rec2").json()
    assert any(t["speaker"] == "Akash Jain" for t in m2["transcript"])


def test_backfill_enqueues_notion(state):
    _seed_meeting(state, "rec1"); _seed_notes(state, "rec1", "Guest 1")
    import app.speakers_api as sp
    c = _client(state)
    c.post("/api/meetings/rec1/speakers/SPEAKER_01/name", json={"name": "Akash Jain", "scope": "this"})
    sp._backfill("Akash Jain", state, enqueue_notion=True)
    assert (state / "relabel_queue" / "rec1.json").exists()
