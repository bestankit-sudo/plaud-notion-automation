"""Local transcription via MLX Whisper (Apple GPU). No network, no egress.

Produces time-stamped segments that the diarization stage aligns speakers to.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

# Full large-v3: best accuracy, slower than turbo; ~3GB on first download.
DEFAULT_MODEL = "mlx-community/whisper-large-v3-mlx"


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    language: str
    text: str
    segments: list[Segment]


def transcribe(
    audio_path: str,
    *,
    model: str = DEFAULT_MODEL,
    language: str | None = None,
    use_vad: bool = True,
) -> Transcript:
    import mlx_whisper

    result = mlx_whisper.transcribe(
        audio_path,
        path_or_hf_repo=model,
        language=language,  # None = auto-detect per recording
        # Anti-hallucination: stop repetition cascades on noisy audio and don't
        # let a bad chunk poison later ones.
        condition_on_previous_text=False,
        compression_ratio_threshold=2.4,
        no_speech_threshold=0.6,
    )
    segments = [
        Segment(start=float(s["start"]), end=float(s["end"]), text=s["text"].strip())
        for s in result.get("segments", [])
        # drop empty / zero-duration artifacts Whisper sometimes emits
        if s["text"].strip() and float(s["end"]) > float(s["start"])
    ]
    if use_vad:
        from .vad import clean_segments, speech_intervals

        try:
            intervals = speech_intervals(audio_path)
        except Exception:
            intervals = None  # VAD is best-effort; never block transcription
        segments = clean_segments(segments, intervals)
    return Transcript(
        language=result.get("language", "?"),
        text=" ".join(s.text for s in segments).strip(),
        segments=segments,
    )


def transcribe_cached(audio_path: str, *, cache_path: Path, **kwargs) -> Transcript:
    """transcribe() with an on-disk cache. MLX Whisper is the slow stage, and the
    transcript never changes for a given recording — so cache it once and let
    speaker re-identification / re-rendering reuse it for free."""
    if cache_path.exists():
        d = json.loads(cache_path.read_text())
        return Transcript(
            language=d["language"],
            text=d["text"],
            segments=[Segment(**s) for s in d["segments"]],
        )
    tr = transcribe(audio_path, **kwargs)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {"language": tr.language, "text": tr.text,
             "segments": [asdict(s) for s in tr.segments]},
            ensure_ascii=False,
        )
    )
    return tr
