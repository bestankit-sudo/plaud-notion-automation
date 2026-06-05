"""Extract a short voice clip of each enrolled non-owner speaker so you can
listen and name the handles (Speaker A/B/...) — and sanity-check Jordan.

For each target name it picks a representative meeting, re-diarizes it, matches
each voice to the library, and stitches that speaker's longest segments into a
~25s clip with ffmpeg. Clips land in state/snippets/ (opened in Finder).

    PYTHONPATH=src .venv/bin/python scripts/build_snippets.py
"""

from __future__ import annotations

import json
import subprocess

from plaud_worker.config import Settings
from plaud_worker.diarize import diarize
from plaud_worker.identify import cluster_embeddings
from plaud_worker.voiceprints import VoiceprintStore

OWNER = "Sam Rivers"
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
    snip_dir = s.state_dir / "snippets"
    snip_dir.mkdir(parents=True, exist_ok=True)

    items: list[tuple[str, str, list[float]]] = []
    for p in sorted((s.state_dir / "diar_cache").glob("*.json")):
        for label, vec in json.loads(p.read_text()).items():
            items.append((p.stem, label, vec))
    clusters = cluster_embeddings(items, threshold=0.55)
    store = VoiceprintStore(s.state_dir / "voiceprints.db")
    targets = [n for n, _ in store.names() if n != OWNER]

    # name -> recordings (largest cluster matching that name)
    name_recs: dict[str, list[str]] = {}
    for c in clusters:
        nm, _ = store.match(c.centroid, threshold=0.5)
        if nm and nm != OWNER and nm not in name_recs:
            name_recs[nm] = sorted(c.recordings)

    diar_cache: dict[str, object] = {}
    for name in targets:
        recs = name_recs.get(name, [])
        made = False
        for rid in recs:
            audio = audio_dir / f"{rid}.mp3"
            if not audio.exists():
                continue
            if rid not in diar_cache:
                diar_cache[rid] = diarize(str(audio), s.hf_token)
            res = diar_cache[rid]
            # which fresh label maps to this name?
            label = next(
                (lb for lb, emb in res.embeddings.items()
                 if store.match(emb, threshold=0.5)[0] == name), None
            )
            if not label:
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
            out = snip_dir / f"{name.replace(' ', '_')}.mp3"
            _extract(str(audio), ranges, str(out))
            print(f"{name}: {out.name}  ({total:.0f}s from {rid})")
            made = True
            break
        if not made:
            print(f"{name}: no snippet (no usable audio)")
    store.close()
    subprocess.run(["open", str(snip_dir)], check=False)
    print(f"\nsnippets in: {snip_dir}")


if __name__ == "__main__":
    main()
