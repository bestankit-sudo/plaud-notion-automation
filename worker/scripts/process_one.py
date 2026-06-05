"""Full pipeline on one recording -> a real Notion page on the TEST parent.

    PYTHONPATH=src .venv/bin/python scripts/process_one.py <recording_id>
"""

from __future__ import annotations

import sys
import time

from plaud_worker.config import Settings
from plaud_worker.ledger import Ledger
from plaud_worker.pipeline import process_recording
from plaud_worker.voiceprints import VoiceprintStore


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: process_one.py <recording_id>")
    rid = sys.argv[1]
    s = Settings.load()
    store = VoiceprintStore(s.state_dir / "voiceprints.db")
    ledger = Ledger(s.state_dir / "ledger.db")

    t0 = time.time()
    meeting = process_recording(rid, s, store=store, ledger=ledger, write=True)
    print(f"\nprocessed in {time.time()-t0:.0f}s")
    print("title:", meeting.title)
    print("participants:", [a.name for a in meeting.attendees])
    print("overview bullets:", len(meeting.overview),
          "| sections:", len(meeting.sections),
          "| action items:", len(meeting.action_items))
    print("page:", meeting.source_url)


if __name__ == "__main__":
    main()
