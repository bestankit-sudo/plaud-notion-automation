"""Download one Riffado recording's audio and transcribe it locally (MLX Whisper).

Validates the local-Whisper path on real data: quality + speed on this M1 Pro.
Pass a recording id, or omit to auto-pick the shortest recording (fast test).

    PYTHONPATH=src .venv/bin/python scripts/transcribe_one.py [recording_id]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from plaud_worker.config import Settings
from plaud_worker.riffado import RiffadoClient
from plaud_worker.transcribe import transcribe


def main() -> None:
    s = Settings.load()
    audio_dir = s.state_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    with RiffadoClient(s.riffado_base_url, s.riffado_api_key) as r:
        if len(sys.argv) > 1:
            rec = r.get_recording(sys.argv[1])
        else:
            recs = list(r.list_recordings())
            rec = min(recs, key=lambda x: x.get("duration_ms") or 1 << 62)
        rid = rec["id"]
        dur_s = round((rec.get("duration_ms") or 0) / 1000)
        print(f"recording: {rid} | {rec.get('title')!r} | {dur_s}s audio")

        dest = audio_dir / f"{rid}.mp3"
        if not dest.exists():
            t0 = time.time()
            r.download_audio(rid, str(dest))
            print(f"downloaded {dest.stat().st_size} bytes in {time.time()-t0:.1f}s")
        else:
            print(f"using cached audio: {dest}")

    t0 = time.time()
    tr = transcribe(str(dest))
    elapsed = time.time() - t0
    rtf = (elapsed / dur_s) if dur_s else 0
    print(f"\ntranscribed in {elapsed:.1f}s  (RTF {rtf:.2f}x; <1 = faster than real-time)")
    print(f"language: {tr.language} | segments: {len(tr.segments)} | chars: {len(tr.text)}")
    print("\n--- first 8 segments ---")
    for seg in tr.segments[:8]:
        print(f"[{seg.start:6.1f}-{seg.end:6.1f}] {seg.text}")


if __name__ == "__main__":
    main()
