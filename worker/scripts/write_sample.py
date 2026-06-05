"""Render ONE sample meeting into the Circleback template on the TEST page.

Uses real metadata (title / recorded_at / duration) from a Riffado recording,
with stub AI content (overview / sections / action items / attendees / transcript)
so we can eyeball template fidelity against the real Circleback notes — before
the transcription + structuring stages exist.

All names/content below are fictional placeholders for the template demo.

    PYTHONPATH=src .venv/bin/python scripts/write_sample.py
"""

from __future__ import annotations

from datetime import datetime, timezone

from plaud_worker.config import Settings
from plaud_worker.models import ActionItem, Attendee, Meeting, Section, TranscriptTurn
from plaud_worker.notion import NotionWriter
from plaud_worker.riffado import RiffadoClient


def stub_content(m: Meeting) -> Meeting:
    m.overview = [
        "Team is targeting a prod release for the CRM integration — Dana tests on dev first, then stage, then prod",
        "No major blockers on dev; Sam will coordinate API access and DB setup to unblock testing",
        "The dashboard card design needs a decision call before it can proceed",
    ]
    m.sections = [
        Section(
            "CRM integration testing",
            [
                "Dana hasn't tested the CRM integration yet and wasn't aware of it",
                "Sam explained the integration replaces the previous Excel upload flow — any CRUD in the CRM now syncs directly to the app",
                "This is a production environment — anything created during testing must be deleted immediately",
            ],
        ),
        Section(
            "Dashboard cards",
            [
                "Cards show zero, which is expected — the test account has no data yet",
                "Sam will check on adding test data directly to the DB",
            ],
        ),
    ]
    m.action_items = [
        ActionItem("Sam Rivers", "Set up Dana for CRM integration testing",
                   "Provide API access and auth details; coordinate on the steps."),
        ActionItem("Sam Rivers", "Check on adding test data for dashboard cards",
                   "Confirm whether test data can be added so the cards display."),
        ActionItem(None, "Test the CRM integration and dashboard cards on dev",
                   "Unattributed speaker — this is the case our voiceprint step exists to fix."),
    ]
    m.attendees = [
        Attendee("Sam Rivers", "sam@example.com"),
        Attendee("Dana Sharma", "dana@example.com"),
        Attendee("Robin Park", "robin@example.com"),
        Attendee(None, None),
    ]
    m.transcript = [
        TranscriptTurn("Sam Rivers", "Hi everyone. Dana, did you test the CRM integration and dashboard cards?"),
        TranscriptTurn("Dana Sharma", "I tested login yesterday, but not the CRM integration — I wasn't aware of it."),
        TranscriptTurn("Sam Rivers", "Okay. The cards show zero because the account has no data — which means it's working, it just needs test rows."),
        TranscriptTurn("Speaker 2", "So we can release to stage and then prod once it's tested?"),
        TranscriptTurn("Sam Rivers", "Correct. Test it, then delete any test data immediately since it's a production environment."),
    ]
    return m


def main() -> None:
    s = Settings.load()
    with RiffadoClient(s.riffado_base_url, s.riffado_api_key) as r:
        rec = next(r.list_recordings(limit=1))

    recorded_at = datetime.fromisoformat(rec["recorded_at"].replace("Z", "+00:00"))
    meeting = Meeting(
        recording_id=rec["id"],
        title=rec.get("title") or "Untitled recording",
        recorded_at=recorded_at.astimezone(timezone.utc),
        duration_ms=rec.get("duration_ms"),
        source_url=f"{s.riffado_base_url}/recordings/{rec['id']}",
    )
    meeting = stub_content(meeting)

    with NotionWriter(s.notion_token) as w:
        page_id = w.create_meeting_page(s.notion_parent_page_id, meeting)
        print("created page:", page_id)
        print("open:", w.page_url(page_id))
        print("from recording:", meeting.recording_id, "|", meeting.title)


if __name__ == "__main__":
    main()
