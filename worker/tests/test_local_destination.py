from datetime import datetime, timezone

from plaud_worker.destinations.local import LocalDestination
from plaud_worker.models import ActionItem, Attendee, Meeting, Section, TranscriptTurn
from plaud_worker.notes_store import NotesStore


def _meeting(rid="rec-1", title="Standup") -> Meeting:
    return Meeting(
        recording_id=rid,
        title=title,
        recorded_at=datetime(2026, 6, 2, 21, 33, tzinfo=timezone.utc),
        duration_ms=1634000,
        source_url=None,
        audio_path="/abs/state/audio/rec-1.mp3",
        overview=["Did the thing"],
        sections=[Section("Topic", ["bullet"])],
        action_items=[ActionItem("Sam", "Send the spec", "by Friday")],
        attendees=[Attendee("Sam")],
        transcript=[TranscriptTurn("Sam", "hello")],
    )


def test_publish_writes_and_roundtrips(tmp_path):
    dest = LocalDestination(tmp_path / "notes.db")
    ref = dest.publish(_meeting())
    assert ref == "rec-1"
    dest.close()

    store = NotesStore(tmp_path / "notes.db")
    got = store.get("rec-1")
    assert got is not None
    assert got.title == "Standup"
    assert got.action_items[0].owner == "Sam"
    rows = store.list_summaries()
    assert rows[0]["recording_id"] == "rec-1"
    assert rows[0]["title"] == "Standup"
    store.close()


def test_publish_is_idempotent_upsert(tmp_path):
    dest = LocalDestination(tmp_path / "notes.db")
    dest.publish(_meeting(title="Old"))
    dest.publish(_meeting(title="New"))  # same recording_id
    dest.close()

    store = NotesStore(tmp_path / "notes.db")
    assert len(store.list_summaries()) == 1
    assert store.get("rec-1").title == "New"
    store.close()


def test_audio_rel_path_is_basename(tmp_path):
    LocalDestination(tmp_path / "notes.db").publish(_meeting())
    store = NotesStore(tmp_path / "notes.db")
    row = store._conn.execute(
        "SELECT audio_rel_path FROM meetings WHERE recording_id = 'rec-1'"
    ).fetchone()
    assert row["audio_rel_path"] == "rec-1.mp3"
    store.close()
