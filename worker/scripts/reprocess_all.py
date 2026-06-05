"""Reprocess the entire back-catalog with the current voiceprint store.

Builds each meeting (transcribe + diarize are cached after the first run, so this
is cheap to re-run), then writes Notion: a recording already in the ledger has its
page rewritten in place (no duplicate); new ones get a fresh page under the parent.

    PYTHONPATH=src .venv/bin/python scripts/reprocess_all.py
"""

from __future__ import annotations

import time

from plaud_worker.config import Settings
from plaud_worker.ledger import Ledger
from plaud_worker.notion import NotionWriter
from plaud_worker.pipeline import process_recording
from plaud_worker.riffado import RiffadoClient
from plaud_worker.voiceprints import VoiceprintStore

MIN_DUR_S = 60


def main() -> None:
    s = Settings.load()
    parent = s.notion_parent_page_id
    store = VoiceprintStore(s.state_dir / "voiceprints.db")
    ledger = Ledger(s.state_dir / "ledger.db")

    skip = s.skip_recordings()
    with RiffadoClient(s.riffado_base_url, s.riffado_api_key) as r:
        recs = list(r.list_recordings())

    todo = [
        rec for rec in recs
        if (rec.get("duration_ms") or 0) / 1000 >= MIN_DUR_S
        and not rec.get("is_trash")
        and rec["id"] not in skip
    ]
    if skip:
        print(f"skipping {len(skip)} recording(s): {', '.join(sorted(skip))}")
    print(f"{len(todo)} recordings to (re)process into {parent}\n")

    for i, rec in enumerate(todo, 1):
        rid = rec["id"]
        title = (rec.get("title") or rid)[:50]
        t0 = time.time()
        try:
            meeting = process_recording(rid, s, store=store, ledger=ledger, write=False)
            existing = ledger.get(rid)
            with NotionWriter(s.notion_token) as w:
                if existing and existing.notion_page_id and w.page_exists(existing.notion_page_id):
                    w.replace_page_content(existing.notion_page_id, meeting)
                    page_id, verb = existing.notion_page_id, "updated"
                else:
                    page_id, verb = w.create_meeting_page(parent, meeting), "created"
                url = w.page_url(page_id)
            ledger.upsert(rid, notion_page_id=page_id, status="processed")
            who = ", ".join(a.name for a in meeting.attendees)
            print(f"[{i:2d}/{len(todo)}] {verb} {title} | {who} | {url} ({time.time()-t0:.0f}s)")
        except Exception as e:  # noqa: BLE001
            ledger.upsert(rid, status="failed")
            print(f"[{i:2d}/{len(todo)}] FAILED {title}: {e}")

    store.close()
    ledger.close()
    print("\nDONE")


if __name__ == "__main__":
    main()
