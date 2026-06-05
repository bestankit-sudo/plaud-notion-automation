"""Build voice clips for recurring UNENROLLED speaker clusters.

After re-enrolling the 5 known people, some clusters remain unnamed yet recur
across multiple recordings — they're either a known person in a different
acoustic setting or a real colleague we haven't named. This extracts a ~25s clip
of each so you can listen and tell us who they are (or 'noise, ignore').

For each such cluster it names the clip with the cluster id and its nearest known
name + score, e.g.  cluster04_nearAkash_0.79.mp3.

    PYTHONPATH=src .venv/bin/python scripts/snippet_unknowns.py
"""

from __future__ import annotations

import json
import subprocess

from plaud_worker.config import Settings
from plaud_worker.diarize import diarize
from plaud_worker.identify import cluster_embeddings
from plaud_worker.voiceprints import VoiceprintStore

THRESHOLD = 0.55
MIN_RECORDINGS = 2   # only clusters seen in 2+ recordings are worth naming
KEEP = 0.85          # clusters at/above this are already enrolled -> skip
TARGET_SECONDS = 25.0
MAX_SEGMENTS = 8


def _extract(audio: str, ranges: list[tuple[float, float]], out: str) -> None:
    parts, labels = [], []
    for i, (s, e) in enumerate(ranges):
        parts.append(f"[0]atrim={s:.2f}:{e:.2f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[a{i}]")
    flt = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(ranges)}:v=0:a=1[out]"
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio, "-filter_complex", flt, "-map", "[out]", out],
        check=True, capture_output=True,
    )


def main() -> None:
    s = Settings.load()
    audio_dir = s.state_dir / "audio"
    snip_dir = s.state_dir / "snippets_unknown"
    snip_dir.mkdir(parents=True, exist_ok=True)

    items: list[tuple[str, str, list[float]]] = []
    for p in sorted((s.state_dir / "diar_cache").glob("*.json")):
        for label, vec in json.loads(p.read_text()).items():
            items.append((p.stem, label, vec))
    clusters = cluster_embeddings(items, threshold=THRESHOLD)
    store = VoiceprintStore(s.state_dir / "voiceprints.db")

    targets = []
    for i, c in enumerate(clusters):
        name, score = store.match(c.centroid, threshold=0.0)
        if score >= KEEP:
            continue  # already enrolled
        if len(c.recordings) < MIN_RECORDINGS:
            continue  # not recurring
        targets.append((i, c, name, score))

    print(f"{len(targets)} recurring unenrolled clusters to sample:")
    diar_cache: dict[str, object] = {}
    for i, c, near, score in targets:
        made = False
        # use the recording where this cluster has the most/clearest presence
        for rid, label in sorted(c.members):
            audio = audio_dir / f"{rid}.mp3"
            if not audio.exists():
                continue
            if rid not in diar_cache:
                diar_cache[rid] = diarize(str(audio), s.hf_token)
            res = diar_cache[rid]
            if label not in res.embeddings:
                continue
            segs = sorted((t for t in res.turns if t.speaker == label),
                          key=lambda t: t.end - t.start, reverse=True)
            ranges, total = [], 0.0
            for t in segs:
                ranges.append((t.start, t.end)); total += t.end - t.start
                if total >= TARGET_SECONDS or len(ranges) >= MAX_SEGMENTS:
                    break
            if not ranges:
                continue
            ranges.sort()
            tag = f"near{near.split()[0]}_{score:.2f}" if near else "unknown"
            out = snip_dir / f"cluster{i:02d}_{tag}.mp3"
            _extract(str(audio), ranges, str(out))
            print(f"  cluster {i:2d}: {out.name}  ({total:.0f}s, "
                  f"{len(c.recordings)} recordings, nearest={near}:{score:.2f})")
            made = True
            break
        if not made:
            print(f"  cluster {i:2d}: no usable audio (nearest={near}:{score:.2f})")
    store.close()
    subprocess.run(["open", str(snip_dir)], check=False)
    print(f"\nclips in: {snip_dir}")


if __name__ == "__main__":
    main()
