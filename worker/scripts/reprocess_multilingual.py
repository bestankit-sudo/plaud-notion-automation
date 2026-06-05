"""Find multilingual back-catalog meetings and re-render them natively.

Runs the multilingual detector over every processed recording (caching the flag),
then re-renders only the multilingual ones through the pipeline's per-block path
so each speaker's turns keep their original language (Chinese / Hindi / English).
Monolingual meetings are left untouched (their single-pass transcript is correct).
Pages are updated in place via the ledger — no duplicates.

    PYTHONPATH=src .venv/bin/python scripts/reprocess_multilingual.py
"""

from __future__ import annotations

import json
import time

from mlx_whisper.audio import load_audio

from plaud_worker import multilang
from plaud_worker.config import Settings
from plaud_worker.diarize import DiarTurn, DiarizationResult
from plaud_worker.ledger import Ledger
from plaud_worker.notion import NotionWriter
from plaud_worker.pipeline import process_recording
from plaud_worker.riffado import RiffadoClient
from plaud_worker.voiceprints import VoiceprintStore

MIN_DUR_S = 60


def _is_ml(s: Settings, rid: str) -> bool:
    """Cached multilingual flag, computing + caching it on first encounter."""
    flag = s.state_dir / "ml_flag" / f"{rid}.json"
    if flag.exists():
        return json.loads(flag.read_text())["multilingual"]
    dpath = s.state_dir / "diar_full" / f"{rid}.json"
    apath = s.state_dir / "audio" / f"{rid}.mp3"
    if not dpath.exists() or not apath.exists():
        return False
    dj = json.loads(dpath.read_text())
    blocks = multilang.merge_blocks([DiarTurn(**t) for t in dj["turns"]])
    val, secondary = multilang.detect(load_audio(str(apath)), blocks)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(json.dumps({"multilingual": val, "secondary": secondary}))
    return val


def main() -> None:
    s = Settings.load()
    skip = s.skip_recordings()
    store = VoiceprintStore(s.state_dir / "voiceprints.db")
    ledger = Ledger(s.state_dir / "ledger.db")
    with RiffadoClient(s.riffado_base_url, s.riffado_api_key) as r:
        recs = [
            rec for rec in r.list_recordings()
            if (rec.get("duration_ms") or 0) / 1000 >= MIN_DUR_S
            and not rec.get("is_trash") and rec["id"] not in skip
        ]

    print(f"scanning {len(recs)} recordings for multilingual content...\n")
    multilingual = []
    for rec in recs:
        rid = rec["id"]
        t0 = time.time()
        ml = _is_ml(s, rid)
        tag = "MULTILINGUAL" if ml else "monolingual"
        print(f"  [{tag:12s}] {(rec.get('title') or rid)[:48]} ({time.time()-t0:.0f}s)")
        if ml:
            multilingual.append(rec)

    print(f"\n{len(multilingual)} multilingual meetings to re-render natively:\n")
    for i, rec in enumerate(multilingual, 1):
        rid = rec["id"]
        title = (rec.get("title") or rid)[:48]
        t0 = time.time()
        try:
            # drop any stale single-pass per-block cache so it re-transcribes fresh
            meeting = process_recording(rid, s, store=store, ledger=ledger, write=False)
            existing = ledger.get(rid)
            with NotionWriter(s.notion_token) as w:
                if existing and existing.notion_page_id and w.page_exists(existing.notion_page_id):
                    w.replace_page_content(existing.notion_page_id, meeting)
                    pid = existing.notion_page_id
                else:
                    pid = w.create_meeting_page(s.notion_parent_page_id, meeting)
                url = w.page_url(pid)
            ledger.upsert(rid, notion_page_id=pid, status="processed")
            mix = multilang.lang_mix(meeting.transcript)
            print(f"[{i}/{len(multilingual)}] {title} | {mix} | {url} ({time.time()-t0:.0f}s)")
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(multilingual)}] FAILED {title}: {e}")

    store.close()
    ledger.close()
    print("\nDONE")


if __name__ == "__main__":
    main()
