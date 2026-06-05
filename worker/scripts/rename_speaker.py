"""Rename a speaker handle to a real name (or merge two), propagating everywhere.

Updates the voiceprint library, re-renders every affected meeting page from the
local cache (no re-transcription), and refreshes the Speaker Directory.

    PYTHONPATH=src .venv/bin/python scripts/rename_speaker.py 'Speaker A' 'James Nicol'
"""

from __future__ import annotations

import json
import sys

from plaud_worker.config import Settings
from plaud_worker.directory import build_and_upsert
from plaud_worker.ledger import Ledger
from plaud_worker.models import Meeting
from plaud_worker.notion import NotionWriter
from plaud_worker.voiceprints import VoiceprintStore


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: rename_speaker.py '<old name/handle>' '<new name>'")
    old, new = sys.argv[1], sys.argv[2]
    s = Settings.load()

    # 1) library: rename (or merge into an existing name)
    store = VoiceprintStore(s.state_dir / "voiceprints.db")
    store.rename(old, new)
    store.close()

    # 2) re-render every cached meeting that mentions the old label
    ledger = Ledger(s.state_dir / "ledger.db")
    meetings_dir = s.state_dir / "meetings"
    updated = 0
    with NotionWriter(s.notion_token) as w:
        for p in sorted(meetings_dir.glob("*.json")):
            raw = p.read_text()
            if old not in raw:
                continue
            raw = raw.replace(old, new)
            p.write_text(raw)
            meeting = Meeting.from_dict(json.loads(raw))
            row = ledger.get(meeting.recording_id)
            if row and row.notion_page_id:
                w.replace_page_content(row.notion_page_id, meeting)
                updated += 1
                print(f"updated: {meeting.title[:60]}")
    ledger.close()

    # 3) refresh the directory
    build_and_upsert(s)
    print(f"\nrenamed {old!r} -> {new!r}; updated {updated} meeting pages + directory")


if __name__ == "__main__":
    main()
