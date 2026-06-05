"""Back-catalog enrollment / voiceprint validation.

Diarize a sample of recordings, collect per-speaker embeddings, and cluster them
across recordings. The cluster present in the MOST recordings is the device owner
("you-anchor"). Remaining clusters are candidates you tag once.

    PYTHONPATH=src .venv/bin/python scripts/enroll_backcatalog.py [--limit N] [--owner "Name"]

Diarization embeddings are cached under state/diar_cache so reruns are instant.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from plaud_worker.config import Settings
from plaud_worker.diarize import diarize
from plaud_worker.identify import greedy_cluster
from plaud_worker.riffado import RiffadoClient
from plaud_worker.voiceprints import VoiceprintStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--min-dur", type=int, default=120)
    ap.add_argument("--max-dur", type=int, default=1200)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--owner", default=None, help="enroll the top cluster under this name")
    args = ap.parse_args()

    s = Settings.load()
    audio_dir = s.state_dir / "audio"
    cache_dir = s.state_dir / "diar_cache"
    audio_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    with RiffadoClient(s.riffado_base_url, s.riffado_api_key) as r:
        recs = list(r.list_recordings())
        picked = [
            x for x in recs
            if args.min_dur <= (x.get("duration_ms") or 0) / 1000 <= args.max_dur
        ][: args.limit]
        titles = {x["id"]: x.get("title") or x["id"] for x in picked}

        items: list[tuple[str, str, list[float]]] = []
        for i, rec in enumerate(picked, 1):
            rid = rec["id"]
            cache = cache_dir / f"{rid}.json"
            if cache.exists():
                emb = json.loads(cache.read_text())
                print(f"[{i}/{len(picked)}] cached  {titles[rid][:55]}  ({len(emb)} speakers)")
            else:
                dest = audio_dir / f"{rid}.mp3"
                if not dest.exists():
                    r.download_audio(rid, str(dest))
                t0 = time.time()
                emb = diarize(str(dest), s.hf_token).embeddings
                cache.write_text(json.dumps(emb))
                print(f"[{i}/{len(picked)}] diarized {titles[rid][:55]}  "
                      f"({len(emb)} speakers, {time.time()-t0:.0f}s)")
            for label, vec in emb.items():
                items.append((rid, label, vec))

    print(f"\ncollected {len(items)} speaker-embeddings from {len(picked)} recordings")
    clusters = greedy_cluster(items, threshold=args.threshold)
    print(f"\n=== {len(clusters)} clusters (by # recordings they appear in) ===")
    for idx, c in enumerate(clusters):
        anchor = "  <-- YOU-ANCHOR (in the most recordings)" if idx == 0 else ""
        print(f"\nCluster {idx}: {len(c.recordings)} recordings, {len(c.members)} segments{anchor}")
        for rid in list(c.recordings)[:6]:
            print(f"    - {titles.get(rid, rid)[:60]}")

    if args.owner and clusters:
        emb_by_key = {(rid, label): vec for rid, label, vec in items}
        store = VoiceprintStore(s.state_dir / "voiceprints.db")
        for rid, label in clusters[0].members:
            store.enroll(args.owner, emb_by_key[(rid, label)])
        store.close()
        print(f"\nenrolled top cluster as '{args.owner}' "
              f"({len(clusters[0].members)} samples) -> state/voiceprints.db")


if __name__ == "__main__":
    main()
