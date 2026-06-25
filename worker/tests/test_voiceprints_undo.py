import numpy as np

from plaud_worker.voiceprints import VoiceprintStore


def test_enroll_returns_id_and_delete_recovers(tmp_path):
    s = VoiceprintStore(tmp_path / "vp.db")
    a = np.array([1.0] + [0.0] * 255, dtype=np.float32)
    b = np.array([0.0, 1.0] + [0.0] * 254, dtype=np.float32)
    s.enroll("Sam", a)
    pid = s.enroll("Sam", b)          # a contaminating second sample
    assert isinstance(pid, int)
    # delete the bad prototype -> centroid recomputed from the surviving one
    s.delete_prototype(pid)
    name, score = s.match(a, threshold=0.5)
    assert name == "Sam" and score > 0.99   # clean sample matches again
    # the contaminating sample no longer matches Sam strongly
    assert s.match(b, threshold=0.9)[0] is None
    s.close()


def test_delete_last_prototype_removes_voiceprint(tmp_path):
    s = VoiceprintStore(tmp_path / "vp.db")
    pid = s.enroll("Solo", np.array([1.0] + [0.0] * 255, dtype=np.float32))
    s.delete_prototype(pid)
    assert s.names() == []          # voiceprint row gone when no prototypes remain
    s.close()
