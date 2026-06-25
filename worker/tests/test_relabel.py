import json
from datetime import datetime, timezone

from plaud_worker import relabel
from plaud_worker.ledger import Ledger
from plaud_worker.models import Meeting, TranscriptTurn
from plaud_worker.notes_store import NotesStore


class FakeWriter:
    def __init__(self): self.calls = []
    def replace_page_content(self, page_id, meeting): self.calls.append((page_id, meeting.recording_id))


def _seed(state, rid):
    ns = NotesStore(state / "notes.db")
    ns.upsert(Meeting(recording_id=rid, title="T", recorded_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
                      transcript=[TranscriptTurn("Akash Jain", "hi")]), audio_rel_path=f"{rid}.mp3")
    ns.close()
    lg = Ledger(state / "ledger.db"); lg.upsert(rid, notion_page_id="page-" + rid, status="done"); lg.close()
    qd = state / "relabel_queue"; qd.mkdir(parents=True, exist_ok=True)
    (qd / f"{rid}.json").write_text(json.dumps({"recording_id": rid}))


def test_re_render_for_publishes(tmp_path):
    state = tmp_path / "state"; state.mkdir()
    _seed(state, "rec1")
    settings = type("S", (), {"state_dir": state})()
    w = FakeWriter()
    lg = Ledger(state / "ledger.db")
    assert relabel.re_render_for("rec1", settings, w, lg) is True
    lg.close()
    assert w.calls == [("page-rec1", "rec1")]


def test_drain_skips_when_not_notion(tmp_path):
    state = tmp_path / "state"; state.mkdir()
    _seed(state, "rec1")
    settings = type("S", (), {"state_dir": state, "destination": "local", "notion_token": None})()
    assert relabel.drain_relabel_queue(settings) == 0
    assert not (state / "relabel_queue" / "rec1.json").exists()  # queue cleared even when skipped
