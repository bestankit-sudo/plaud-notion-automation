"""meeting_store must find the meeting wherever it actually lives.

On a destination=notion install nothing writes notes.db, so a reader that only
consults notes.db silently sees nothing — the bug that made every viewer
speaker-rename never reach Notion.
"""

import json
from datetime import datetime, timezone

from plaud_worker.meeting_store import load_meeting, save_meeting
from plaud_worker.models import Attendee, Meeting, TranscriptTurn
from plaud_worker.notes_store import NotesStore


def _meeting(rid="rec1", speaker="Guest 1"):
    return Meeting(
        recording_id=rid,
        title="T",
        recorded_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
        audio_path=f"/tmp/{rid}.mp3",
        attendees=[Attendee(name=speaker)],
        transcript=[TranscriptTurn(speaker, "hi")],
    )


def _write_json_cache(state, meeting):
    d = state / "meetings"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{meeting.recording_id}.json").write_text(json.dumps(meeting.to_dict()))
    return d / f"{meeting.recording_id}.json"


def test_loads_from_json_cache_when_notes_db_absent(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    _write_json_cache(state, _meeting())

    loaded = load_meeting(state, "rec1")

    assert loaded is not None, "notion-destination install has no notes.db"
    assert loaded.transcript[0].speaker == "Guest 1"


def test_loads_from_json_cache_when_notes_db_exists_but_is_empty(tmp_path):
    """The real shape of this install: notes.db present, zero rows."""
    state = tmp_path / "state"
    state.mkdir()
    NotesStore(state / "notes.db").close()  # creates the schema, no rows
    _write_json_cache(state, _meeting())

    loaded = load_meeting(state, "rec1")

    assert loaded is not None
    assert loaded.recording_id == "rec1"


def test_notes_db_wins_when_both_present(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    ns = NotesStore(state / "notes.db")
    ns.upsert(_meeting(speaker="FromDb"), audio_rel_path="rec1.mp3")
    ns.close()
    _write_json_cache(state, _meeting(speaker="FromJson"))

    assert load_meeting(state, "rec1").transcript[0].speaker == "FromDb"


def test_returns_none_when_nothing_stored(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    assert load_meeting(state, "missing") is None


def test_corrupt_json_cache_is_not_fatal(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    d = state / "meetings"
    d.mkdir()
    (d / "rec1.json").write_text('{"recording_id": "rec1"')  # truncated

    assert load_meeting(state, "rec1") is None


def test_save_round_trips_through_the_json_cache(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    path = _write_json_cache(state, _meeting())

    m = load_meeting(state, "rec1")
    m.transcript[0].speaker = "Rajeev"
    m.attendees[0].name = "Rajeev"
    save_meeting(state, m)

    assert json.loads(path.read_text())["transcript"][0]["speaker"] == "Rajeev"
    assert load_meeting(state, "rec1").attendees[0].name == "Rajeev"


def test_save_does_not_create_a_notes_db_row_on_a_json_only_install(tmp_path):
    """A notion-destination install must not sprout a half-populated notes.db."""
    state = tmp_path / "state"
    state.mkdir()
    NotesStore(state / "notes.db").close()
    _write_json_cache(state, _meeting())

    save_meeting(state, load_meeting(state, "rec1"))

    ns = NotesStore(state / "notes.db")
    try:
        assert ns.get("rec1") is None
    finally:
        ns.close()


def test_save_updates_notes_db_when_the_row_exists(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    ns = NotesStore(state / "notes.db")
    ns.upsert(_meeting(), audio_rel_path="rec1.mp3")
    ns.close()

    m = load_meeting(state, "rec1")
    m.transcript[0].speaker = "Rajeev"
    save_meeting(state, m)

    ns = NotesStore(state / "notes.db")
    try:
        assert ns.get("rec1").transcript[0].speaker == "Rajeev"
    finally:
        ns.close()


def test_save_never_mints_a_cache_for_an_unprocessed_recording(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    save_meeting(state, _meeting())
    assert not (state / "meetings" / "rec1.json").exists()
