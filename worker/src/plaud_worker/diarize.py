"""Diarization (who-spoke-when) via pyannote, fully local after model download.

Produces anonymous speaker turns (SPEAKER_00, ...). The voiceprint stage maps
those anonymous labels to real names. Also aligns Whisper segments to speakers
so the transcript reads "**SPEAKER_00:** ...".
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .models import TranscriptTurn
from .transcribe import Segment

DIARIZATION_MODEL = "pyannote/speaker-diarization-3.1"


def _to_wav(audio_path: str) -> str:
    """Decode to 16 kHz mono WAV. pyannote mis-counts samples on some MP3s
    (frame-boundary rounding); a clean WAV sidesteps it."""
    out = Path(tempfile.gettempdir()) / (Path(audio_path).stem + ".pyannote.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ac", "1", "-ar", "16000", "-f", "wav", str(out)],
        check=True,
        capture_output=True,
    )
    return str(out)


@dataclass
class DiarTurn:
    start: float
    end: float
    speaker: str  # anonymous label, e.g. "SPEAKER_00"


@dataclass
class DiarizationResult:
    turns: list[DiarTurn]
    # one voiceprint per anonymous speaker label, straight from pyannote
    embeddings: dict[str, "list[float]"]


def diarize(
    audio_path: str,
    hf_token: str,
    *,
    device_pref: str = "mps",
    num_speakers: int | None = None,
) -> DiarizationResult:
    import torch
    from pyannote.audio import Pipeline

    # pyannote 4.x renamed use_auth_token -> token; support both.
    try:
        pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, token=hf_token)
    except TypeError:
        pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, use_auth_token=hf_token)
    if pipeline is None:
        raise RuntimeError(
            f"Could not load {DIARIZATION_MODEL} — check HF token and that the "
            "model terms are accepted on huggingface.co."
        )

    wav = _to_wav(audio_path)

    # Prefer Apple GPU; fall back to CPU if MPS chokes on an unsupported op.
    devices = [device_pref, "cpu"] if device_pref != "cpu" else ["cpu"]
    last_err: Exception | None = None
    for dev in devices:
        try:
            pipeline.to(torch.device(dev))
            kw = {"num_speakers": num_speakers} if num_speakers else {}
            result = pipeline(wav, **kw)
            # pyannote 4.x returns DiarizeOutput; 3.x returns an Annotation.
            annotation = result
            if not hasattr(annotation, "itertracks"):
                annotation = (
                    getattr(result, "speaker_diarization", None)
                    or getattr(result, "exclusive_speaker_diarization", None)
                )
            if annotation is None:
                raise RuntimeError(f"no diarization annotation in {type(result).__name__}")
            turns = [
                DiarTurn(start=float(seg.start), end=float(seg.end), speaker=label)
                for seg, _, label in annotation.itertracks(yield_label=True)
            ]
            # speaker_embeddings rows align to annotation.labels() order.
            embeddings: dict[str, list[float]] = {}
            emb = getattr(result, "speaker_embeddings", None)
            if emb is not None:
                for label, vec in zip(annotation.labels(), emb):
                    embeddings[label] = [float(x) for x in vec]
            return DiarizationResult(turns=turns, embeddings=embeddings)
        except Exception as e:  # noqa: BLE001 - retry on a different device
            last_err = e
    raise RuntimeError(f"diarization failed on {devices}: {last_err}")


def diarize_cached(audio_path: str, hf_token: str, *, cache_path: Path, **kwargs) -> DiarizationResult:
    """diarize() with an on-disk cache of turns + embeddings. Diarization is slow
    and deterministic for a recording, so cache it once; speaker re-identification
    (re-matching embeddings against an updated voiceprint store) then costs nothing."""
    if cache_path.exists():
        d = json.loads(cache_path.read_text())
        return DiarizationResult(
            turns=[DiarTurn(**t) for t in d["turns"]],
            embeddings=d["embeddings"],
        )
    res = diarize(audio_path, hf_token, **kwargs)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {"turns": [{"start": t.start, "end": t.end, "speaker": t.speaker} for t in res.turns],
             "embeddings": res.embeddings},
            ensure_ascii=False,
        )
    )
    return res


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def label_segments(
    segments: list[Segment], turns: list[DiarTurn]
) -> list[TranscriptTurn]:
    """Assign each Whisper segment the max-overlap speaker, then coalesce
    consecutive same-speaker segments into clean transcript turns."""
    out: list[TranscriptTurn] = []
    for seg in segments:
        best, best_ov = None, 0.0
        for t in turns:
            ov = _overlap(seg.start, seg.end, t.start, t.end)
            if ov > best_ov:
                best, best_ov = t.speaker, ov
        speaker = best  # None if no overlap -> unknown
        if out and out[-1].speaker == speaker:
            out[-1].text = f"{out[-1].text} {seg.text}".strip()
        else:
            out.append(TranscriptTurn(speaker=speaker, text=seg.text))
    return out
