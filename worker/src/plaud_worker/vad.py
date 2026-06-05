"""Voice-activity detection (silero) + repetition cleanup.

Two cheap quality wins on noisy Plaud audio:
  * drop transcript segments that fall outside detected speech (kills Whisper
    hallucinations on silence/noise, e.g. trailing "Do Do Do...").
  * collapse degenerate segments where one token repeats (within-speech loops).
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .transcribe import Segment


def speech_intervals(audio_path: str) -> list[tuple[float, float]]:
    import torchaudio
    from silero_vad import get_speech_timestamps, load_silero_vad

    # 16 kHz mono wav for the VAD model
    wav_path = Path(tempfile.gettempdir()) / (Path(audio_path).stem + ".vad.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ac", "1", "-ar", "16000", str(wav_path)],
        check=True,
        capture_output=True,
    )
    wav, _sr = torchaudio.load(str(wav_path))
    model = load_silero_vad()
    ts = get_speech_timestamps(
        wav.squeeze(0), model, sampling_rate=16000, return_seconds=True
    )
    return [(float(t["start"]), float(t["end"])) for t in ts]


def _overlaps_speech(seg: Segment, intervals: list[tuple[float, float]], frac: float) -> bool:
    dur = max(seg.end - seg.start, 1e-6)
    ov = sum(
        max(0.0, min(seg.end, e) - max(seg.start, s)) for s, e in intervals
    )
    return (ov / dur) >= frac


def _is_repetitive(text: str) -> bool:
    toks = [t.lower().strip(".,!?;:") for t in text.split()]
    toks = [t for t in toks if t]
    if not toks:
        return False
    uniq = len(set(toks))
    if uniq == 1 and len(toks) >= 3:
        return True  # "ok ok ok", "Do Do Do ...", "Okay. Okay. Okay."
    if len(toks) >= 4 and uniq <= 2:
        return True
    if len(toks) >= 8 and len(toks) / uniq >= 2.5:
        return True  # phrase loop, e.g. "you gave me figure" repeated
    return False


def clean_segments(
    segments: list[Segment],
    intervals: list[tuple[float, float]] | None,
    *,
    min_speech_frac: float = 0.2,
) -> list[Segment]:
    out: list[Segment] = []
    for seg in segments:
        if _is_repetitive(seg.text):
            continue
        if intervals is not None and not _overlaps_speech(seg, intervals, min_speech_frac):
            continue
        # drop an exact immediate duplicate of the previous kept segment
        if out and out[-1].text.strip() == seg.text.strip():
            continue
        out.append(seg)
    return out
