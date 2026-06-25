import json
from pathlib import Path

import numpy as np

from plaud_worker import naming
from plaud_worker.models import TranscriptTurn
from plaud_worker.voiceprints import VoiceprintStore


def test_display_names_numbers_guests_in_order():
    turns = [TranscriptTurn("SPEAKER_01", "hi"), TranscriptTurn("SPEAKER_00", "yo"),
             TranscriptTurn("SPEAKER_01", "again")]
    out = naming.display_names(turns, {"SPEAKER_01": None, "SPEAKER_00": "Sam"})
    assert out == {"SPEAKER_01": "Guest 1", "SPEAKER_00": "Sam"}


def _seed(state, rid, *, enroll=None):
    (state / "diar_full").mkdir(parents=True, exist_ok=True)
    (state / "transcripts").mkdir(parents=True, exist_ok=True)
    e0 = [1.0] + [0.0] * 255   # SPEAKER_00 embedding
    e1 = [0.0, 1.0] + [0.0] * 254
    (state / "diar_full" / f"{rid}.json").write_text(json.dumps({
        "turns": [{"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
                  {"start": 3.0, "end": 4.0, "speaker": "SPEAKER_01"}],
        "embeddings": {"SPEAKER_00": e0, "SPEAKER_01": e1},
    }))
    (state / "transcripts" / f"{rid}.json").write_text(json.dumps({
        "language": "en", "text": "a b",
        "segments": [{"start": 0.0, "end": 3.0, "text": "hello there"},
                     {"start": 3.0, "end": 4.0, "text": "bye"}],
    }))
    store = VoiceprintStore(state / "voiceprints.db")
    if enroll:
        store.enroll(enroll[0], np.array(enroll[1], dtype=np.float32))
    return store


def test_reconstruct_labelmap_faithful(tmp_path):
    state = tmp_path / "state"
    store = _seed(state, "rec1", enroll=("Sam Rivers", [1.0] + [0.0] * 255))
    lm = naming.reconstruct_labelmap("rec1", store, state, threshold=0.75)
    store.close()
    assert lm["SPEAKER_00"]["name"] == "Sam Rivers"     # matched the enrolled voice
    assert lm["SPEAKER_00"]["enrolled"] is True
    assert lm["SPEAKER_00"]["display"] == "Sam Rivers"
    assert lm["SPEAKER_01"]["name"] is None             # unknown -> Guest
    assert lm["SPEAKER_01"]["display"] == "Guest 1"
    assert lm["SPEAKER_00"]["total_speech_sec"] == 3.0
    assert 0.0 <= lm["SPEAKER_01"]["score"] <= 1.0


def test_reconstruct_labelmap_missing_cache_returns_none(tmp_path):
    state = tmp_path / "state"
    store = VoiceprintStore(state / "voiceprints.db")
    assert naming.reconstruct_labelmap("nope", store, state) is None
    store.close()
