"""Rebuild the voiceprint store with multi-prototype enrollment.

Keeps the names already in the store, but re-enrolls every cluster member as its
own prototype (not just a running average) so matching can compare a new voice
against each acoustic condition the person was recorded in. Only clusters that
confidently match an existing name (>= KEEP) are enrolled; everything else stays
unknown (a Guest / a candidate for snippet naming).

    PYTHONPATH=src .venv/bin/python scripts/reenroll_prototypes.py
"""

from __future__ import annotations

import json
import shutil

from plaud_worker.config import Settings
from plaud_worker.identify import cluster_embeddings
from plaud_worker.voiceprints import VoiceprintStore

THRESHOLD = 0.55  # clustering distance threshold (matches the pipeline)
KEEP = 0.85       # only re-enroll clusters that clearly map to a known name


def main() -> None:
    s = Settings.load()
    items: list[tuple[str, str, list[float]]] = []
    for p in sorted((s.state_dir / "diar_cache").glob("*.json")):
        for label, vec in json.loads(p.read_text()).items():
            items.append((p.stem, label, vec))
    clusters = cluster_embeddings(items, threshold=THRESHOLD)
    emb_by_key = {(r, l): v for r, l, v in items}

    db = s.state_dir / "voiceprints.db"
    old = VoiceprintStore(db)
    # cluster index -> (name) for clusters that confidently match a known name
    mapping: dict[int, str] = {}
    for i, c in enumerate(clusters):
        name, score = old.match(c.centroid, threshold=0.0)
        if name and score >= KEEP:
            mapping[i] = name
    old.close()

    shutil.copy(db, db.with_suffix(".db.bak"))
    db.unlink()
    store = VoiceprintStore(db)
    for i, name in sorted(mapping.items()):
        for r, l in clusters[i].members:
            store.enroll(name, emb_by_key[(r, l)])
        print(f"cluster {i:2d} -> {name!r}  ({len(clusters[i].members)} prototypes, "
              f"{len(clusters[i].recordings)} recordings)")
    print("\nvoiceprints (name, n):", store.names())
    proto_count = store._conn.execute("SELECT COUNT(*) FROM prototypes").fetchone()[0]
    print("total prototypes:", proto_count)
    store.close()


if __name__ == "__main__":
    main()
