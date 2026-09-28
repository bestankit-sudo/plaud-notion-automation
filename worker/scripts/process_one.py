"""Full pipeline on one recording -> a real Notion page on the configured parent.

    PYTHONPATH=src .venv/bin/python scripts/process_one.py <recording_id>

Takes the same run lock as the launchd job, so a hand-run and a scheduled run
can never end up transcribing the same recording at the same time.
"""

from __future__ import annotations

import sys
import time

from plaud_worker.config import Settings
from plaud_worker.ledger import Ledger
from plaud_worker.pipeline import process_recording
from plaud_worker.runlock import AlreadyRunning, run_lock
from plaud_worker.voiceprints import VoiceprintStore


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: process_one.py <recording_id>")
    rid = sys.argv[1]
    s = Settings.load()
    store = VoiceprintStore(s.state_dir / "voiceprints.db")
    ledger = Ledger(s.state_dir / "ledger.db")

    try:
        with run_lock(s.state_dir):
            t0 = time.time()
            meeting = process_recording(rid, s, store=store, ledger=ledger, write=True)
            elapsed = time.time() - t0
    except AlreadyRunning as e:
        raise SystemExit(f"{e} — not starting a second pipeline")

    print(f"\nprocessed in {elapsed:.0f}s")
    print("title:", meeting.title)
    print("participants:", [a.name for a in meeting.attendees])
    print("overview bullets:", len(meeting.overview),
          "| sections:", len(meeting.sections),
          "| action items:", len(meeting.action_items))
    print("page:", meeting.source_url)


if __name__ == "__main__":
    main()
