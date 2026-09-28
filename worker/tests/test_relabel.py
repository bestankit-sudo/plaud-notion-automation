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


def _seed_json_only(state, rid):
    """The real destination=notion shape: empty notes.db, meeting in the JSON cache."""
    NotesStore(state / "notes.db").close()  # schema only, zero rows
    md = state / "meetings"
    md.mkdir(parents=True, exist_ok=True)
    m = Meeting(recording_id=rid, title="T", recorded_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
                transcript=[TranscriptTurn("Guest 1", "hi")])
    (md / f"{rid}.json").write_text(json.dumps(m.to_dict()))
    lg = Ledger(state / "ledger.db"); lg.upsert(rid, notion_page_id="page-" + rid, status="done"); lg.close()
    qd = state / "relabel_queue"; qd.mkdir(parents=True, exist_ok=True)
    (qd / f"{rid}.json").write_text(json.dumps({"recording_id": rid}))


def test_re_render_for_publishes_when_only_the_json_cache_exists(tmp_path):
    """Regression: notes.db is empty on a notion install, so re-publishes
    silently no-opped and viewer renames never reached Notion."""
    state = tmp_path / "state"; state.mkdir()
    _seed_json_only(state, "rec1")
    settings = type("S", (), {"state_dir": state})()
    w = FakeWriter()
    lg = Ledger(state / "ledger.db")
    assert relabel.re_render_for("rec1", settings, w, lg) is True
    lg.close()
    assert w.calls == [("page-rec1", "rec1")]


def test_drain_publishes_and_clears_queue_for_a_json_only_meeting(tmp_path):
    state = tmp_path / "state"; state.mkdir()
    _seed_json_only(state, "rec1")
    published = []

    class _W:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def replace_page_content(self, pid, m): published.append((pid, m.recording_id))

    import plaud_worker.notion as notion_mod
    orig = notion_mod.NotionWriter
    notion_mod.NotionWriter = lambda *a, **k: _W()
    try:
        settings = type("S", (), {"state_dir": state, "destination": "notion",
                                  "notion_token": "tok"})()
        assert relabel.drain_relabel_queue(settings) == 1
    finally:
        notion_mod.NotionWriter = orig

    assert published == [("page-rec1", "rec1")]
    assert not (state / "relabel_queue" / "rec1.json").exists()
