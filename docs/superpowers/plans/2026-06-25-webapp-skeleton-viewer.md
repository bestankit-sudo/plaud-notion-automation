# Web App Skeleton + Viewer (Plan 2a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local web app (`./run` → FastAPI on 127.0.0.1) that displays the meeting notes already in `state/notes.db` — a searchable list, a per-meeting detail view with a playable audio embed, overview, sections, action items, attendees, and transcript.

**Architecture:** New top-level `app/` (FastAPI backend + a no-build vanilla-JS frontend) that imports the existing `plaud_worker` package as a library (read-only: `NotesStore`, `AppConfig`, `Meeting`). A `./run` bash bootstrap gates on macOS/Apple-Silicon, ensures the shared `worker/.venv`, installs the minimal server deps, and launches uvicorn. The viewer requires **no** credentials — it only reads the local SQLite store written by the worker.

**Tech Stack:** Python 3.12, FastAPI + uvicorn (new), the existing `plaud_worker` package, vanilla HTML/JS (no bundler), pytest + FastAPI `TestClient`.

## Global Constraints

- Target is **macOS on Apple Silicon (arm64), Python 3.12** — the bootstrap hard-gates on this and refuses elsewhere.
- The app **reuses the existing `worker/.venv`** (Plan 1's virtualenv); server deps (`fastapi`, `uvicorn`) are added there. No second venv.
- The viewer is **read-only and credential-free**: it resolves the state dir and reads `state/notes.db` directly; it must **not** call `Settings.load()` (which requires `RIFFADO_*` etc.).
- App binds to **127.0.0.1** only.
- Audio is served from `<state>/audio/<recording_id>.mp3` (the pipeline's naming convention). The audio endpoint must reject path traversal.
- `plaud_worker` read surface (do not modify it): `NotesStore(db_path)` → `list_summaries() -> list[dict]` (keys `recording_id`, `title`, `recorded_at`, `duration_ms`), `get(recording_id) -> Meeting | None`, `close()`; `Meeting.to_dict()` (keys: `recording_id`, `title`, `recorded_at`, `duration_ms`, `source_url`, `audio_path`, `overview`, `sections[{heading,bullets}]`, `action_items[{owner,task,description}]`, `attendees[{name,email}]`, `transcript[{speaker,text}]`) and the `Meeting.duration_label` property; `AppConfig.load(state_dir) -> AppConfig` (has `.destination`).
- DRY, YAGNI, TDD, frequent commits.

> **Decomposition note:** This is Plan **2a** of the web app. Plan 2b (the setup wizard: installers, Riffado standup, destination + provider/model pickers, launchd generation) and Plan 2c (the speaker-naming panel) build on this skeleton and are separate plans. 2a deliberately ships a working read-only viewer over the existing `notes.db`.

---

### Task 0: App scaffold

**Files:**
- Create: `app/requirements.txt`
- Create: `app/pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/tests/__init__.py`
- Create: `app/tests/conftest.py`
- Create: `app/tests/test_scaffold.py`

**Interfaces:**
- Consumes: the existing `worker/.venv` and `worker/src/plaud_worker`.
- Produces: `cd app && ../worker/.venv/bin/python -m pytest` runs, with `app.*` importable (pythonpath includes the repo root) and `plaud_worker` importable (pythonpath includes `../worker/src`).

- [ ] **Step 1: Create the server requirements**

Create `app/requirements.txt`:

```text
# Local web app (wizard + viewer) server deps. Installed into the shared
# worker/.venv. The heavy ML stack stays in worker/requirements-ml.txt.
fastapi>=0.110
uvicorn>=0.29
```

- [ ] **Step 2: Create the pytest config**

Create `app/pyproject.toml` (`..` puts the repo root on the path so `import app.<mod>` resolves; `../worker/src` for `plaud_worker`):

```toml
[tool.pytest.ini_options]
pythonpath = ["..", "../worker/src"]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 3: Create the package + tests package**

Create `app/__init__.py` (empty file).
Create `app/tests/__init__.py` (empty file).
Create `app/tests/conftest.py`:

```python
"""Shared fixtures for the app tests. `pythonpath` in app/pyproject.toml makes
both `app.*` and `plaud_worker` importable; nothing else is needed here yet."""
```

- [ ] **Step 4: Write a scaffold smoke test**

Create `app/tests/test_scaffold.py`:

```python
def test_fastapi_and_worker_importable():
    import fastapi  # noqa: F401
    import plaud_worker  # noqa: F401
```

- [ ] **Step 5: Install server deps into the shared venv and run it**

Run:
```bash
cd worker && .venv/bin/pip install -r ../app/requirements.txt
cd ../app && ../worker/.venv/bin/python -m pytest tests/test_scaffold.py -v
```
Expected: PASS (`test_fastapi_and_worker_importable`).

- [ ] **Step 6: Commit**

```bash
git add app/requirements.txt app/pyproject.toml app/__init__.py app/tests/
git commit -m "test: app scaffold (FastAPI deps + pytest harness)"
```

---

### Task 1: Platform gate

**Files:**
- Create: `app/platform_check.py`
- Test: `app/tests/test_platform_check.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `is_supported() -> bool` (True iff `sys.platform == "darwin"` and `platform.machine() == "arm64"`); `assert_supported() -> None` (prints a clear message to stderr and `raise SystemExit(1)` when unsupported). Runnable as `python platform_check.py` (gates, then prints `platform OK: macOS/arm64`).

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_platform_check.py`:

```python
import platform
import sys

import pytest

from app import platform_check


def test_supported_on_darwin_arm64(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    assert platform_check.is_supported() is True


def test_unsupported_on_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert platform_check.is_supported() is False


def test_unsupported_on_intel_mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert platform_check.is_supported() is False


def test_assert_supported_exits_when_unsupported(monkeypatch):
    monkeypatch.setattr(platform_check, "is_supported", lambda: False)
    with pytest.raises(SystemExit) as exc:
        platform_check.assert_supported()
    assert exc.value.code == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_platform_check.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.platform_check'`.

- [ ] **Step 3: Implement the gate**

Create `app/platform_check.py`:

```python
"""Hard gate: this app only runs on macOS / Apple Silicon (the local Whisper +
launchd stack is arm64-only). Used by the ./run bootstrap and importable for tests."""

from __future__ import annotations

import platform
import sys


def is_supported() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def assert_supported() -> None:
    if not is_supported():
        sys.stderr.write(
            "plaudautomation requires macOS on Apple Silicon (arm64). "
            f"Detected: {sys.platform}/{platform.machine()}.\n"
        )
        raise SystemExit(1)


if __name__ == "__main__":
    assert_supported()
    print("platform OK: macOS/arm64")
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_platform_check.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/platform_check.py app/tests/test_platform_check.py
git commit -m "feat: macOS/arm64 platform gate"
```

---

### Task 2: Path resolution

**Files:**
- Create: `app/paths.py`
- Test: `app/tests/test_paths.py`

**Interfaces:**
- Consumes: nothing (does NOT import `plaud_worker.config`).
- Produces: `state_dir() -> Path` (`WORKER_STATE_DIR` env if set, else `<repo>/worker/state`), `notes_db() -> Path` (`state_dir()/"notes.db"`), `audio_dir() -> Path` (`state_dir()/"audio"`). All read the env at call time (so tests can set it per-request).

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_paths.py`:

```python
from pathlib import Path

from app import paths


def test_state_dir_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_STATE_DIR", str(tmp_path / "st"))
    assert paths.state_dir() == tmp_path / "st"
    assert paths.notes_db() == tmp_path / "st" / "notes.db"
    assert paths.audio_dir() == tmp_path / "st" / "audio"


def test_state_dir_default_is_worker_state(monkeypatch):
    monkeypatch.delenv("WORKER_STATE_DIR", raising=False)
    sd = paths.state_dir()
    assert sd.name == "state"
    assert sd.parent.name == "worker"
    assert paths.notes_db() == sd / "notes.db"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.paths'`.

- [ ] **Step 3: Implement paths**

Create `app/paths.py`:

```python
"""State-dir resolution for the viewer — credential-free (does not import
plaud_worker.config, which requires RIFFADO_* secrets). Mirrors config.py's
WORKER_STATE_DIR / <repo>/worker/state default."""

from __future__ import annotations

import os
from pathlib import Path


def _repo_root() -> Path:
    # app/ lives at <repo>/app — the repo root is its parent.
    return Path(__file__).resolve().parents[1]


def state_dir() -> Path:
    return Path(os.getenv("WORKER_STATE_DIR", _repo_root() / "worker" / "state"))


def notes_db() -> Path:
    return state_dir() / "notes.db"


def audio_dir() -> Path:
    return state_dir() / "audio"
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_paths.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/paths.py app/tests/test_paths.py
git commit -m "feat: credential-free state-dir path resolution for the viewer"
```

---

### Task 3: Viewer API

**Files:**
- Create: `app/server.py`
- Test: `app/tests/test_viewer_api.py`

**Interfaces:**
- Consumes: `app.paths` (Task 2); `plaud_worker.notes_store.NotesStore`; `plaud_worker.appconfig.AppConfig`; `plaud_worker.models.Meeting` (indirectly, via NotesStore).
- Produces: a FastAPI `app` object in `app/server.py` with:
  - `GET /api/meetings` → `{"destination": <str>, "meetings": [{recording_id,title,recorded_at,duration_ms}, ...]}`
  - `GET /api/meetings/{recording_id}` → `Meeting.to_dict()` plus a `duration_label` field; 404 if absent
  - `GET /api/audio/{recording_id}` → the mp3 at `audio_dir()/<recording_id>.mp3` (media type `audio/mpeg`); 404 if missing or if the resolved path escapes `audio_dir()` (traversal guard)

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_viewer_api.py`:

```python
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from plaud_worker.models import ActionItem, Attendee, Meeting, Section, TranscriptTurn
from plaud_worker.notes_store import NotesStore


@pytest.fixture
def client(monkeypatch, tmp_path):
    state = tmp_path / "state"
    (state / "audio").mkdir(parents=True)
    monkeypatch.setenv("WORKER_STATE_DIR", str(state))
    # seed one meeting + its audio file
    store = NotesStore(state / "notes.db")
    store.upsert(
        Meeting(
            recording_id="rec-1",
            title="Patent Strategy",
            recorded_at=datetime(2026, 6, 2, 21, 33, tzinfo=timezone.utc),
            duration_ms=1634000,
            audio_path="/abs/rec-1.mp3",
            overview=["Filed the provisional"],
            sections=[Section("Next steps", ["draft claims"])],
            action_items=[ActionItem("Sam", "Send the spec", "by Fri")],
            attendees=[Attendee("Sam")],
            transcript=[TranscriptTurn("Sam", "hello")],
        ),
        audio_rel_path="rec-1.mp3",
    )
    store.close()
    (state / "audio" / "rec-1.mp3").write_bytes(b"ID3fake-mp3-bytes")
    from app.server import app
    return TestClient(app)


def test_list_meetings(client):
    r = client.get("/api/meetings")
    assert r.status_code == 200
    body = r.json()
    assert body["destination"] in ("notion", "local")
    assert body["meetings"][0]["recording_id"] == "rec-1"
    assert body["meetings"][0]["title"] == "Patent Strategy"


def test_meeting_detail(client):
    r = client.get("/api/meetings/rec-1")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Patent Strategy"
    assert body["overview"] == ["Filed the provisional"]
    assert body["action_items"][0]["owner"] == "Sam"
    assert body["duration_label"]  # non-empty derived label


def test_meeting_detail_404(client):
    assert client.get("/api/meetings/missing").status_code == 404


def test_audio_served(client):
    r = client.get("/api/audio/rec-1")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3fake-mp3-bytes"


def test_audio_missing_404(client):
    assert client.get("/api/audio/nope").status_code == 404


def test_audio_rejects_traversal(client):
    # encoded traversal must not escape the audio dir
    r = client.get("/api/audio/..%2f..%2fsecret")
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_viewer_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.server'`.

- [ ] **Step 3: Implement the viewer API**

Create `app/server.py`:

```python
"""Local web app — Plan 2a serves the read-only notes viewer. Binds to
127.0.0.1 (see ./run). Credential-free: reads state/notes.db directly."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from plaud_worker.appconfig import AppConfig
from plaud_worker.notes_store import NotesStore

from app.paths import audio_dir, notes_db, state_dir

app = FastAPI(title="plaudautomation")

WEB_DIR = Path(__file__).resolve().parent / "web"


@app.get("/api/meetings")
def list_meetings() -> dict:
    store = NotesStore(notes_db())
    try:
        meetings = store.list_summaries()
    finally:
        store.close()
    return {"destination": AppConfig.load(state_dir()).destination, "meetings": meetings}


@app.get("/api/meetings/{recording_id}")
def get_meeting(recording_id: str) -> dict:
    store = NotesStore(notes_db())
    try:
        meeting = store.get(recording_id)
    finally:
        store.close()
    if meeting is None:
        raise HTTPException(status_code=404, detail="meeting not found")
    data = meeting.to_dict()
    data["duration_label"] = meeting.duration_label
    return data


@app.get("/api/audio/{recording_id}")
def get_audio(recording_id: str) -> FileResponse:
    base = audio_dir().resolve()
    path = (base / f"{recording_id}.mp3").resolve()
    # traversal guard: the resolved file must sit directly under audio_dir()
    if base != path.parent or not path.exists():
        raise HTTPException(status_code=404, detail="audio not found")
    return FileResponse(path, media_type="audio/mpeg")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((WEB_DIR / "index.html").read_text())
```

(The `/static` mount for `web/` is added in Task 4, once `web/` exists.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_viewer_api.py -v`
Expected: 5 of 6 PASS; `test_audio_served` and the others pass; the `index` route is not yet exercised. (If `WEB_DIR/index.html` is missing, only the `GET /` route would fail — and no test here calls `/`, so all 6 pass.)

- [ ] **Step 5: Commit**

```bash
git add app/server.py app/tests/test_viewer_api.py
git commit -m "feat: viewer API (meetings list/detail + audio with traversal guard)"
```

---

### Task 4: Viewer frontend

**Files:**
- Create: `app/web/index.html`
- Create: `app/web/app.js`
- Create: `app/web/style.css`
- Modify: `app/server.py` (mount `/static`)
- Test: `app/tests/test_static.py`

**Interfaces:**
- Consumes: the viewer API (Task 3).
- Produces: `GET /` returns the viewer HTML; `GET /static/app.js` and `GET /static/style.css` are served. The page lists meetings and, on click, shows the detail with an audio player.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_static.py`:

```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_STATE_DIR", str(tmp_path / "state"))
    from app.server import app
    return TestClient(app)


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "plaudautomation" in r.text


def test_static_js_served(client):
    r = client.get("/static/app.js")
    assert r.status_code == 200
    assert "/api/meetings" in r.text
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_static.py -v`
Expected: FAIL — `GET /` raises (no `web/index.html`) and `/static/...` 404s (no mount yet).

- [ ] **Step 3: Create the frontend files**

Create `app/web/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>plaudautomation — meeting notes</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <header>
    <h1>plaudautomation</h1>
    <span id="destination" class="badge"></span>
  </header>
  <main>
    <aside id="list" aria-label="Meetings"></aside>
    <section id="detail"><p class="empty">Select a meeting.</p></section>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
```

Create `app/web/app.js`:

```javascript
async function loadList() {
  const res = await fetch("/api/meetings");
  const { destination, meetings } = await res.json();
  document.getElementById("destination").textContent = destination;
  const list = document.getElementById("list");
  list.innerHTML = "";
  if (!meetings.length) {
    list.innerHTML = '<p class="empty">No meetings yet.</p>';
    return;
  }
  for (const m of meetings) {
    const el = document.createElement("button");
    el.className = "row";
    const when = new Date(m.recorded_at).toLocaleString();
    el.innerHTML = `<span class="row-title"></span><span class="row-when">${when}</span>`;
    el.querySelector(".row-title").textContent = m.title;
    el.onclick = () => loadDetail(m.recording_id, el);
    list.appendChild(el);
  }
}

async function loadDetail(rid, rowEl) {
  document.querySelectorAll(".row.active").forEach((r) => r.classList.remove("active"));
  if (rowEl) rowEl.classList.add("active");
  const res = await fetch(`/api/meetings/${encodeURIComponent(rid)}`);
  const detail = document.getElementById("detail");
  if (!res.ok) {
    detail.innerHTML = '<p class="empty">Could not load meeting.</p>';
    return;
  }
  const m = await res.json();
  const parts = [];
  parts.push(`<h2></h2>`);
  parts.push(`<p class="meta">${m.duration_label || ""}</p>`);
  parts.push(`<audio controls src="/api/audio/${encodeURIComponent(rid)}"></audio>`);
  if (m.overview?.length) {
    parts.push("<h3>Overview</h3><ul>" + m.overview.map(li).join("") + "</ul>");
  }
  for (const s of m.sections || []) {
    parts.push(`<h3 class="sec"></h3><ul>` + (s.bullets || []).map(li).join("") + "</ul>");
  }
  if (m.action_items?.length) {
    parts.push("<h3>Action Items</h3><ul>");
    for (const a of m.action_items) {
      const owner = a.owner ? `<strong></strong>: ` : "";
      parts.push(`<li class="ai" data-owner="${a.owner || ""}">${owner}<span class="task"></span></li>`);
    }
    parts.push("</ul>");
  }
  if (m.attendees?.length) {
    parts.push("<h3>Attendees</h3><ul>" + m.attendees.map((a) => li(a.name || "—")).join("") + "</ul>");
  }
  if (m.transcript?.length) {
    parts.push('<h3>Transcript</h3><div class="transcript"></div>');
  }
  detail.innerHTML = parts.join("");
  detail.querySelector("h2").textContent = m.title;
  // fill section headings + action item text safely (avoid HTML injection)
  const secHeads = detail.querySelectorAll("h3.sec");
  (m.sections || []).forEach((s, i) => { if (secHeads[i]) secHeads[i].textContent = s.heading; });
  detail.querySelectorAll("li.ai").forEach((liEl, i) => {
    const a = m.action_items[i];
    const strong = liEl.querySelector("strong");
    if (strong) strong.textContent = a.owner;
    liEl.querySelector(".task").textContent = a.task;
  });
  const tx = detail.querySelector(".transcript");
  if (tx) {
    for (const t of m.transcript) {
      const p = document.createElement("p");
      const b = document.createElement("strong");
      b.textContent = (t.speaker || "Speaker") + ": ";
      p.appendChild(b);
      p.appendChild(document.createTextNode(t.text));
      tx.appendChild(p);
    }
  }
}

function li(text) {
  const d = document.createElement("li");
  d.textContent = text;
  return d.outerHTML;
}

loadList();
```

Create `app/web/style.css`:

```css
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 -apple-system, system-ui, sans-serif; color: #1c1c1c; }
header { display: flex; align-items: center; gap: 12px; padding: 12px 20px; border-bottom: 1px solid #e5e5e5; }
header h1 { font-size: 18px; margin: 0; }
.badge { font-size: 12px; background: #eef; color: #335; padding: 2px 8px; border-radius: 10px; }
main { display: grid; grid-template-columns: 320px 1fr; height: calc(100vh - 53px); }
#list { overflow-y: auto; border-right: 1px solid #e5e5e5; }
.row { display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left; background: none; border: 0; border-bottom: 1px solid #f0f0f0; padding: 10px 16px; cursor: pointer; }
.row:hover { background: #fafafa; }
.row.active { background: #eef; }
.row-title { font-weight: 600; }
.row-when { font-size: 12px; color: #888; }
#detail { overflow-y: auto; padding: 20px 28px; }
#detail h2 { margin-top: 0; }
.meta { color: #888; font-size: 13px; }
audio { width: 100%; margin: 8px 0 16px; }
.transcript p { margin: 4px 0; }
.empty { color: #999; }
```

- [ ] **Step 4: Mount the static directory**

In `app/server.py`, add the import at the top with the other FastAPI imports (it's already imported — confirm `from fastapi.staticfiles import StaticFiles` is present), then append this line at the END of the file (after the `index` route, so the mount picks up the existing `web/` dir):

```python
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_static.py tests/test_viewer_api.py -v`
Expected: PASS (both static tests + all 6 viewer tests).

- [ ] **Step 6: Commit**

```bash
git add app/web/ app/server.py app/tests/test_static.py
git commit -m "feat: viewer frontend (list + detail + audio) served by the app"
```

---

### Task 5: `./run` bootstrap launcher

**Files:**
- Create: `run` (repo root, executable)
- Test: covered by a syntax check + the Task 1 gate unit tests (a bash launcher isn't unit-tested; its only logic seam, the platform gate, is tested in Task 1).

**Interfaces:**
- Consumes: `app/platform_check.py` (Task 1), the shared `worker/.venv`, `app/requirements.txt`, `app/server.py`.
- Produces: a `./run` script that gates on macOS/arm64, ensures the venv + server deps, and launches uvicorn on `127.0.0.1:8787`, opening the browser.

- [ ] **Step 1: Create the bootstrap script**

Create `run` at the repo root:

```bash
#!/usr/bin/env bash
# plaudautomation launcher — gates on macOS/Apple Silicon, ensures the shared
# worker/.venv + server deps, then launches the local web app on 127.0.0.1.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd -P)"
VENV="$ROOT/worker/.venv"
PORT="${PLAUD_PORT:-8787}"

# 1. Hardware gate (macOS / arm64). platform_check exits 1 with a message otherwise.
if [ ! -x "$VENV/bin/python" ]; then
  command -v python3 >/dev/null 2>&1 || { echo "python3 not found — install it (brew install python@3.12)"; exit 1; }
  python3 -m venv "$VENV"
fi
PYTHONPATH="$ROOT/app" "$VENV/bin/python" -m app.platform_check >/dev/null

# 2. Ensure server deps in the shared venv (idempotent; quiet if already present).
"$VENV/bin/python" -c "import fastapi, uvicorn" 2>/dev/null || \
  "$VENV/bin/pip" install -q -r "$ROOT/app/requirements.txt"

# 3. Launch the web app and open the browser.
echo "plaudautomation → http://127.0.0.1:$PORT"
( sleep 1; open "http://127.0.0.1:$PORT" >/dev/null 2>&1 || true ) &
cd "$ROOT/app"
exec env PYTHONPATH="$ROOT:$ROOT/worker/src" \
  "$VENV/bin/python" -m uvicorn server:app --host 127.0.0.1 --port "$PORT"
```

Note: uvicorn is launched with `server:app` (cwd `app/`, so `server` resolves) and `PYTHONPATH` containing the repo root (for `app.paths` used inside `server.py` via `from app.paths import ...`) and `worker/src` (for `plaud_worker`). The platform gate is invoked with `PYTHONPATH=app` so `python -m app.platform_check` resolves.

- [ ] **Step 2: Make it executable + syntax-check**

Run:
```bash
chmod +x run
bash -n run && echo "syntax OK"
```
Expected: `syntax OK` (no syntax errors). Do not run `./run` here — it would block on the server and try to open a browser.

- [ ] **Step 3: Sanity-check the gate invocation resolves**

Run:
```bash
cd "$(git rev-parse --show-toplevel)" && PYTHONPATH=app worker/.venv/bin/python -c "import app.platform_check as p; print('gate import OK; supported=' + str(p.is_supported()))"
```
Expected: prints `gate import OK; supported=...` (True on an Apple-Silicon Mac). This confirms the module path the script uses is correct, without launching the server.

- [ ] **Step 4: Commit**

```bash
git add run
git commit -m "feat: ./run bootstrap (platform gate + venv + launch viewer)"
```

---

## Self-Review

**Spec coverage (Plan 2a scope):**
- §3 `app/` package + `run` bootstrap → Tasks 0, 5. ✓
- §8 viewer (list/detail/audio player) + bootstrap (hardware gate, venv, launch, open browser) → Tasks 1, 3, 4, 5. ✓
- §8 "first run = wizard, after = viewer" routing, installers, destination/provider pickers, launchd → **deferred to Plan 2b** (this plan ships the viewer only; the app currently always shows the viewer).
- §9 speaker-naming panel → **deferred to Plan 2c.**
- §12 web/API tests + smoke → Tasks 3, 4, 5 (TestClient API tests; bootstrap syntax + gate sanity). ✓
- Credential-free viewer (§7 decoupling) → Task 2 (`paths.py` avoids `Settings.load()`). ✓

**Placeholder scan:** none — every code/test step has complete content; no TBD/TODO.

**Type/name consistency:** `paths.state_dir()/notes_db()/audio_dir()` defined in Task 2 are used identically in `server.py` (Task 3) and the bootstrap (Task 5). `NotesStore.list_summaries()/get()/close()` and `Meeting.to_dict()`/`duration_label` match the Plan 1 read surface verified against `notes_store.py`/`models.py`. `app.platform_check.is_supported/assert_supported` defined in Task 1 are used by the bootstrap (Task 5) via `python -m app.platform_check`. The `WEB_DIR` and `/static` mount (Task 4) reference the `web/` dir created in the same task.

**Deliberate scope boundaries:** No auth/creds in the viewer (only reads notes.db); the audio endpoint has a traversal guard; the app reuses `worker/.venv`; the bootstrap is shell (its one logic seam — the platform gate — is unit-tested in Python). The wizard and speaker panel are explicitly out of this plan.
