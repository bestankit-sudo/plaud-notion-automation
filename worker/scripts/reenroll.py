"""Re-enroll voiceprints from the back-catalog using agglomerative clustering.

The owner is the largest cluster (present in the most recordings); Jordan is the
cluster containing a known sample; remaining recurring clusters (>= MIN
recordings) get stable handles. Resets the store, then enrolls.

    PYTHONPATH=src .venv/bin/python scripts/reenroll.py
"""

from __future__ import annotations

import json

from plaud_worker.config import Settings
from plaud_worker.identify import cluster_embeddings
from plaud_worker.voiceprints import VoiceprintStore

OWNER = "Sam Rivers"
# A known-good reference so the right cluster gets the right name regardless of
# clustering order: (recording_id, diarization label) -> name.
KNOWN = {("EXAMPLE_RECORDING_ID", "SPEAKER_01"): "Jordan"}
HANDLE_MIN = 3
THRESHOLD = 0.55


def main() -> None:
    s = Settings.load()
    items: list[tuple[str, str, list[float]]] = []
    for p in sorted((s.state_dir / "diar_cache").glob("*.json")):
        for label, vec in json.loads(p.read_text()).items():
            items.append((p.stem, label, vec))
    clusters = cluster_embeddings(items, threshold=THRESHOLD)
    emb_by_key = {(r, l): v for r, l, v in items}

    # cluster index -> name
    name_of: dict[int, str] = {0: OWNER}  # largest cluster = owner
    for ref, name in KNOWN.items():
        for i, c in enumerate(clusters):
            if ref in c.members:
                name_of[i] = name
                break
    letter = ord("A")
    for i, c in enumerate(clusters):
        if i in name_of or len(c.recordings) < HANDLE_MIN:
            continue
        name_of[i] = f"Speaker {chr(letter)}"
        letter += 1

    db = s.state_dir / "voiceprints.db"
    if db.exists():
        db.unlink()
    store = VoiceprintStore(db)
    for i, name in name_of.items():
        for r, l in clusters[i].members:
            store.enroll(name, emb_by_key[(r, l)])
        print(f"cluster {i} -> {name!r} ({len(clusters[i].recordings)} recordings)")
    print("\nvoiceprints:", store.names())
    store.close()


if __name__ == "__main__":
    main()
