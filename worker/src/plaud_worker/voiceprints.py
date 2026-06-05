"""Local voiceprint library — named speaker embeddings, kept on-disk (private).

Stores one running-average embedding per known person. Matching a new speaker's
embedding against the library (cosine) is what turns SPEAKER_00 into a real name.
Biometric data: never leaves the machine.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

_SCHEMA = """
CREATE TABLE IF NOT EXISTS voiceprints (
    name       TEXT PRIMARY KEY,
    embedding  BLOB NOT NULL,   -- float32 bytes, L2-normalised (running average)
    n          INTEGER NOT NULL DEFAULT 1,  -- how many samples averaged in
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS prototypes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    embedding  BLOB NOT NULL    -- float32 bytes, L2-normalised (one raw sample)
);
CREATE INDEX IF NOT EXISTS idx_prototypes_name ON prototypes (name);
"""


def _norm(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(v)
    return v / n if n else v


def cosine(a, b) -> float:
    a, b = _norm(np.asarray(a)), _norm(np.asarray(b))
    return float(np.dot(a, b))


class VoiceprintStore:
    def __init__(self, db_path: Path):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def enroll(self, name: str, embedding) -> None:
        """Add a sample for `name`: keep the raw embedding as its own prototype
        (so matching can compare against each acoustic condition separately) and
        also fold it into the running-average centroid (a stable fallback)."""
        new = _norm(embedding)
        self._conn.execute(
            "INSERT INTO prototypes (name, embedding) VALUES (?, ?)", (name, new.tobytes())
        )
        row = self._conn.execute(
            "SELECT embedding, n FROM voiceprints WHERE name = ?", (name,)
        ).fetchone()
        if row:
            old = np.frombuffer(row["embedding"], dtype=np.float32)
            n = row["n"]
            avg = _norm((old * n + new) / (n + 1))
            self._conn.execute(
                "UPDATE voiceprints SET embedding=?, n=?, updated_at=datetime('now') WHERE name=?",
                (avg.tobytes(), n + 1, name),
            )
        else:
            self._conn.execute(
                "INSERT INTO voiceprints (name, embedding, n) VALUES (?, ?, 1)",
                (name, new.tobytes()),
            )
        self._conn.commit()

    def match(self, embedding, *, threshold: float = 0.5) -> tuple[str | None, float]:
        """Best-matching name above threshold, with its cosine score.

        Scores against each *prototype* (raw sample) and keeps the best per name,
        so a voice recorded in a different acoustic condition still matches its
        closest enrolled sample rather than a washed-out average. Names with no
        prototype rows (legacy enrollments) fall back to their centroid."""
        q = _norm(embedding)
        best: dict[str, float] = {}
        for row in self._conn.execute("SELECT name, embedding FROM prototypes"):
            score = float(np.dot(q, np.frombuffer(row["embedding"], dtype=np.float32)))
            if score > best.get(row["name"], -1.0):
                best[row["name"]] = score
        for row in self._conn.execute("SELECT name, embedding FROM voiceprints"):
            if row["name"] in best:
                continue  # prototypes win when present
            best[row["name"]] = float(np.dot(q, np.frombuffer(row["embedding"], dtype=np.float32)))

        best_name, best_score = None, -1.0
        for name, score in best.items():
            if score > best_score:
                best_name, best_score = name, score
        if best_score >= threshold:
            return best_name, best_score
        return None, best_score

    def rename(self, old: str, new: str) -> None:
        """Rename a voiceprint. If `new` already exists, merge the two (weighted
        average) — handles 'Speaker A and Speaker E are both Rajeev'."""
        o = self._conn.execute(
            "SELECT embedding, n FROM voiceprints WHERE name = ?", (old,)
        ).fetchone()
        if not o:
            return
        existing = self._conn.execute(
            "SELECT embedding, n FROM voiceprints WHERE name = ?", (new,)
        ).fetchone()
        if existing:
            a = np.frombuffer(o["embedding"], dtype=np.float32)
            b = np.frombuffer(existing["embedding"], dtype=np.float32)
            na, nb = o["n"], existing["n"]
            merged = _norm((a * na + b * nb) / (na + nb))
            self._conn.execute(
                "UPDATE voiceprints SET embedding=?, n=?, updated_at=datetime('now') WHERE name=?",
                (merged.tobytes(), na + nb, new),
            )
            self._conn.execute("DELETE FROM voiceprints WHERE name = ?", (old,))
        else:
            self._conn.execute(
                "UPDATE voiceprints SET name=?, updated_at=datetime('now') WHERE name=?",
                (new, old),
            )
        # prototypes follow the name in both cases (rename or merge into `new`)
        self._conn.execute("UPDATE prototypes SET name=? WHERE name=?", (new, old))
        self._conn.commit()

    def names(self) -> list[tuple[str, int]]:
        return [
            (r["name"], r["n"])
            for r in self._conn.execute("SELECT name, n FROM voiceprints ORDER BY n DESC")
        ]

    def close(self) -> None:
        self._conn.close()
