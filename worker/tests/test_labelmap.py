import json

import numpy as np

from plaud_worker import naming
from plaud_worker.diarize import DiarizationResult, DiarTurn
from plaud_worker.voiceprints import VoiceprintStore


def _diar():
    return DiarizationResult(
        turns=[DiarTurn(0.0, 3.0, "SPEAKER_00"), DiarTurn(3.0, 4.0, "SPEAKER_01")],
        embeddings={"SPEAKER_00": [1.0] + [0.0] * 255, "SPEAKER_01": [0.0, 1.0] + [0.0] * 254},
    )


def test_build_labelmap_shape(tmp_path):
    store = VoiceprintStore(tmp_path / "vp.db")
    store.enroll("Sam", np.array([1.0] + [0.0] * 255, dtype=np.float32))
    lm = naming.build_labelmap(_diar(), {"SPEAKER_00": "Sam", "SPEAKER_01": None},
                               {"SPEAKER_00": "Sam", "SPEAKER_01": "Guest 1"}, store)
    store.close()
    assert lm["SPEAKER_00"] == {"display": "Sam", "name": "Sam", "score": 1.0,
                                "enrolled": True, "total_speech_sec": 3.0}
    assert lm["SPEAKER_01"]["display"] == "Guest 1" and lm["SPEAKER_01"]["enrolled"] is False


def test_write_load_roundtrip(tmp_path):
    naming.write_labelmap("rec1", tmp_path, {"SPEAKER_00": {"display": "Sam"}})
    assert naming.load_labelmap("rec1", tmp_path) == {"SPEAKER_00": {"display": "Sam"}}
    assert naming.load_labelmap("ghost", tmp_path) is None
    saved = json.loads((tmp_path / "labelmap" / "rec1.json").read_text())
    assert saved["version"] == 1


def test_load_or_reconstruct_prefers_persisted(tmp_path):
    store = VoiceprintStore(tmp_path / "vp.db")
    naming.write_labelmap("rec1", tmp_path, {"SPEAKER_00": {"display": "Pinned"}})
    out = naming.load_or_reconstruct("rec1", store, tmp_path)
    store.close()
    assert out["SPEAKER_00"]["display"] == "Pinned"  # used the file, did not reconstruct
