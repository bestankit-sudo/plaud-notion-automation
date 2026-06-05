"""Tag-once: assign real names to back-catalog voiceprint clusters and enroll.

Re-clusters the cached diarization embeddings (deterministic), then enrolls the
chosen clusters under the given names into the voiceprint store.

    PYTHONPATH=src .venv/bin/python scripts/tag_clusters.py --reset \
        --name '0=Sam Rivers' --name '1=Jordan'
"""

from __future__ import annotations

import argparse
import json

from plaud_worker.config import Settings
from plaud_worker.identify import greedy_cluster
from plaud_worker.voiceprints import VoiceprintStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", action="append", default=[], help="'<clusterIdx>=<Name>'")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--reset", action="store_true", help="wipe the voiceprint store first")
    ap.add_argument("--auto-handles", type=int, metavar="MIN", default=None,
                    help="give every still-unnamed cluster in >=MIN recordings a "
                         "stable handle (Speaker A, B, C, ...)")
    args = ap.parse_args()

    s = Settings.load()
    cache = s.state_dir / "diar_cache"
    items: list[tuple[str, str, list[float]]] = []
    for p in sorted(cache.glob("*.json")):
        for label, vec in json.loads(p.read_text()).items():
            items.append((p.stem, label, vec))
    clusters = greedy_cluster(items, threshold=args.threshold)
    emb_by_key = {(rid, label): vec for rid, label, vec in items}

    db = s.state_dir / "voiceprints.db"
    if args.reset and db.exists():
        db.unlink()
    store = VoiceprintStore(db)

    named: set[int] = set()
    for spec in args.name:
        idx_s, name = spec.split("=", 1)
        idx = int(idx_s)
        if idx >= len(clusters):
            print(f"skip: cluster {idx} out of range")
            continue
        for rid, label in clusters[idx].members:
            store.enroll(name, emb_by_key[(rid, label)])
        named.add(idx)
        print(f"enrolled cluster {idx} as {name!r} ({len(clusters[idx].members)} samples)")

    if args.auto_handles is not None:
        letter = ord("A")
        for idx, c in enumerate(clusters):
            if idx in named or len(c.recordings) < args.auto_handles:
                continue
            handle = f"Speaker {chr(letter)}"
            letter += 1
            for rid, label in c.members:
                store.enroll(handle, emb_by_key[(rid, label)])
            print(f"handle: cluster {idx} -> {handle!r} ({len(c.recordings)} recordings)")

    print("voiceprints now:", store.names())
    store.close()


if __name__ == "__main__":
    main()
