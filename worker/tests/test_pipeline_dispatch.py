from datetime import datetime, timezone

import plaud_worker.pipeline as pipeline
from plaud_worker.ledger import Ledger
from plaud_worker.models import Meeting


class _Settings:
    destination = "local"

    def __init__(self, state_dir):
        self.state_dir = state_dir
        self.notion_token = None
        self.notion_parent_page_id = None


def _meeting(rid="rec-1") -> Meeting:
    return Meeting(
        recording_id=rid, title="Standup",
        recorded_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
        audio_path="/abs/rec-1.mp3",
    )


def test_write_meeting_publishes_local_and_records_ref(tmp_path):
    settings = _Settings(tmp_path)
    ledger = Ledger(tmp_path / "ledger.db")
    ref = pipeline._write_meeting(_meeting(), settings, ledger)
    assert ref == "rec-1"
    assert ledger.get_ref("rec-1", "local") == "rec-1"
    assert ledger.get("rec-1").status == "processed"
    ledger.close()


def test_write_meeting_passes_prior_ref(tmp_path, monkeypatch):
    settings = _Settings(tmp_path)
    ledger = Ledger(tmp_path / "ledger.db")
    ledger.set_ref("rec-1", "local", "rec-1")
    seen = {}

    class _Dest:
        name = "local"

        def publish(self, meeting, *, prior_ref=None):
            seen["prior_ref"] = prior_ref
            return "rec-1"

        def close(self):
            seen["closed"] = True

    monkeypatch.setattr(pipeline, "build_destination", lambda s, **kw: _Dest())
    pipeline._write_meeting(_meeting(), settings, ledger)
    assert seen["prior_ref"] == "rec-1"
    assert seen["closed"] is True
    ledger.close()
