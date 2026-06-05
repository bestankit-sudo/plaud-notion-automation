"""Transcribe + diarize one recording and print the speaker-labelled transcript.

Speakers are anonymous here (SPEAKER_00...) — the voiceprint stage maps them to
real names next. Requires HF_TOKEN (and accepted pyannote model terms).

    PYTHONPATH=src .venv/bin/python scripts/diarize_one.py [recording_id]
"""

from __future__ import annotations

import sys
import time
from collections import Counter

from plaud_worker.config import Settings
from plaud_worker.diarize import diarize, label_segments
from plaud_worker.riffado import RiffadoClient
from plaud_worker.transcribe import transcribe

DEFAULT_REC = "uVS3dxeRFbeyn0zeDB27J"  # the ~3-min clip already cached


def main() -> None:
    s = Settings.load()
    if not s.hf_token:
        raise SystemExit("HF_TOKEN not set — add it to secrets.env first.")
    rid = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REC

    audio_dir = s.state_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    dest = audio_dir / f"{rid}.mp3"
    if not dest.exists():
        with RiffadoClient(s.riffado_base_url, s.riffado_api_key) as r:
            r.download_audio(rid, str(dest))
    print(f"recording: {rid}")

    t0 = time.time()
    tr = transcribe(str(dest))
    print(f"transcribed: {len(tr.segments)} segments in {time.time()-t0:.1f}s")

    t0 = time.time()
    result = diarize(str(dest), s.hf_token)
    speakers = Counter(t.speaker for t in result.turns)
    print(f"diarized: {len(result.turns)} turns, {len(speakers)} speakers in {time.time()-t0:.1f}s")
    print(f"speakers: {dict(speakers)} | embeddings: {sorted(result.embeddings)}")

    labelled = label_segments(tr.segments, result.turns)
    print("\n--- speaker-labelled transcript ---")
    for turn in labelled[:20]:
        who = turn.speaker or "UNKNOWN"
        print(f"{who}: {turn.text}")


if __name__ == "__main__":
    main()
