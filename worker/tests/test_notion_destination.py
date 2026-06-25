from datetime import datetime, timezone

import plaud_worker.destinations.notion as notion_mod
from plaud_worker.destinations.notion import NotionDestination
from plaud_worker.models import Meeting


def _meeting(rid="rec-1") -> Meeting:
    return Meeting(
        recording_id=rid,
        title="Standup",
        recorded_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
    )


class _FakeWriter:
    """Records calls; stands in for NotionWriter as a context manager."""

    calls: list[tuple] = []

    def __init__(self, token):
        self.token = token

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def page_exists(self, page_id):
        return page_id == "existing-page"

    def create_meeting_page(self, parent, meeting):
        _FakeWriter.calls.append(("create", parent, meeting.recording_id))
        return "new-page"

    def replace_page_content(self, page_id, meeting):
        _FakeWriter.calls.append(("replace", page_id, meeting.recording_id))


def test_publish_creates_when_no_prior_ref(monkeypatch):
    _FakeWriter.calls = []
    monkeypatch.setattr(notion_mod, "NotionWriter", _FakeWriter)
    ref = NotionDestination("tok", "parent-123").publish(_meeting())
    assert ref == "new-page"
    assert _FakeWriter.calls == [("create", "parent-123", "rec-1")]


def test_publish_updates_in_place_when_prior_page_exists(monkeypatch):
    _FakeWriter.calls = []
    monkeypatch.setattr(notion_mod, "NotionWriter", _FakeWriter)
    ref = NotionDestination("tok", "parent-123").publish(
        _meeting(), prior_ref="existing-page"
    )
    assert ref == "existing-page"
    assert _FakeWriter.calls == [("replace", "existing-page", "rec-1")]


def test_publish_recreates_when_prior_page_gone(monkeypatch):
    _FakeWriter.calls = []
    monkeypatch.setattr(notion_mod, "NotionWriter", _FakeWriter)
    ref = NotionDestination("tok", "parent-123").publish(
        _meeting(), prior_ref="deleted-page"
    )
    assert ref == "new-page"
    assert _FakeWriter.calls == [("create", "parent-123", "rec-1")]
