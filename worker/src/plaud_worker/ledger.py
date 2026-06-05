"""Local SQLite ledger — idempotency + processing state, kept local for privacy.

One row per Riffado recording id. The Notion writer consults this to update the
existing page on reruns rather than creating duplicates.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed (
    recording_id    TEXT PRIMARY KEY,
    notion_page_id  TEXT,
    processing_hash TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@dataclass
class LedgerRow:
    recording_id: str
    notion_page_id: str | None
    processing_hash: str | None
    status: str


class Ledger:
    def __init__(self, db_path: Path):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def get(self, recording_id: str) -> LedgerRow | None:
        cur = self._conn.execute(
            "SELECT recording_id, notion_page_id, processing_hash, status "
            "FROM processed WHERE recording_id = ?",
            (recording_id,),
        )
        row = cur.fetchone()
        return LedgerRow(**row) if row else None

    def upsert(
        self,
        recording_id: str,
        *,
        notion_page_id: str | None = None,
        processing_hash: str | None = None,
        status: str = "processed",
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO processed (recording_id, notion_page_id, processing_hash, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(recording_id) DO UPDATE SET
                notion_page_id  = excluded.notion_page_id,
                processing_hash = excluded.processing_hash,
                status          = excluded.status,
                updated_at      = datetime('now')
            """,
            (recording_id, notion_page_id, processing_hash, status),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
