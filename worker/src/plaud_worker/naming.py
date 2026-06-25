"""Pure speaker-naming helpers shared by the worker pipeline AND the credential-free
viewer. Keep module-level imports heavy-dep-free (the imported modules below only pull
stdlib+numpy at import time; torch/mlx are lazy inside their functions) so importing
this never drags the ML/summarizer/riffado stack into the web app."""

from __future__ import annotations

import json
from pathlib import Path

from .diarize import DiarTurn, DiarizationResult, label_segments
from .identify import identify_speakers
from .transcribe import transcribe_cached
from .voiceprints import VoiceprintStore


def display_names(turns, id_map: dict[str, str | None]) -> dict[str, str]:
    """Anonymous label -> display name: an identified person, else an ephemeral
    'Guest N' numbered by first appearance over `turns`."""
    display: dict[str, str] = {}
    guest = 0
    for t in turns:
        if t.speaker in display:
            continue
        name = id_map.get(t.speaker)
        if name:
            display[t.speaker] = name
        else:
            guest += 1
            display[t.speaker] = f"Guest {guest}"
    return display


def load_diar(path: Path) -> DiarizationResult:
    d = json.loads(Path(path).read_text())
    return DiarizationResult(
        turns=[DiarTurn(**t) for t in d["turns"]],
        embeddings=d["embeddings"],
    )


def reconstruct_labelmap(rid: str, store: VoiceprintStore, state_dir, *, threshold: float = 0.75):
    """Faithfully recompute {SPEAKER_XX -> {display,name,score,enrolled,total_speech_sec}}
    by replaying label_segments + display_names over the cached whisper transcript and
    diarization — the SAME computation pipeline.py did, so it can't drift. Returns None
    if the diar/transcript cache is missing (caller treats the meeting as play-only)."""
    state_dir = Path(state_dir)
    diar_path = state_dir / "diar_full" / f"{rid}.json"
    tr_path = state_dir / "transcripts" / f"{rid}.json"
    if not diar_path.exists() or not tr_path.exists():
        return None
    diar = load_diar(diar_path)
    tr = transcribe_cached("", cache_path=tr_path)  # cache hit -> no mlx
    seg_turns = label_segments(tr.segments, diar.turns)
    id_map = identify_speakers(diar, store, threshold=threshold)
    display = display_names(seg_turns, id_map)
    out: dict[str, dict] = {}
    for label, emb in diar.embeddings.items():
        name, score = store.match(emb, threshold=0.0)
        total = sum(t.end - t.start for t in diar.turns if t.speaker == label)
        out[label] = {
            "display": display.get(label, label),
            "name": id_map.get(label),
            "score": round(float(score), 4),
            "enrolled": id_map.get(label) is not None,
            "total_speech_sec": round(float(total), 1),
        }
    return out
