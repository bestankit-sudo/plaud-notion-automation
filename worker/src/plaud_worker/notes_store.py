"""Local SQLite store of finished meeting notes (state/notes.db).

Mirrors Meeting.to_dict() as a JSON payload column plus a few queryable columns
for the viewer's list. Separate DB from the ledger/voiceprint stores so the
concerns stay isolated.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Meeting

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    recording_id   TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    recorded_at    TEXT NOT NULL,
    duration_ms    INTEGER,
    source_url     TEXT,
    audio_rel_path TEXT,
    payload_json   TEXT NOT NULL,
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class NotesStore:
    def __init__(self, db_path: Path):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def upsert(self, meeting: Meeting, *, audio_rel_path: str | None) -> str:
        payload = json.dumps(meeting.to_dict(), ensure_ascii=False)
        self._conn.execute(
            """
            INSERT INTO meetings (recording_id, title, recorded_at, duration_ms,
                                  source_url, audio_rel_path, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(recording_id) DO UPDATE SET
                title          = excluded.title,
                recorded_at    = excluded.recorded_at,
                duration_ms    = excluded.duration_ms,
                source_url     = excluded.source_url,
                audio_rel_path = excluded.audio_rel_path,
                payload_json   = excluded.payload_json,
                updated_at     = datetime('now')
            """,
            (
                meeting.recording_id,
                meeting.title,
                meeting.recorded_at.isoformat(),
                meeting.duration_ms,
                meeting.source_url,
                audio_rel_path,
                payload,
            ),
        )
        self._conn.commit()
        return meeting.recording_id

    def get(self, recording_id: str) -> Meeting | None:
        cur = self._conn.execute(
            "SELECT payload_json FROM meetings WHERE recording_id = ?",
            (recording_id,),
        )
        row = cur.fetchone()
        return Meeting.from_dict(json.loads(row["payload_json"])) if row else None

    def list_summaries(self) -> list[dict]:
        cur = self._conn.execute(
            "SELECT recording_id, title, recorded_at, duration_ms "
            "FROM meetings ORDER BY recorded_at DESC"
        )
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()
