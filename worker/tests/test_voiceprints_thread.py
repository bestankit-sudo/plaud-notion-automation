import threading

import numpy as np

from plaud_worker.voiceprints import VoiceprintStore


def test_store_usable_across_threads(tmp_path):
    store = VoiceprintStore(tmp_path / "vp.db")
    err = []

    def work():
        try:
            store.enroll("Sam", np.array([1.0] + [0.0] * 255, dtype=np.float32))
            name, score = store.match(np.array([1.0] + [0.0] * 255, dtype=np.float32), threshold=0.5)
            assert name == "Sam" and score > 0.99
        except Exception as e:  # noqa: BLE001
            err.append(e)

    t = threading.Thread(target=work)
    t.start()
    t.join()
    store.close()
    assert not err, err
