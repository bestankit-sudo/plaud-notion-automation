"""Local destination — writes the Meeting into state/notes.db."""

from __future__ import annotations

import os
from pathlib import Path

from ..models import Meeting
from ..notes_store import NotesStore


class LocalDestination:
    name = "local"

    def __init__(self, notes_db: Path):
        self._store = NotesStore(notes_db)

    def publish(self, meeting: Meeting, *, prior_ref: str | None = None) -> str:
        # prior_ref unused: upsert by recording_id PK is already idempotent.
        rel = os.path.basename(meeting.audio_path) if meeting.audio_path else None
        return self._store.upsert(meeting, audio_rel_path=rel)

    def close(self) -> None:
        self._store.close()
