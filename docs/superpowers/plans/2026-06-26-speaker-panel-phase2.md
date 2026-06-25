# Speaker Panel — Phase 2 (Plan 2c-P2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`). Verified signature/shape reference: `.superpowers/sdd/2c-build-brief.md`. Phase 1 is merged (the panel + `naming.py` + `speakers_api.py` exist).

**Goal:** Durability for the speaker panel — (1) a **persisted labelmap** (`state/labelmap/{rid}.json`) that authoritatively records the display name shown for each anonymous `SPEAKER_XX` label, written at pipeline time + lazily for legacy meetings; (2) **async identity-keyed back-fill** so naming a voice relabels every PAST meeting where it now clears 0.75; (3) **worker-side Notion re-publish** via a relabel queue the worker drains (the credential-free viewer never touches the Notion token); (4) **Undo** (`delete_prototype` + centroid recompute) for a wrong enroll; (5) **global rename/merge**.

**Architecture:** The persisted labelmap is the source of "what string is currently displayed for label L in meeting X" — back-fill needs it to know the old string to replace (reconstruct alone gives the *new* resolution, not the old display). `naming.py` gains `build_labelmap`/`write_labelmap`/`load_labelmap`/`load_or_reconstruct`. `VoiceprintStore` gains `delete_prototype`/`recompute_centroid` and `enroll` returns the new prototype id. The viewer's name/rename endpoints relabel locally + **enqueue** `state/relabel_queue/{rid}.json` (Notion target only); the worker's `sync_and_reconcile` **drains** that queue via `NotionWriter` (worker-only import — boundary preserved).

**Tech Stack:** Python 3.12, FastAPI, vanilla JS, the Phase-1 speaker stack, `NotionWriter`/`Ledger` (worker), pytest.

## Global Constraints
- macOS/arm64, Python 3.12. App binds 127.0.0.1. **Credential-free viewer boundary stays intact:** the viewer (`app/*`) NEVER imports `NotionWriter`/`pipeline`. Notion re-publish happens ONLY in the worker (`sync_and_reconcile` draining the queue). The viewer's back-fill writes queue files + local caches only.
- Enroll ONLY from `diar_full.embeddings[label]`. Back-fill re-matches by label identity (`store.match` on the embedding) — NEVER a raw string-replace of an ambiguous "Guest N" across meetings.
- The persisted labelmap is authoritative for the current display per label; every relabel (name/back-fill/rename/undo) updates it. `load_or_reconstruct` prefers the persisted file, else reconstructs (faithfully, Phase 1) and writes it once.
- Naming/rename/back-fill/undo all run under the existing `_NAMING_LOCK` for store writes; the async back-fill runs in a daemon thread but is exposed as a synchronous `_backfill(...)` function for tests.
- `delete_prototype` + `recompute_centroid` give true Undo (deleting a prototype alone leaves the centroid polluted — recompute from surviving prototypes, or delete the voiceprint row if none remain).
- DRY, YAGNI, TDD, frequent commits. Worker tests: `cd worker && .venv/bin/python -m pytest`. App tests: `cd app && ../worker/.venv/bin/python -m pytest`.

> **Decomposition:** Plan 2c Phase 2 (of 2), built on merged Phase 1.

---

### Task 1: Persisted labelmap (`naming.py` + pipeline writes it)

**Files:** Modify `worker/src/plaud_worker/naming.py`, `worker/src/plaud_worker/pipeline.py`; Test `worker/tests/test_labelmap.py`.

**Interfaces:** add `build_labelmap(diar, id_map, display, store) -> dict`; `write_labelmap(rid, state_dir, labelmap) -> None` (writes `{"version":1,"labels":labelmap}` to `state/labelmap/{rid}.json`); `load_labelmap(rid, state_dir) -> dict | None`; `load_or_reconstruct(rid, store, state_dir, *, threshold=0.75) -> dict | None` (prefer persisted, else reconstruct + persist). Refactor `reconstruct_labelmap` + `build_labelmap` to share an `_assemble` core.

- [ ] **Step 1: Failing tests** — `worker/tests/test_labelmap.py`:

```python
import json

import numpy as np

from plaud_worker import naming
from plaud_worker.diarize import DiarizationResult, DiarTurn
from plaud_worker.voiceprints import VoiceprintStore


def _diar():
    return DiarizationResult(
        turns=[DiarTurn(0.0, 3.0, "SPEAKER_00"), DiarTurn(3.0, 4.0, "SPEAKER_01")],
        embeddings={"SPEAKER_00": [1.0] + [0.0] * 255, "SPEAKER_01": [0.0, 1.0] + [0.0] * 254},
    )


def test_build_labelmap_shape(tmp_path):
    store = VoiceprintStore(tmp_path / "vp.db")
    store.enroll("Sam", np.array([1.0] + [0.0] * 255, dtype=np.float32))
    lm = naming.build_labelmap(_diar(), {"SPEAKER_00": "Sam", "SPEAKER_01": None},
                               {"SPEAKER_00": "Sam", "SPEAKER_01": "Guest 1"}, store)
    store.close()
    assert lm["SPEAKER_00"] == {"display": "Sam", "name": "Sam", "score": 1.0,
                                "enrolled": True, "total_speech_sec": 3.0}
    assert lm["SPEAKER_01"]["display"] == "Guest 1" and lm["SPEAKER_01"]["enrolled"] is False


def test_write_load_roundtrip(tmp_path):
    naming.write_labelmap("rec1", tmp_path, {"SPEAKER_00": {"display": "Sam"}})
    assert naming.load_labelmap("rec1", tmp_path) == {"SPEAKER_00": {"display": "Sam"}}
    assert naming.load_labelmap("ghost", tmp_path) is None
    saved = json.loads((tmp_path / "labelmap" / "rec1.json").read_text())
    assert saved["version"] == 1


def test_load_or_reconstruct_prefers_persisted(tmp_path):
    store = VoiceprintStore(tmp_path / "vp.db")
    naming.write_labelmap("rec1", tmp_path, {"SPEAKER_00": {"display": "Pinned"}})
    out = naming.load_or_reconstruct("rec1", store, tmp_path)
    store.close()
    assert out["SPEAKER_00"]["display"] == "Pinned"  # used the file, did not reconstruct
```

- [ ] **Step 2:** Run `cd worker && .venv/bin/python -m pytest tests/test_labelmap.py -v` → FAIL.

- [ ] **Step 3:** In `naming.py`, refactor the per-label assembly out of `reconstruct_labelmap` and add the new functions:

```python
def _assemble(diar, id_map, display, store) -> dict:
    out: dict[str, dict] = {}
    for label, emb in diar.embeddings.items():
        name, score = store.match(emb, threshold=0.0)
        total = sum(t.end - t.start for t in diar.turns if t.speaker == label)
        out[label] = {
            "display": display.get(label, label),
            "name": id_map.get(label),
            "score": round(float(score), 4),
            "enrolled": id_map.get(label) is not None,
            "total_speech_sec": round(float(total), 1),
        }
    return out


def build_labelmap(diar, id_map, display, store) -> dict:
    return _assemble(diar, id_map, display, store)


def write_labelmap(rid: str, state_dir, labelmap: dict) -> None:
    d = Path(state_dir) / "labelmap"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{rid}.json").write_text(json.dumps({"version": 1, "labels": labelmap}, ensure_ascii=False))


def load_labelmap(rid: str, state_dir):
    p = Path(state_dir) / "labelmap" / f"{rid}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text()).get("labels")


def load_or_reconstruct(rid: str, store, state_dir, *, threshold: float = 0.75):
    lm = load_labelmap(rid, state_dir)
    if lm is not None:
        return lm
    r = reconstruct_labelmap(rid, store, state_dir, threshold=threshold)
    if r is not None:
        write_labelmap(rid, state_dir, r)
    return r
```

Change `reconstruct_labelmap`'s final block to `return _assemble(diar, id_map, display, store)` (so Phase-1 behavior is unchanged).

- [ ] **Step 4: pipeline writes the labelmap.** In `pipeline.py` `process_recording`, immediately after `display = display_names(labelled, id_map)` (line ~119, BEFORE the loop that overwrites `turn.speaker`), add:

```python
        from .naming import build_labelmap, write_labelmap
        write_labelmap(rid, settings.state_dir, build_labelmap(diar, id_map, display, store))
```

(`diar`, `id_map`, `display`, `store` are all in scope there.)

- [ ] **Step 5:** Run `tests/test_labelmap.py` + `tests/test_naming.py` (Phase-1, must still pass) + full worker suite → PASS. Commit.

---

### Task 2: `VoiceprintStore.delete_prototype` + `recompute_centroid`; `enroll` returns the id

**Files:** Modify `worker/src/plaud_worker/voiceprints.py`; Test `worker/tests/test_voiceprints_undo.py`.

**Interfaces:** `enroll(name, embedding) -> int` (returns the new prototype rowid); `delete_prototype(proto_id: int) -> None` (delete the row then recompute that name's centroid); `recompute_centroid(name: str) -> None` (rebuild the running average from surviving prototypes, or DELETE the voiceprints row if none remain).

- [ ] **Step 1: Failing tests** — `worker/tests/test_voiceprints_undo.py`:

```python
import numpy as np

from plaud_worker.voiceprints import VoiceprintStore


def test_enroll_returns_id_and_delete_recovers(tmp_path):
    s = VoiceprintStore(tmp_path / "vp.db")
    a = np.array([1.0] + [0.0] * 255, dtype=np.float32)
    b = np.array([0.0, 1.0] + [0.0] * 254, dtype=np.float32)
    s.enroll("Sam", a)
    pid = s.enroll("Sam", b)          # a contaminating second sample
    assert isinstance(pid, int)
    # delete the bad prototype -> centroid recomputed from the surviving one
    s.delete_prototype(pid)
    name, score = s.match(a, threshold=0.5)
    assert name == "Sam" and score > 0.99   # clean sample matches again
    # the contaminating sample no longer matches Sam strongly
    assert s.match(b, threshold=0.9)[0] is None
    s.close()


def test_delete_last_prototype_removes_voiceprint(tmp_path):
    s = VoiceprintStore(tmp_path / "vp.db")
    pid = s.enroll("Solo", np.array([1.0] + [0.0] * 255, dtype=np.float32))
    s.delete_prototype(pid)
    assert s.names() == []          # voiceprint row gone when no prototypes remain
    s.close()
```

- [ ] **Step 2:** Run → FAIL (`enroll` returns None; no `delete_prototype`).

- [ ] **Step 3:** In `voiceprints.py`: make `enroll` capture + return the prototype id, and add the two methods:

```python
    def enroll(self, name: str, embedding) -> int:
        new = _norm(embedding)
        cur = self._conn.execute(
            "INSERT INTO prototypes (name, embedding) VALUES (?, ?)", (name, new.tobytes())
        )
        proto_id = cur.lastrowid
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
        return proto_id

    def recompute_centroid(self, name: str) -> None:
        """Rebuild `name`'s centroid from its surviving prototypes (or drop the
        voiceprint row if none remain). Used to recover from a bad enroll."""
        rows = self._conn.execute(
            "SELECT embedding FROM prototypes WHERE name = ?", (name,)
        ).fetchall()
        if not rows:
            self._conn.execute("DELETE FROM voiceprints WHERE name = ?", (name,))
            self._conn.commit()
            return
        vecs = [np.frombuffer(r["embedding"], dtype=np.float32) for r in rows]
        avg = _norm(np.mean(vecs, axis=0))
        self._conn.execute(
            "UPDATE voiceprints SET embedding=?, n=?, updated_at=datetime('now') WHERE name=?",
            (avg.tobytes(), len(rows), name),
        )
        self._conn.commit()

    def delete_prototype(self, proto_id: int) -> None:
        row = self._conn.execute(
            "SELECT name FROM prototypes WHERE id = ?", (proto_id,)
        ).fetchone()
        if not row:
            return
        name = row["name"]
        self._conn.execute("DELETE FROM prototypes WHERE id = ?", (proto_id,))
        self._conn.commit()
        self.recompute_centroid(name)
```

- [ ] **Step 4:** Run the undo tests + full worker suite → PASS. Commit.

---

### Task 3: speakers_api uses the labelmap; name endpoint updates it + richer audit

**Files:** Modify `app/speakers_api.py`; Test `app/tests/test_speakers_api.py`.

**Interfaces:** `meeting_speakers` reads via `load_or_reconstruct`. `name_speaker` body becomes `{name: str, scope: 'all'|'this' = 'all'}`; it captures `old_display` from the labelmap BEFORE enroll, enrolls (capturing `proto_id`), relabels locally, **updates the labelmap** (`labelmap[label] = {display:name, name:name, enrolled:True, ...}` then `write_labelmap`), and logs `{ts, rid, label, name, old_display, proto_id, scope, action}`. (The back-fill kick is added in Task 4.)

- [ ] **Step 1: Failing tests** — add to `app/tests/test_speakers_api.py`:

```python
def test_meeting_speakers_uses_persisted_labelmap(state):
    _seed_meeting(state, "rec1")
    from plaud_worker import naming
    naming.write_labelmap("rec1", state, {"SPEAKER_00": {"label": "SPEAKER_00", "display": "Pinned Name",
                                                          "name": "Pinned Name", "score": 0.9,
                                                          "enrolled": True, "total_speech_sec": 3.0}})
    c = _client(state)
    byl = {s["label"]: s for s in c.get("/api/meetings/rec1/speakers").json()["speakers"]}
    assert byl["SPEAKER_00"]["display"] == "Pinned Name"


def test_name_updates_labelmap_and_logs_proto(state):
    _seed_meeting(state, "rec1")
    _seed_notes(state, "rec1", "Guest 1")
    c = _client(state)
    c.post("/api/meetings/rec1/speakers/SPEAKER_01/name", json={"name": "Akash Jain", "scope": "this"})
    from plaud_worker import naming
    lm = naming.load_labelmap("rec1", state)
    assert lm["SPEAKER_01"]["display"] == "Akash Jain" and lm["SPEAKER_01"]["enrolled"] is True
    import json as _j
    last = [_j.loads(x) for x in (state / "speaker_log.jsonl").read_text().splitlines()][-1]
    assert last["old_display"] == "Guest 1" and isinstance(last["proto_id"], int) and last["scope"] == "this"
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Update `app/speakers_api.py`:
  - `meeting_speakers`: replace `reconstruct_labelmap(...)` with `load_or_reconstruct(rid, store, state_dir(), threshold=0.75)`; build the `speakers` list from the dict the same way (each item `{"label": k, **v}` — note persisted entries may already contain `label`; dedupe by using `{"label": k, **{x:v[x] for x in v if x!='label'}}`).
  - Import `from plaud_worker.naming import load_or_reconstruct, load_labelmap, write_labelmap`.
  - `_NameBody`: add `scope: str = "all"`.
  - `name_speaker`: capture `old_display` via `load_or_reconstruct(rid, store, state_dir())` BEFORE enroll; `proto_id = store.enroll(name, emb)` (None on skip path — keep `proto_id` as `int | None`); after `_apply_relabel`, update the labelmap (`lm = load_or_reconstruct(...) or {}; lm[label] = {"label": label, "display": name, "name": name, "score": ..., "enrolled": True, "total_speech_sec": lm.get(label,{}).get("total_speech_sec",0.0)}; write_labelmap(rid, state_dir(), lm)`); `_append_log` gains `old_display`, `proto_id`, `scope`.
  - Rename Phase-1 `_relabel_local(rid, label, old, name)` to `_apply_relabel(rid, old, name)` (it only needs old+name) and update both the notes.db + meetings json (unchanged logic); the labelmap update lives in `name_speaker` (and the back-fill). Keep it a no-op when `old == name`.

- [ ] **Step 4:** Run the new tests + the Phase-1 naming tests (still green) + full app suite → PASS. Commit.

---

### Task 4: Async identity-keyed back-fill across past meetings

**Files:** Modify `app/speakers_api.py`; Test `app/tests/test_speakers_api.py`.

**Interfaces:** `_destination() -> str` (config.json `destination`, default "local"); `_enqueue_notion(rid)` writes `state/relabel_queue/{rid}.json` (`{"recording_id": rid}`); `_backfill(name, state, *, enqueue_notion) -> dict` (synchronous, testable): for every `meetings/*.json` rid, load its `diar_full` embeddings + `load_or_reconstruct`; for each label where `store.match(emb, 0.0)` resolves to `name` at score ≥ 0.75 AND the labelmap's current `display != name`, `_apply_relabel(rid, old_display, name)` + update that meeting's labelmap + (if `enqueue_notion`) enqueue; detect within-meeting collisions (≥2 labels → same name) and append a `"collision"` warning to `speaker_log.jsonl`; return `{"relabeled":[rids], "collisions":[rids]}`. `name_speaker` (scope=="all") kicks `threading.Thread(target=lambda: _backfill(name, state_dir(), enqueue_notion=_destination()=="notion"), daemon=True).start()` AFTER the local relabel.

- [ ] **Step 1: Failing tests** — add (seed TWO meetings sharing the voice):

```python
def test_backfill_relabels_other_meetings(state):
    # rec1 named in-request (scope this); rec2 has the same voice as Guest, back-filled
    _seed_meeting(state, "rec1"); _seed_notes(state, "rec1", "Guest 1")
    _seed_meeting(state, "rec2"); _seed_notes(state, "rec2", "Guest 1")
    import app.speakers_api as sp
    c = _client(state)
    # enroll SPEAKER_01's voice as Akash on rec1 (scope this so the request doesn't block on backfill)
    c.post("/api/meetings/rec1/speakers/SPEAKER_01/name", json={"name": "Akash Jain", "scope": "this"})
    # now run backfill synchronously and assert rec2 got relabeled
    from plaud_worker.voiceprints import VoiceprintStore  # noqa
    res = sp._backfill("Akash Jain", state, enqueue_notion=False)
    assert "rec2" in res["relabeled"]
    m2 = c.get("/api/meetings/rec2").json()
    assert any(t["speaker"] == "Akash Jain" for t in m2["transcript"])


def test_backfill_enqueues_notion(state):
    _seed_meeting(state, "rec1"); _seed_notes(state, "rec1", "Guest 1")
    import app.speakers_api as sp
    c = _client(state)
    c.post("/api/meetings/rec1/speakers/SPEAKER_01/name", json={"name": "Akash Jain", "scope": "this"})
    sp._backfill("Akash Jain", state, enqueue_notion=True)
    assert (state / "relabel_queue" / "rec1.json").exists()
```

(`_seed_meeting` writes SPEAKER_01 with embedding `[0,1,0,...]`; naming "Akash Jain" enrolls that vector, so SPEAKER_01 in rec2 matches at ~1.0.)

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Implement `_destination`, `_enqueue_notion`, `_backfill` (per the interface above; reuse `_apply_relabel`, `load_or_reconstruct`, `write_labelmap`, `naming.load_diar`). Wire `name_speaker` scope=="all" to spawn the daemon thread. The back-fill opens its own short-lived `VoiceprintStore` under `_NAMING_LOCK` per meeting write.

- [ ] **Step 4:** Run the back-fill tests + full app suite → PASS. Commit.

---

### Task 5: Worker-side Notion re-publish (queue drain)

**Files:** Create `worker/src/plaud_worker/relabel.py`; Modify `worker/scripts/sync_and_reconcile.py`; Test `worker/tests/test_relabel.py`.

**Interfaces:** `re_render_for(rid, settings, writer, ledger) -> bool` — load the meeting from `notes.db` (already locally relabeled), get its `ledger.get(rid).notion_page_id`; if a `writer` and `page_id` exist, `writer.replace_page_content(page_id, meeting)`; return True if re-published. `drain_relabel_queue(settings, *, on_event=lambda m: None) -> int` — glob `state/relabel_queue/*.json`; if `settings.destination != "notion"` or no `settings.notion_token`, delete the files and return 0; else open one `NotionWriter(settings.notion_token)`, `re_render_for` each, delete each queue file, return the count re-published. The worker entry calls it between the sync-sleep and `reconcile()`.

- [ ] **Step 1: Failing tests** — `worker/tests/test_relabel.py` (fake writer; seed notes.db + ledger + queue):

```python
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
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Create `worker/src/plaud_worker/relabel.py` with `re_render_for` + `drain_relabel_queue` (per the interface; `re_render_for` uses `NotesStore(settings.state_dir/"notes.db").get(rid)`; `drain_relabel_queue` opens `NotionWriter` only when `destination=="notion"` and a token is present, and always removes the processed/skip queue files). Then in `worker/scripts/sync_and_reconcile.py`, import `drain_relabel_queue` and call it between the sync-sleep and `reconcile(...)` (with the existing `_log` as `on_event`).

- [ ] **Step 4:** Run `tests/test_relabel.py` + full worker suite → PASS. Commit.

---

### Task 6: Undo + global rename + UI

**Files:** Modify `app/speakers_api.py`, `app/web/app.js`, `app/web/style.css`; Test `app/tests/test_speakers_api.py`.

**Interfaces:**
- `POST /api/speakers/undo` → reads the last `speaker_log.jsonl` entry with `action=="enroll"`; `delete_prototype(proto_id)` (+ `recompute_centroid`); reverts the current meeting's relabel (`_apply_relabel(rid, name, old_display)` + labelmap update back to `old_display`/enrolled-false); logs `action="undo"`; returns `{"ok":True,"reverted":rid}`. (Other back-filled meetings re-resolve to Guest on their next render — documented.)
- `POST /api/speakers/rename` body `{old, new}` → under `_NAMING_LOCK`, `store.rename(old, new)`, kick `_backfill(new, ...)`; returns `{"ok":True}`.
- UI: after a successful Save, show an **Undo** link in the row status (calls `/api/speakers/undo`, then re-renders). A small "rename" affordance on enrolled rows that POSTs `/api/speakers/rename` `{old: sp.display, new: input}`.

- [ ] **Step 1: Failing tests** — add:

```python
def test_undo_removes_enrollment(state):
    _seed_meeting(state, "rec1"); _seed_notes(state, "rec1", "Guest 1")
    c = _client(state)
    c.post("/api/meetings/rec1/speakers/SPEAKER_01/name", json={"name": "Akash Jain", "scope": "this"})
    assert "Akash Jain" in [s["name"] for s in c.get("/api/speakers").json()["speakers"]]
    r = c.post("/api/speakers/undo")
    assert r.status_code == 200 and r.json()["reverted"] == "rec1"
    # the voice is no longer enrolled, and the meeting reverted to Guest 1
    assert "Akash Jain" not in [s["name"] for s in c.get("/api/speakers").json()["speakers"]]
    m = c.get("/api/meetings/rec1").json()
    assert any(t["speaker"] == "Guest 1" for t in m["transcript"])


def test_global_rename_merges(state):
    _seed_meeting(state, "rec1")
    from plaud_worker.voiceprints import VoiceprintStore
    s = VoiceprintStore(state / "voiceprints.db"); s.enroll("Speaker A", __import__("numpy").array([1.0]+[0.0]*255, dtype="float32")); s.close()
    c = _client(state)
    assert c.post("/api/speakers/rename", json={"old": "Speaker A", "new": "Rajeev"}).status_code == 200
    assert "Rajeev" in [x["name"] for x in c.get("/api/speakers").json()["speakers"]]
    assert "Speaker A" not in [x["name"] for x in c.get("/api/speakers").json()["speakers"]]
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Implement the two endpoints in `app/speakers_api.py` (under `_NAMING_LOCK`; reuse `delete_prototype`, `store.rename`, `_apply_relabel`, `_backfill`, the labelmap helpers, `_append_log`). Add the Undo link + rename affordance to `app/web/app.js` `speakerRow` (Undo shown in `.spk-status` after Save; rename via a small button on enrolled rows). All dynamic text via `textContent`. Style in `style.css`.

- [ ] **Step 4:** Run the undo/rename tests + full app suite → PASS. Playwright re-demo: name a voice, Undo reverts it; rename merges. Commit.

---

## Self-Review
- Persisted labelmap (authoritative current display) → Task 1; Undo store primitives → Task 2; labelmap-driven name endpoint → Task 3; async identity-keyed back-fill + Notion enqueue → Task 4; worker-side Notion drain (credential-free boundary) → Task 5; Undo + global rename + UI → Task 6. ✓
- The three critic must-fixes: (1) Notion-from-viewer → resolved by the queue + worker drain (Task 4 enqueues, Task 5 drains; viewer never imports NotionWriter); (2) faithful legacy reconstruction → Phase 1's faithful `reconstruct_labelmap`, persisted via `load_or_reconstruct`; (3) centroid-snapshot Undo + idempotency → `delete_prototype`+`recompute_centroid` (Task 2) + the Phase-1 idempotency guard. ✓
- Collision warning (Task 4) + the documented Undo-doesn't-revert-other-backfilled-meetings limitation are called out. ✓
