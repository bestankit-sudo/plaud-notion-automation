# Speaker Panel — Phase 1 (Plan 2c-P1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax. A verified signature/shape reference for THIS codebase is at `.superpowers/sdd/2c-build-brief.md` — read it for any exact API/JSON shape.

**Goal:** A viewer "Speaker Key" panel: see each voice in a meeting, play a snippet, type a name → enroll its embedding into `voiceprints.db` so all FUTURE meetings auto-label that voice (the matching already runs at threshold 0.75 in `pipeline.py:133`). Local-first; no Notion writes from the viewer; current-meeting relabel only.

**Architecture:** A pure `worker/src/plaud_worker/naming.py` (no heavy deps at module level) holds `display_names()` (factored out of `pipeline._display_names`) + `reconstruct_labelmap()` — the FAITHFUL bridge from anonymous `SPEAKER_XX` labels (which own the embedding+timing in `state/diar_full/{rid}.json`) to on-screen display names, by replaying `label_segments` + `display_names` over the cached Whisper transcript (`state/transcripts/{rid}.json`) and diarization — the same computation the pipeline did, so it cannot drift. A new `app/speakers_api.py` FastAPI router exposes list/per-meeting/snippet/name endpoints, gated on `speaker_naming_enabled`. `app/web/app.js` renders the panel.

**Tech Stack:** Python 3.12, FastAPI, vanilla JS, `VoiceprintStore`/`identify`/`diarize`/`transcribe` (worker), pytest + `TestClient`. ffmpeg for snippets.

## Global Constraints
- macOS/arm64, Python 3.12. App binds 127.0.0.1.
- **Keep the viewer credential-free.** `naming.py` and everything the viewer imports must stay heavy-dep-free at module level: `diarize`/`transcribe`/`identify`/`voiceprints` import only stdlib+numpy at module scope (torch/pyannote/mlx are lazy inside functions). **Never import `pipeline.py` into the viewer** (it drags summarizer/riffado/destinations). Move `_display_names` into `naming.py` and have `pipeline.py` import it back.
- **Enroll ONLY from `diar_full.embeddings[label]`** (the true 256-d L2-normalized pyannote vector) — NEVER a vector re-extracted from the audio snippet. Snippets are for human listening only (prevents library poisoning).
- `VoiceprintStore` opens a bare `sqlite3.connect` — add `check_same_thread=False` so the viewer can use it from FastAPI's threadpool; open a short-lived store per request and serialize naming writes with a module-level lock.
- ffmpeg via `shutil.which` (clear 500 if missing — the launchd-ffmpeg silent-failure mode is a known risk). Snippet extraction is on-demand + cached; never blocks.
- All viewer DOM writes via `textContent` (no innerHTML with server data). Audio served from `state/` on 127.0.0.1 only, with the existing traversal-guard pattern.
- Phase 1 does NOT write to Notion and does NOT back-fill past meetings (that's Phase 2). Relabel is scoped to the current `rid` only. DRY, YAGNI, TDD, frequent commits. Worker tests: `cd worker && .venv/bin/python -m pytest`. App tests: `cd app && ../worker/.venv/bin/python -m pytest`.

> **Decomposition:** Plan 2c Phase 1 (of 2). Phase 2 (persisted labelmap, async identity-keyed back-fill, worker-side Notion re-publish, centroid-snapshot Undo, global rename) is a separate plan written against merged Phase 1.

---

### Task 1: `naming.py` — factor `display_names` + the faithful `reconstruct_labelmap`

**Files:**
- Create: `worker/src/plaud_worker/naming.py`
- Modify: `worker/src/plaud_worker/pipeline.py` (delete local `_display_names`, import from `naming`)
- Test: `worker/tests/test_naming.py`

**Interfaces:**
- Produces `display_names(turns, id_map) -> dict[str,str]` (anonymous label → "Real Name" or "Guest N", numbered by first appearance over `turns`); `load_diar(path) -> DiarizationResult`; `reconstruct_labelmap(rid, store, state_dir, *, threshold=0.75) -> dict[str, dict] | None` where each value is `{display, name, score, enrolled, total_speech_sec}` and `None` means the diar/transcript cache is missing.
- Consumes: `diarize.{DiarTurn,DiarizationResult,label_segments}`, `transcribe.transcribe_cached`, `identify.identify_speakers`, `voiceprints.VoiceprintStore`.

- [ ] **Step 1: Failing tests** — `worker/tests/test_naming.py`:

```python
import json
from pathlib import Path

import numpy as np

from plaud_worker import naming
from plaud_worker.models import TranscriptTurn
from plaud_worker.voiceprints import VoiceprintStore


def test_display_names_numbers_guests_in_order():
    turns = [TranscriptTurn("SPEAKER_01", "hi"), TranscriptTurn("SPEAKER_00", "yo"),
             TranscriptTurn("SPEAKER_01", "again")]
    out = naming.display_names(turns, {"SPEAKER_01": None, "SPEAKER_00": "Sam"})
    assert out == {"SPEAKER_01": "Guest 1", "SPEAKER_00": "Sam"}


def _seed(state, rid, *, enroll=None):
    (state / "diar_full").mkdir(parents=True, exist_ok=True)
    (state / "transcripts").mkdir(parents=True, exist_ok=True)
    e0 = [1.0] + [0.0] * 255   # SPEAKER_00 embedding
    e1 = [0.0, 1.0] + [0.0] * 254
    (state / "diar_full" / f"{rid}.json").write_text(json.dumps({
        "turns": [{"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
                  {"start": 3.0, "end": 4.0, "speaker": "SPEAKER_01"}],
        "embeddings": {"SPEAKER_00": e0, "SPEAKER_01": e1},
    }))
    (state / "transcripts" / f"{rid}.json").write_text(json.dumps({
        "language": "en", "text": "a b",
        "segments": [{"start": 0.0, "end": 3.0, "text": "hello there"},
                     {"start": 3.0, "end": 4.0, "text": "bye"}],
    }))
    store = VoiceprintStore(state / "voiceprints.db")
    if enroll:
        store.enroll(enroll[0], np.array(enroll[1], dtype=np.float32))
    return store


def test_reconstruct_labelmap_faithful(tmp_path):
    state = tmp_path / "state"
    store = _seed(state, "rec1", enroll=("Sam Rivers", [1.0] + [0.0] * 255))
    lm = naming.reconstruct_labelmap("rec1", store, state, threshold=0.75)
    store.close()
    assert lm["SPEAKER_00"]["name"] == "Sam Rivers"     # matched the enrolled voice
    assert lm["SPEAKER_00"]["enrolled"] is True
    assert lm["SPEAKER_00"]["display"] == "Sam Rivers"
    assert lm["SPEAKER_01"]["name"] is None             # unknown -> Guest
    assert lm["SPEAKER_01"]["display"] == "Guest 1"
    assert lm["SPEAKER_00"]["total_speech_sec"] == 3.0
    assert 0.0 <= lm["SPEAKER_01"]["score"] <= 1.0


def test_reconstruct_labelmap_missing_cache_returns_none(tmp_path):
    state = tmp_path / "state"
    store = VoiceprintStore(state / "voiceprints.db")
    assert naming.reconstruct_labelmap("nope", store, state) is None
    store.close()
```

- [ ] **Step 2:** Run `cd worker && .venv/bin/python -m pytest tests/test_naming.py -v` → FAIL (no module `naming`).

- [ ] **Step 3:** Create `worker/src/plaud_worker/naming.py`:

```python
"""Pure speaker-naming helpers shared by the worker pipeline AND the credential-free
viewer. Keep module-level imports heavy-dep-free (the imported modules below only pull
stdlib+numpy at import time; torch/mlx are lazy inside their functions) so importing
this never drags the ML/summarizer/riffado stack into the web app."""

from __future__ import annotations

import json
from pathlib import Path

from .diarize import DiarTurn, DiarizationResult, label_segments
from .identify import identify_speakers
from .transcribe import transcribe_cached
from .voiceprints import VoiceprintStore


def display_names(turns, id_map: dict[str, str | None]) -> dict[str, str]:
    """Anonymous label -> display name: an identified person, else an ephemeral
    'Guest N' numbered by first appearance over `turns`."""
    display: dict[str, str] = {}
    guest = 0
    for t in turns:
        if t.speaker in display:
            continue
        name = id_map.get(t.speaker)
        if name:
            display[t.speaker] = name
        else:
            guest += 1
            display[t.speaker] = f"Guest {guest}"
    return display


def load_diar(path: Path) -> DiarizationResult:
    d = json.loads(Path(path).read_text())
    return DiarizationResult(
        turns=[DiarTurn(**t) for t in d["turns"]],
        embeddings=d["embeddings"],
    )


def reconstruct_labelmap(rid: str, store: VoiceprintStore, state_dir, *, threshold: float = 0.75):
    """Faithfully recompute {SPEAKER_XX -> {display,name,score,enrolled,total_speech_sec}}
    by replaying label_segments + display_names over the cached whisper transcript and
    diarization — the SAME computation pipeline.py did, so it can't drift. Returns None
    if the diar/transcript cache is missing (caller treats the meeting as play-only)."""
    state_dir = Path(state_dir)
    diar_path = state_dir / "diar_full" / f"{rid}.json"
    tr_path = state_dir / "transcripts" / f"{rid}.json"
    if not diar_path.exists() or not tr_path.exists():
        return None
    diar = load_diar(diar_path)
    tr = transcribe_cached("", cache_path=tr_path)  # cache hit -> no mlx
    seg_turns = label_segments(tr.segments, diar.turns)
    id_map = identify_speakers(diar, store, threshold=threshold)
    display = display_names(seg_turns, id_map)
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
```

- [ ] **Step 4: Repoint pipeline.py.** Delete the local `_display_names` (build-brief §5.2, lines ~66–81), add `from .naming import display_names` with the other `from .` imports, and replace the call site `_display_names(...)` with `display_names(...)`. Run `grep -n "_display_names" worker/src/plaud_worker/pipeline.py` → expect no matches after.

- [ ] **Step 5:** Run `cd worker && .venv/bin/python -m pytest tests/test_naming.py -v` then the full worker suite → PASS. Commit.

```bash
git add worker/src/plaud_worker/naming.py worker/src/plaud_worker/pipeline.py worker/tests/test_naming.py
git commit -m "feat: naming.py — pure display_names + faithful reconstruct_labelmap (viewer-safe)"
```

---

### Task 2: `VoiceprintStore` thread-safety for the viewer

**Files:**
- Modify: `worker/src/plaud_worker/voiceprints.py` (the `sqlite3.connect` line)
- Test: `worker/tests/test_voiceprints_thread.py`

**Interfaces:** no API change; `VoiceprintStore(db_path)` becomes usable from a different thread than it was created on (FastAPI threadpool).

- [ ] **Step 1: Failing test** — `worker/tests/test_voiceprints_thread.py`:

```python
import threading

import numpy as np

from plaud_worker.voiceprints import VoiceprintStore


def test_store_usable_across_threads(tmp_path):
    store = VoiceprintStore(tmp_path / "vp.db")
    err = []

    def work():
        try:
            store.enroll("Sam", np.array([1.0] + [0.0] * 255, dtype=np.float32))
            name, score = store.match(np.array([1.0] + [0.0] * 255, dtype=np.float32), threshold=0.5)
            assert name == "Sam" and score > 0.99
        except Exception as e:  # noqa: BLE001
            err.append(e)

    t = threading.Thread(target=work)
    t.start(); t.join()
    store.close()
    assert not err, err
```

- [ ] **Step 2:** Run → FAIL (`SQLite objects created in a thread can only be used in that same thread`).

- [ ] **Step 3:** In `voiceprints.py` change `sqlite3.connect(db_path)` → `sqlite3.connect(db_path, check_same_thread=False)` (mirror `NotesStore`).

- [ ] **Step 4:** Run the test + full worker suite → PASS. Commit.

---

### Task 3: `app/speakers_api.py` — list + per-meeting speakers (gated)

**Files:**
- Create: `app/speakers_api.py`
- Modify: `app/server.py` (mount the router)
- Test: `app/tests/test_speakers_api.py`

**Interfaces:**
- `GET /api/speakers -> {"speakers":[{"name","samples"}]}` (from `VoiceprintStore.names()`).
- `GET /api/meetings/{rid}/speakers -> {"recording_id","threshold":0.75,"speakers":[{"label","display","name","score","enrolled","total_speech_sec"}]}` (from `reconstruct_labelmap`; empty list if cache missing). Both `404` when `speaker_naming_enabled` is false.
- Module seams: `_vp_store()` opens `VoiceprintStore(state_dir()/"voiceprints.db")`; `_naming_enabled()` reads `state_dir()/config.json`'s `speaker_naming_enabled` (default True).

- [ ] **Step 1: Failing tests** — `app/tests/test_speakers_api.py`:

```python
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def state(tmp_path, monkeypatch):
    s = tmp_path / "state"
    (s / "diar_full").mkdir(parents=True)
    (s / "transcripts").mkdir(parents=True)
    monkeypatch.setenv("WORKER_STATE_DIR", str(s))
    return s


def _seed_meeting(s, rid):
    e0 = [1.0] + [0.0] * 255
    e1 = [0.0, 1.0] + [0.0] * 254
    (s / "diar_full" / f"{rid}.json").write_text(json.dumps({
        "turns": [{"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
                  {"start": 3.0, "end": 4.0, "speaker": "SPEAKER_01"}],
        "embeddings": {"SPEAKER_00": e0, "SPEAKER_01": e1}}))
    (s / "transcripts" / f"{rid}.json").write_text(json.dumps({
        "language": "en", "text": "x",
        "segments": [{"start": 0.0, "end": 3.0, "text": "hello"},
                     {"start": 3.0, "end": 4.0, "text": "bye"}]}))


def _client(s):
    from plaud_worker.voiceprints import VoiceprintStore
    st = VoiceprintStore(s / "voiceprints.db")
    st.enroll("Sam Rivers", np.array([1.0] + [0.0] * 255, dtype=np.float32))
    st.close()
    from app.server import app
    return TestClient(app)


def test_list_speakers(state):
    _seed_meeting(state, "rec1")
    c = _client(state)
    body = c.get("/api/speakers").json()
    assert body["speakers"][0]["name"] == "Sam Rivers"
    assert body["speakers"][0]["samples"] == 1


def test_meeting_speakers(state):
    _seed_meeting(state, "rec1")
    c = _client(state)
    body = c.get("/api/meetings/rec1/speakers").json()
    assert body["threshold"] == 0.75
    byl = {s["label"]: s for s in body["speakers"]}
    assert byl["SPEAKER_00"]["name"] == "Sam Rivers" and byl["SPEAKER_00"]["enrolled"] is True
    assert byl["SPEAKER_01"]["display"] == "Guest 1" and byl["SPEAKER_01"]["name"] is None


def test_meeting_speakers_missing_cache_empty(state):
    c = _client(state)
    body = c.get("/api/meetings/ghost/speakers").json()
    assert body["speakers"] == []


def test_gated_off(state, monkeypatch):
    (state / "config.json").write_text(json.dumps({"speaker_naming_enabled": False}))
    c = _client(state)
    assert c.get("/api/speakers").status_code == 404
    assert c.get("/api/meetings/rec1/speakers").status_code == 404
```

- [ ] **Step 2:** Run `cd app && ../worker/.venv/bin/python -m pytest tests/test_speakers_api.py -v` → FAIL (404 routes / no module).

- [ ] **Step 3:** Create `app/speakers_api.py`:

```python
"""/api speaker-key endpoints (credential-free viewer). Imports only viewer-safe
worker modules (naming/voiceprints — no pipeline). Gated on speaker_naming_enabled."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from app.paths import state_dir
from plaud_worker.naming import reconstruct_labelmap
from plaud_worker.voiceprints import VoiceprintStore

router = APIRouter(prefix="/api")


def _vp_store() -> VoiceprintStore:
    return VoiceprintStore(state_dir() / "voiceprints.db")


def _naming_enabled() -> bool:
    cfg = state_dir() / "config.json"
    if cfg.exists():
        try:
            return bool(json.loads(cfg.read_text()).get("speaker_naming_enabled", True))
        except (ValueError, OSError):
            return True
    return True


def _require_enabled() -> None:
    if not _naming_enabled():
        raise HTTPException(status_code=404, detail="speaker naming disabled")


@router.get("/speakers")
def list_speakers() -> dict:
    _require_enabled()
    store = _vp_store()
    try:
        return {"speakers": [{"name": n, "samples": c} for n, c in store.names()]}
    finally:
        store.close()


@router.get("/meetings/{rid}/speakers")
def meeting_speakers(rid: str) -> dict:
    _require_enabled()
    store = _vp_store()
    try:
        lm = reconstruct_labelmap(rid, store, state_dir(), threshold=0.75)
    finally:
        store.close()
    speakers = [] if lm is None else [{"label": k, **v} for k, v in sorted(lm.items())]
    return {"recording_id": rid, "threshold": 0.75, "speakers": speakers}
```

- [ ] **Step 4: Mount.** In `app/server.py`, add `from app.speakers_api import router as speakers_router` with the other imports and `app.include_router(speakers_router)` after the existing routers. (The existing `/api/meetings/{recording_id}` GET stays; the new `/api/meetings/{rid}/speakers` is a distinct path.)

- [ ] **Step 5:** Run the test + full app suite → PASS. Commit.

---

### Task 4: `GET /api/audio/{rid}/snippet` — per-speaker audio clip

**Files:**
- Modify: `app/speakers_api.py` (add the route + helpers)
- Test: `app/tests/test_speakers_api.py` (add snippet tests)

**Interfaces:** `GET /api/audio/{rid}/snippet?label=SPEAKER_01 -> FileResponse audio/mpeg`. Validates `label` against `^SPEAKER_\d+$` AND presence in `diar_full.embeddings`; picks the longest turns (≤25s / ≤8 segments) for that label; runs ffmpeg `atrim`+`concat` (lifted from `build_snippets._extract`); caches to `state/snippets_panel/{rid}_{label}.mp3`; reuses the `audio_dir()` traversal guard. The ffmpeg call is a module seam `_extract` for tests.

- [ ] **Step 1: Failing tests** — add to `app/tests/test_speakers_api.py`:

```python
import app.speakers_api as sp


def test_snippet_bad_label(state):
    _seed_meeting(state, "rec1")
    c = _client(state)
    assert c.get("/api/audio/rec1/snippet?label=../etc").status_code == 400
    assert c.get("/api/audio/rec1/snippet?label=SPEAKER_99").status_code == 404  # not in meeting


def test_snippet_extracts_and_caches(state, monkeypatch):
    _seed_meeting(state, "rec1")
    (state / "audio").mkdir(parents=True, exist_ok=True)
    (state / "audio" / "rec1.mp3").write_bytes(b"ID3fake")
    calls = []

    def fake_extract(audio, ranges, out):
        calls.append((audio, tuple(ranges), out))
        Path(out).write_bytes(b"ID3snippet")

    monkeypatch.setattr(sp, "_extract", fake_extract)
    monkeypatch.setattr(sp.shutil, "which", lambda _x: "/opt/homebrew/bin/ffmpeg")
    c = _client(state)
    r = c.get("/api/audio/rec1/snippet?label=SPEAKER_00")
    assert r.status_code == 200 and r.content == b"ID3snippet"
    assert (state / "snippets_panel" / "rec1_SPEAKER_00.mp3").exists()
    # second call is cached -> no second extract
    c.get("/api/audio/rec1/snippet?label=SPEAKER_00")
    assert len(calls) == 1
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Add to `app/speakers_api.py` (imports + route):

```python
import re
import shutil
import subprocess

from fastapi.responses import FileResponse

from app.paths import audio_dir

_LABEL_RE = re.compile(r"^SPEAKER_\d+$")
_SNIPPET_TARGET_SECONDS = 25.0
_SNIPPET_MAX_SEGMENTS = 8


def _pick_ranges(turns: list[tuple[float, float]]) -> list[tuple[float, float]]:
    chosen: list[tuple[float, float]] = []
    total = 0.0
    for s, e in sorted(turns, key=lambda r: r[1] - r[0], reverse=True):
        chosen.append((s, e))
        total += e - s
        if total >= _SNIPPET_TARGET_SECONDS or len(chosen) >= _SNIPPET_MAX_SEGMENTS:
            break
    return sorted(chosen)


def _extract(audio: str, ranges: list[tuple[float, float]], out: str) -> None:
    parts, labels = [], []
    for i, (s, e) in enumerate(ranges):
        parts.append(f"[0]atrim={s:.2f}:{e:.2f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[a{i}]")
    flt = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(ranges)}:v=0:a=1[out]"
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio, "-filter_complex", flt, "-map", "[out]", out],
        check=True, capture_output=True,
    )


@router.get("/audio/{rid}/snippet")
def speaker_snippet(rid: str, label: str) -> FileResponse:
    _require_enabled()
    if not _LABEL_RE.match(label):
        raise HTTPException(status_code=400, detail="bad label")
    base = audio_dir().resolve()
    audio = (base / f"{rid}.mp3").resolve()
    if base != audio.parent or not audio.exists():
        raise HTTPException(status_code=404, detail="audio not found")
    diar_path = state_dir() / "diar_full" / f"{rid}.json"
    if not diar_path.exists():
        raise HTTPException(status_code=404, detail="diarization not found")
    d = json.loads(diar_path.read_text())
    if label not in d.get("embeddings", {}):
        raise HTTPException(status_code=404, detail="label not in meeting")
    turns = [(t["start"], t["end"]) for t in d["turns"] if t["speaker"] == label]
    if not turns:
        raise HTTPException(status_code=404, detail="no audio for label")
    out_dir = state_dir() / "snippets_panel"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{rid}_{label}.mp3"
    if not out.exists():
        if not shutil.which("ffmpeg"):
            raise HTTPException(status_code=500, detail="ffmpeg not found")
        try:
            _extract(str(audio), _pick_ranges(turns), str(out))
        except subprocess.CalledProcessError:
            raise HTTPException(status_code=500, detail="snippet extraction failed")
    return FileResponse(out, media_type="audio/mpeg")
```

- [ ] **Step 4:** Run the snippet tests + full app suite → PASS. Commit.

---

### Task 5: `POST /api/meetings/{rid}/speakers/{label}/name` — enroll + local relabel

**Files:**
- Modify: `app/speakers_api.py` (add the route + `_relabel_local` + `_append_log` + lock)
- Test: `app/tests/test_speakers_api.py` (add naming tests)

**Interfaces:** `POST .../name` body `{"name": str}` → enroll `diar_full.embeddings[label]` into the store under `name` (idempotent: skip if this label already matches `name` ≥ 0.75); relabel THIS meeting's `notes.db` + `meetings/{rid}.json` display (replace the label's current display name with `name`, dedup attendees); append a line to `state/speaker_log.jsonl`. Returns `{"ok":True,"enrolled":bool,"name":str}`. No Notion write. Serialized by a module lock.

- [ ] **Step 1: Failing tests** — add to `app/tests/test_speakers_api.py` (needs a seeded `notes.db` meeting):

```python
from datetime import datetime, timezone


def _seed_notes(state, rid, transcript_speaker):
    from plaud_worker.notes_store import NotesStore
    from plaud_worker.models import Meeting, TranscriptTurn, Attendee
    ns = NotesStore(state / "notes.db")
    ns.upsert(Meeting(recording_id=rid, title="T", recorded_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
                      attendees=[Attendee(transcript_speaker)],
                      transcript=[TranscriptTurn(transcript_speaker, "hello")]),
              audio_rel_path=f"{rid}.mp3")
    ns.close()


def test_name_enrolls_and_relabels(state):
    _seed_meeting(state, "rec1")
    _seed_notes(state, "rec1", "Guest 1")  # SPEAKER_01 displays as Guest 1
    c = _client(state)
    r = c.post("/api/meetings/rec1/speakers/SPEAKER_01/name", json={"name": "Akash Jain"})
    assert r.status_code == 200 and r.json()["enrolled"] is True
    # the voice is now enrolled -> appears in the library
    names = [s["name"] for s in c.get("/api/speakers").json()["speakers"]]
    assert "Akash Jain" in names
    # this meeting's transcript was relabeled locally
    m = c.get("/api/meetings/rec1").json()
    assert any(t["speaker"] == "Akash Jain" for t in m["transcript"])
    assert not any(t["speaker"] == "Guest 1" for t in m["transcript"])
    # audit log written
    assert (state / "speaker_log.jsonl").exists()


def test_name_bad_input(state):
    _seed_meeting(state, "rec1")
    c = _client(state)
    assert c.post("/api/meetings/rec1/speakers/BAD/name", json={"name": "X"}).status_code == 400
    assert c.post("/api/meetings/rec1/speakers/SPEAKER_00/name", json={"name": "  "}).status_code == 400
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Add to `app/speakers_api.py`:

```python
import os
import threading
from datetime import datetime, timezone

from pydantic import BaseModel

from app.paths import notes_db
from plaud_worker.models import Meeting
from plaud_worker.notes_store import NotesStore

_NAMING_LOCK = threading.Lock()


class _NameBody(BaseModel):
    name: str


def _append_log(rid: str, label: str, name: str, score: float, action: str) -> None:
    line = json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "rid": rid,
                       "label": label, "name": name, "score": round(float(score), 4), "action": action})
    with (state_dir() / "speaker_log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _relabel_local(rid: str, label: str, name: str) -> None:
    """Replace this meeting's display name for `label` with `name` in notes.db +
    meetings/{rid}.json. Local-only — no Notion. (Notion re-publish is Phase 2.)"""
    store = _vp_store()
    try:
        lm = reconstruct_labelmap(rid, store, state_dir())
    finally:
        store.close()
    if not lm or label not in lm:
        return
    old = lm[label]["display"]
    if old == name:
        return
    ns = NotesStore(notes_db())
    try:
        m = ns.get(rid)
        if m is None:
            return
        for t in m.transcript:
            if t.speaker == old:
                t.speaker = name
        seen, deduped = set(), []
        for a in m.attendees:
            a.name = name if a.name == old else a.name
            if a.name not in seen:
                seen.add(a.name)
                deduped.append(a)
        m.attendees = deduped
        rel = os.path.basename(m.audio_path) if m.audio_path else f"{rid}.mp3"
        ns.upsert(m, audio_rel_path=rel)
    finally:
        ns.close()
    mj = state_dir() / "meetings" / f"{rid}.json"
    if mj.exists():
        mj.write_text(json.dumps(m.to_dict(), ensure_ascii=False))


@router.post("/meetings/{rid}/speakers/{label}/name")
def name_speaker(rid: str, label: str, body: _NameBody) -> dict:
    _require_enabled()
    name = body.name.strip()
    if not name or not _LABEL_RE.match(label):
        raise HTTPException(status_code=400, detail="bad input")
    diar_path = state_dir() / "diar_full" / f"{rid}.json"
    if not diar_path.exists():
        raise HTTPException(status_code=404, detail="diarization not found")
    emb = json.loads(diar_path.read_text()).get("embeddings", {}).get(label)
    if emb is None:
        raise HTTPException(status_code=404, detail="label not in meeting")
    with _NAMING_LOCK:
        store = _vp_store()
        try:
            cur, score = store.match(emb, threshold=0.0)
            already = cur == name and score >= 0.75
            if not already:
                store.enroll(name, emb)
        finally:
            store.close()
        _relabel_local(rid, label, name)
        _append_log(rid, label, name, score, "skip" if already else "enroll")
    return {"ok": True, "enrolled": not already, "name": name}
```

- [ ] **Step 4:** Run the naming tests + full app suite → PASS. Commit.

---

### Task 6: Viewer "Speaker Key" panel UI

**Files:**
- Modify: `app/web/app.js` (render the panel in `loadDetail`), `app/web/style.css`
- Validation: Playwright drive against an isolated tmp state (no unit test for DOM/SSE glue).

**Interfaces:** consumes `GET /api/meetings/{rid}/speakers`, `GET /api/speakers`, `GET /api/audio/{rid}/snippet?label=`, `POST /api/meetings/{rid}/speakers/{label}/name`.

- [ ] **Step 1:** After the transcript renders in `loadDetail` (build-brief §7 / `app.js` ~line 80), fetch `/api/meetings/{rid}/speakers`; if `speakers` non-empty, render a collapsible "Speaker Key" card above the transcript: one row per speaker — `display` name + an "enrolled ✓" or "Guest" badge + the nearest hint (`name ? "" : "sounds like " + best + " " + score`, with a "< 0.75 to auto-label" note); a ▶ "hear" button that lazily sets an `<audio controls>` `src` to `/api/audio/{rid}/snippet?label=...`; a name `<input>` backed by a `<datalist>` populated from `/api/speakers`; a Save button. All text via `textContent`; the `<input>`/`<datalist>` values set via `.value`/option `textContent`.
- [ ] **Step 2:** On Save → `POST /api/meetings/{rid}/speakers/{label}/name {name}`; on success, re-fetch the meeting (or the speakers list) and re-render so the relabel shows. Disable the button while in flight.
- [ ] **Step 3:** Style the card in `style.css` (reuse the existing palette).
- [ ] **Step 4:** Playwright demo against an isolated tmp state seeded with a `diar_full` + `transcripts` + `notes.db` + a `voiceprints.db`: load a meeting → Speaker Key shows the voices → name a Guest → it relabels. Screenshot. (Use a fake/echo ffmpeg or skip the audio play in the demo.)

---

## Self-Review
- Panel (list/per-meeting/snippet/name) + future-auto-label via enroll → Tasks 3–6; the faithful bridge (must-fix #2) → Task 1 `reconstruct_labelmap`; thread-safety → Task 2; first real use of `speaker_naming_enabled` → Task 3 gate. ✓
- Security: viewer stays credential-free (naming.py imports are heavy-dep-free; pipeline never imported); enroll only from `diar_full` embeddings; label regex + traversal guard on the snippet; `textContent` everywhere; no Notion writes. ✓
- **Deferred to Phase 2:** persisted labelmap at pipeline time + legacy backfill script; async identity-keyed back-fill across past meetings; worker-side Notion re-publish (relabel queue drained in `sync_and_reconcile.py`); `delete_prototype` + centroid-snapshot Undo; global rename + collision warnings.
