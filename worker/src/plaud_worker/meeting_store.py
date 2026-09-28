"""Single read/write path for a recording's structured Meeting.

Two local stores can hold it, and which one is populated depends entirely on
the configured destination:

  * ``notes.db``            — written by the viewer-facing notes path
  * ``meetings/{rid}.json`` — written by ``pipeline.process_recording`` for
    *every* recording, regardless of destination

On a ``destination=notion`` install nothing ever writes notes.db, so a reader
that consults only notes.db finds nothing and silently does nothing. That is
why speaker renames made in the viewer never reached Notion: both
``relabel.re_render_for`` and the app's ``_apply_relabel`` bailed out on a
``None`` from notes.db while the real meeting sat in the JSON cache.

Read through :func:`load_meeting` and write through :func:`save_meeting` so
neither store can be missed again.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Meeting
from .notes_store import NotesStore


def meeting_json_path(state_dir: Path, rid: str) -> Path:
    return state_dir / "meetings" / f"{rid}.json"


def load_meeting(state_dir: Path, rid: str) -> Meeting | None:
    """Return meeting *rid*, preferring notes.db and falling back to the JSON cache.

    Returns None only when neither store holds it.
    """
    db = state_dir / "notes.db"
    if db.exists():
        ns = NotesStore(db)
        try:
            meeting = ns.get(rid)
        finally:
            ns.close()
        if meeting is not None:
            return meeting

    path = meeting_json_path(state_dir, rid)
    if not path.exists():
        return None
    try:
        return Meeting.from_dict(json.loads(path.read_text()))
    except (ValueError, KeyError, TypeError):
        # A truncated or half-written cache must not take the caller down; the
        # recording simply looks unavailable and the queue entry is retried.
        return None


def save_meeting(
    state_dir: Path,
    meeting: Meeting,
    *,
    audio_rel_path: str | None = None,
) -> None:
    """Persist *meeting* back to whichever stores are actually in play.

    notes.db is updated only if it already holds a row for this recording, so a
    notion-destination install does not sprout a half-populated notes.db. The
    JSON cache is refreshed only if it already exists, so we never mint a cache
    for a recording the pipeline has not processed.
    """
    rid = meeting.recording_id

    db = state_dir / "notes.db"
    if db.exists():
        ns = NotesStore(db)
        try:
            if ns.get(rid) is not None:
                rel = audio_rel_path
                if rel is None:
                    rel = Path(meeting.audio_path).name if meeting.audio_path else f"{rid}.mp3"
                ns.upsert(meeting, audio_rel_path=rel)
        finally:
            ns.close()

    path = meeting_json_path(state_dir, rid)
    if path.exists():
        path.write_text(json.dumps(meeting.to_dict(), ensure_ascii=False))
