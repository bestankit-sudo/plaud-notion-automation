# Worker Abstractions (Local destination + provider-pick summaries) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the pipeline write finished meeting notes to a **Local SQLite store** as an alternative to Notion, and summarize via **OpenAI or Anthropic** chosen by config — all CLI-driven and unit-tested, with no web UI.

**Architecture:** Introduce two thin interfaces in the worker — `Destination` (Notion | Local) and `Summarizer` (OpenAI | Anthropic) — plus a non-secret `state/config.json` (`AppConfig`) the future wizard will write. `pipeline.py` stops calling Notion/OpenAI directly and instead resolves a destination and summarizer from config. The proven Whisper/diarize/identify stages are untouched.

**Tech Stack:** Python 3.12, sqlite3 (stdlib), httpx (existing), `openai` (existing), `anthropic` (new), pytest (new, tests only).

## Global Constraints

- Worker runtime is **Apple-Silicon macOS, Python 3.12** — do not add cross-platform shims.
- **Secrets never committed.** Secrets load from `worker/.env` (gitignored) or the optional central `~/.config/env-variables/secrets.env`. Non-secret settings live in `state/config.json`.
- `AnthropicSummarizer` uses **structured outputs** (`output_config.format`); valid Anthropic model ids are exactly `claude-opus-4-8` (default), `claude-sonnet-4-6`, `claude-haiku-4-5` — **no date suffixes**. Do not offer Opus 4.7/4.6 as summarizer models (structured outputs unconfirmed there).
- Summaries (title/overview/sections/action_items) are **always English**, regardless of transcript language.
- **Do not regress the existing Notion path or `reconcile.py` idempotency.** A recording already `status='processed'` is still skipped by reconcile; reruns of `process_recording` must update in place, never duplicate.
- DRY, YAGNI, TDD, frequent commits.

---

### Task 0: Test scaffold

**Files:**
- Create: `worker/pyproject.toml`
- Create: `worker/requirements-dev.txt`
- Create: `worker/tests/__init__.py`
- Create: `worker/tests/conftest.py`
- Create: `worker/tests/test_scaffold.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a working `cd worker && python -m pytest` invocation with `plaud_worker` importable from `src`.

- [ ] **Step 1: Create the pytest config**

Create `worker/pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: Create the dev requirements**

Create `worker/requirements-dev.txt`:

```text
# Test-only deps (not needed at runtime).
pytest>=8.0
```

- [ ] **Step 3: Create the tests package + conftest**

Create `worker/tests/__init__.py` (empty file).

Create `worker/tests/conftest.py`:

```python
"""Shared test fixtures. `pythonpath = ["src"]` in pyproject makes
`plaud_worker` importable; nothing else is needed here yet."""
```

- [ ] **Step 4: Write a scaffold smoke test**

Create `worker/tests/test_scaffold.py`:

```python
def test_plaud_worker_importable():
    import plaud_worker  # noqa: F401
```

- [ ] **Step 5: Install dev deps and run it**

Run:
```bash
cd worker && pip install -r requirements.txt -r requirements-dev.txt && python -m pytest tests/test_scaffold.py -v
```
Expected: PASS (`test_plaud_worker_importable`).

- [ ] **Step 6: Commit**

```bash
git add worker/pyproject.toml worker/requirements-dev.txt worker/tests/
git commit -m "test: add pytest scaffold for the worker package"
```

---

### Task 1: AppConfig (state/config.json)

**Files:**
- Create: `worker/src/plaud_worker/appconfig.py`
- Test: `worker/tests/test_appconfig.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `AppConfig` dataclass with fields `destination: str` (`"notion"|"local"`), `speaker_naming_enabled: bool`, `summarizer_provider: str` (`"openai"|"anthropic"`), `summarizer_model: str`, `notion_parent_page_id: str | None`; classmethod `AppConfig.load(state_dir: Path) -> AppConfig`; method `save(state_dir: Path) -> None`. Defaults: `destination="notion"`, `speaker_naming_enabled=True`, `summarizer_provider="openai"`, `summarizer_model="gpt-5.5"`, `notion_parent_page_id=None`.

- [ ] **Step 1: Write the failing tests**

Create `worker/tests/test_appconfig.py`:

```python
from plaud_worker.appconfig import AppConfig


def test_load_missing_returns_defaults(tmp_path):
    cfg = AppConfig.load(tmp_path)
    assert cfg.destination == "notion"
    assert cfg.summarizer_provider == "openai"
    assert cfg.summarizer_model == "gpt-5.5"
    assert cfg.speaker_naming_enabled is True
    assert cfg.notion_parent_page_id is None


def test_save_then_load_roundtrips(tmp_path):
    AppConfig(
        destination="local",
        speaker_naming_enabled=False,
        summarizer_provider="anthropic",
        summarizer_model="claude-opus-4-8",
        notion_parent_page_id="page-123",
    ).save(tmp_path)
    cfg = AppConfig.load(tmp_path)
    assert cfg.destination == "local"
    assert cfg.speaker_naming_enabled is False
    assert cfg.summarizer_provider == "anthropic"
    assert cfg.summarizer_model == "claude-opus-4-8"
    assert cfg.notion_parent_page_id == "page-123"


def test_load_tolerates_unknown_keys(tmp_path):
    (tmp_path / "config.json").write_text('{"destination": "local", "future_key": 1}')
    cfg = AppConfig.load(tmp_path)
    assert cfg.destination == "local"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd worker && python -m pytest tests/test_appconfig.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'plaud_worker.appconfig'`.

- [ ] **Step 3: Implement AppConfig**

Create `worker/src/plaud_worker/appconfig.py`:

```python
"""Non-secret app settings the setup wizard writes; read by the worker.

Stored at state/config.json so a shared clone can configure itself without the
owner's central secrets store. Secrets stay in worker/.env (see config.py).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    destination: str = "notion"            # "notion" | "local"
    speaker_naming_enabled: bool = True
    summarizer_provider: str = "openai"    # "openai" | "anthropic"
    summarizer_model: str = "gpt-5.5"
    notion_parent_page_id: str | None = None

    @classmethod
    def load(cls, state_dir: Path) -> "AppConfig":
        path = state_dir / "config.json"
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, state_dir: Path) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "config.json").write_text(json.dumps(asdict(self), indent=2))
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd worker && python -m pytest tests/test_appconfig.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add worker/src/plaud_worker/appconfig.py worker/tests/test_appconfig.py
git commit -m "feat: AppConfig for non-secret state/config.json settings"
```

---

### Task 2: NotesStore + LocalDestination

**Files:**
- Create: `worker/src/plaud_worker/notes_store.py`
- Create: `worker/src/plaud_worker/destinations/__init__.py`
- Create: `worker/src/plaud_worker/destinations/base.py`
- Create: `worker/src/plaud_worker/destinations/local.py`
- Test: `worker/tests/test_local_destination.py`

**Interfaces:**
- Consumes: `Meeting` (from `models.py`, has `to_dict()` / `from_dict()` / `recording_id` / `recorded_at` / `duration_ms` / `source_url` / `audio_path`).
- Produces:
  - `Destination` Protocol: `name: str`, `publish(self, meeting: Meeting, *, prior_ref: str | None = None) -> str`.
  - `NotesStore(db_path: Path)` with `upsert(meeting: Meeting, *, audio_rel_path: str | None) -> str`, `get(recording_id: str) -> Meeting | None`, `list_summaries() -> list[dict]` (dicts: `recording_id`, `title`, `recorded_at`, `duration_ms`), `close()`.
  - `LocalDestination(notes_db: Path)` with `name = "local"`, `publish(...)`, `close()`.

- [ ] **Step 1: Write the failing tests**

Create `worker/tests/test_local_destination.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd worker && python -m pytest tests/test_local_destination.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'plaud_worker.notes_store'`.

- [ ] **Step 3: Implement NotesStore**

Create `worker/src/plaud_worker/notes_store.py`:

```python
"""Local SQLite store of finished meeting notes (state/notes.db).

Mirrors Meeting.to_dict() as a JSON payload column plus a few queryable columns
for the viewer's list. Separate DB from the ledger/voiceprint stores so the
concerns stay isolated.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Meeting

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    recording_id   TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    recorded_at    TEXT NOT NULL,
    duration_ms    INTEGER,
    source_url     TEXT,
    audio_rel_path TEXT,
    payload_json   TEXT NOT NULL,
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class NotesStore:
    def __init__(self, db_path: Path):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def upsert(self, meeting: Meeting, *, audio_rel_path: str | None) -> str:
        payload = json.dumps(meeting.to_dict(), ensure_ascii=False)
        self._conn.execute(
            """
            INSERT INTO meetings (recording_id, title, recorded_at, duration_ms,
                                  source_url, audio_rel_path, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(recording_id) DO UPDATE SET
                title          = excluded.title,
                recorded_at    = excluded.recorded_at,
                duration_ms    = excluded.duration_ms,
                source_url     = excluded.source_url,
                audio_rel_path = excluded.audio_rel_path,
                payload_json   = excluded.payload_json,
                updated_at     = datetime('now')
            """,
            (
                meeting.recording_id,
                meeting.title,
                meeting.recorded_at.isoformat(),
                meeting.duration_ms,
                meeting.source_url,
                audio_rel_path,
                payload,
            ),
        )
        self._conn.commit()
        return meeting.recording_id

    def get(self, recording_id: str) -> Meeting | None:
        cur = self._conn.execute(
            "SELECT payload_json FROM meetings WHERE recording_id = ?",
            (recording_id,),
        )
        row = cur.fetchone()
        return Meeting.from_dict(json.loads(row["payload_json"])) if row else None

    def list_summaries(self) -> list[dict]:
        cur = self._conn.execute(
            "SELECT recording_id, title, recorded_at, duration_ms "
            "FROM meetings ORDER BY recorded_at DESC"
        )
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Implement the Destination protocol and LocalDestination**

Create `worker/src/plaud_worker/destinations/__init__.py`:

```python
from .base import Destination

__all__ = ["Destination"]
```

Create `worker/src/plaud_worker/destinations/base.py`:

```python
"""The output-destination interface the pipeline writes through."""

from __future__ import annotations

from typing import Protocol

from ..models import Meeting


class Destination(Protocol):
    name: str

    def publish(self, meeting: Meeting, *, prior_ref: str | None = None) -> str:
        """Create or update this meeting's note. Returns a stable ref
        (Notion page id / local recording id) the ledger stores for idempotent
        reruns. `prior_ref` is the previously-stored ref, or None on first write."""
        ...
```

Create `worker/src/plaud_worker/destinations/local.py`:

```python
"""Local destination — writes the Meeting into state/notes.db."""

from __future__ import annotations

import os
from pathlib import Path

from ..models import Meeting
from ..notes_store import NotesStore


class LocalDestination:
    name = "local"

    def __init__(self, notes_db: Path):
        self._store = NotesStore(notes_db)

    def publish(self, meeting: Meeting, *, prior_ref: str | None = None) -> str:
        rel = os.path.basename(meeting.audio_path) if meeting.audio_path else None
        return self._store.upsert(meeting, audio_rel_path=rel)

    def close(self) -> None:
        self._store.close()
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd worker && python -m pytest tests/test_local_destination.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add worker/src/plaud_worker/notes_store.py worker/src/plaud_worker/destinations/ worker/tests/test_local_destination.py
git commit -m "feat: NotesStore + LocalDestination (state/notes.db)"
```

---

### Task 3: NotionDestination + destination factory

**Files:**
- Create: `worker/src/plaud_worker/destinations/notion.py`
- Modify: `worker/src/plaud_worker/destinations/__init__.py`
- Test: `worker/tests/test_notion_destination.py`

**Interfaces:**
- Consumes: existing `NotionWriter` (from `notion.py`) — `create_meeting_page(parent_page_id, meeting) -> str`, `page_exists(page_id) -> bool`, `replace_page_content(page_id, meeting) -> None`, context-manager (`__enter__`/`__exit__`); `Meeting`.
- Produces:
  - `NotionDestination(token: str, parent_page_id: str)` with `name = "notion"`, `publish(...)`.
  - `build_destination(settings, *, parent_page_id: str | None = None) -> Destination` factory in `destinations/__init__.py`: returns `LocalDestination(settings.state_dir / "notes.db")` when `settings.destination == "local"`, else `NotionDestination(settings.notion_token, parent_page_id or settings.notion_parent_page_id)`.

- [ ] **Step 1: Write the failing tests**

Create `worker/tests/test_notion_destination.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd worker && python -m pytest tests/test_notion_destination.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'plaud_worker.destinations.notion'`.

- [ ] **Step 3: Implement NotionDestination**

Create `worker/src/plaud_worker/destinations/notion.py`:

```python
"""Notion destination — thin wrapper over the existing NotionWriter.

Adds idempotent in-place updates: if the previously-written page still exists,
rewrite it instead of creating a duplicate.
"""

from __future__ import annotations

from ..models import Meeting
from ..notion import NotionWriter


class NotionDestination:
    name = "notion"

    def __init__(self, token: str, parent_page_id: str):
        self._token = token
        self._parent = parent_page_id

    def publish(self, meeting: Meeting, *, prior_ref: str | None = None) -> str:
        with NotionWriter(self._token) as w:
            if prior_ref and w.page_exists(prior_ref):
                w.replace_page_content(prior_ref, meeting)
                return prior_ref
            return w.create_meeting_page(self._parent, meeting)
```

- [ ] **Step 4: Add the factory**

Replace the contents of `worker/src/plaud_worker/destinations/__init__.py`:

```python
from __future__ import annotations

from .base import Destination
from .local import LocalDestination
from .notion import NotionDestination

__all__ = ["Destination", "LocalDestination", "NotionDestination", "build_destination"]


def build_destination(settings, *, parent_page_id: str | None = None) -> Destination:
    """Resolve the configured destination. Only the chosen one is constructed,
    so a local-only setup never needs Notion credentials."""
    if settings.destination == "local":
        return LocalDestination(settings.state_dir / "notes.db")
    return NotionDestination(
        settings.notion_token, parent_page_id or settings.notion_parent_page_id
    )
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd worker && python -m pytest tests/test_notion_destination.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add worker/src/plaud_worker/destinations/ worker/tests/test_notion_destination.py
git commit -m "feat: NotionDestination (idempotent) + build_destination factory"
```

---

### Task 4: Summarizers (OpenAI + Anthropic) + factory

**Files:**
- Create: `worker/src/plaud_worker/summarizers/__init__.py`
- Create: `worker/src/plaud_worker/summarizers/base.py`
- Create: `worker/src/plaud_worker/summarizers/openai.py`
- Create: `worker/src/plaud_worker/summarizers/anthropic.py`
- Modify: `worker/requirements.txt`
- Test: `worker/tests/test_summarizers.py`

**Interfaces:**
- Consumes: existing `structure(transcript_text, *, title, api_key, model, participants) -> tuple[str, list[str], list[Section], list[ActionItem]]` and the module-level `_SCHEMA` / `_SYSTEM` from `structure.py`; `Section`, `ActionItem` from `models.py`.
- Produces:
  - `Summarizer` Protocol: `summarize(self, transcript_text: str, *, title: str, participants: list[str] | None = None) -> tuple[str, list[str], list[Section], list[ActionItem]]`.
  - `OpenAISummarizer(api_key: str, model: str)`.
  - `AnthropicSummarizer(api_key: str, model: str)` (imports the `anthropic` SDK lazily so an OpenAI-only install never needs it).
  - `build_summarizer(settings) -> Summarizer` factory: `AnthropicSummarizer(settings.anthropic_api_key, settings.summarizer_model)` when `settings.summarizer_provider == "anthropic"`, else `OpenAISummarizer(settings.openai_api_key, settings.summarizer_model)`.

- [ ] **Step 1: Write the failing tests**

Create `worker/tests/test_summarizers.py`:

```python
import json

import plaud_worker.summarizers.anthropic as anth_mod
import plaud_worker.summarizers.openai as oai_mod
from plaud_worker.models import ActionItem, Section
from plaud_worker.summarizers.anthropic import AnthropicSummarizer
from plaud_worker.summarizers.openai import OpenAISummarizer

_NOTES = {
    "title": "Patent Strategy",
    "overview": ["Filed the provisional"],
    "sections": [{"heading": "Next steps", "bullets": ["draft claims"]}],
    "action_items": [{"owner": "Sam", "task": "Send the spec", "description": "by Fri"}],
}


def test_openai_summarizer_delegates_to_structure(monkeypatch):
    captured = {}

    def fake_structure(transcript_text, *, title, api_key, model, participants=None):
        captured.update(api_key=api_key, model=model, participants=participants)
        return ("Patent Strategy", ["ov"], [Section("H", ["b"])], [ActionItem("Sam", "t", "d")])

    monkeypatch.setattr(oai_mod, "structure", fake_structure)
    title, overview, sections, actions = OpenAISummarizer("sk-xyz", "gpt-5.5").summarize(
        "Sam: hi", title="Untitled", participants=["Sam"]
    )
    assert captured == {"api_key": "sk-xyz", "model": "gpt-5.5", "participants": ["Sam"]}
    assert title == "Patent Strategy"
    assert sections[0].heading == "H"


def test_anthropic_summarizer_parses_structured_json(monkeypatch):
    class _Block:
        type = "text"
        text = json.dumps(_NOTES)

    class _Resp:
        content = [_Block()]

    class _Messages:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return _Resp()

    class _Client:
        def __init__(self, api_key):
            self.messages = _Messages()

    fake_anthropic = type("M", (), {"Anthropic": _Client})
    monkeypatch.setattr(anth_mod, "_import_anthropic", lambda: fake_anthropic)

    s = AnthropicSummarizer("ak-1", "claude-opus-4-8")
    title, overview, sections, actions = s.summarize(
        "Sam: hi", title="Untitled", participants=["Sam"]
    )
    assert title == "Patent Strategy"
    assert overview == ["Filed the provisional"]
    assert sections[0].bullets == ["draft claims"]
    assert actions[0].owner == "Sam"
    # model + structured-output format were passed through
    assert s._client.messages.kwargs["model"] == "claude-opus-4-8"
    assert s._client.messages.kwargs["output_config"]["format"]["type"] == "json_schema"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd worker && python -m pytest tests/test_summarizers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'plaud_worker.summarizers'`.

- [ ] **Step 3: Implement the protocol + OpenAI summarizer**

Create `worker/src/plaud_worker/summarizers/base.py`:

```python
"""The summarizer interface the pipeline calls to turn a labelled transcript
into structured English notes (title / overview / sections / action items)."""

from __future__ import annotations

from typing import Protocol

from ..models import ActionItem, Section


class Summarizer(Protocol):
    def summarize(
        self,
        transcript_text: str,
        *,
        title: str,
        participants: list[str] | None = None,
    ) -> tuple[str, list[str], list[Section], list[ActionItem]]:
        ...
```

Create `worker/src/plaud_worker/summarizers/openai.py`:

```python
"""OpenAI summarizer — wraps the existing structure() call."""

from __future__ import annotations

from ..models import ActionItem, Section
from ..structure import structure


class OpenAISummarizer:
    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model

    def summarize(
        self,
        transcript_text: str,
        *,
        title: str,
        participants: list[str] | None = None,
    ) -> tuple[str, list[str], list[Section], list[ActionItem]]:
        return structure(
            transcript_text,
            title=title,
            api_key=self._api_key,
            model=self._model,
            participants=participants,
        )
```

- [ ] **Step 4: Implement the Anthropic summarizer**

Create `worker/src/plaud_worker/summarizers/anthropic.py`:

```python
"""Anthropic summarizer — same prompt/schema as the OpenAI path, via the
official anthropic SDK with structured outputs. Reuses structure._SYSTEM and
structure._SCHEMA so the two providers stay byte-identical in intent.

Valid models (structured-output support): claude-opus-4-8, claude-sonnet-4-6,
claude-haiku-4-5.
"""

from __future__ import annotations

import json

from ..models import ActionItem, Section
from ..structure import _SCHEMA, _SYSTEM


def _import_anthropic():
    # Lazy import so an OpenAI-only install never requires the anthropic package,
    # and so tests can monkeypatch this seam.
    import anthropic

    return anthropic


class AnthropicSummarizer:
    def __init__(self, api_key: str, model: str):
        anthropic = _import_anthropic()
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def summarize(
        self,
        transcript_text: str,
        *,
        title: str,
        participants: list[str] | None = None,
    ) -> tuple[str, list[str], list[Section], list[ActionItem]]:
        who = f"Known participants: {', '.join(participants)}.\n" if participants else ""
        user = f"Meeting title: {title}\n{who}\nTranscript:\n{transcript_text}"
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=8000,
            system=_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{"role": "user", "content": user}],
        )
        text = next(b.text for b in resp.content if b.type == "text")
        data = json.loads(text)
        gen_title = (data.get("title") or "").strip()
        sections = [Section(heading=s["heading"], bullets=s["bullets"]) for s in data["sections"]]
        actions = [
            ActionItem(owner=a["owner"], task=a["task"], description=a.get("description", ""))
            for a in data["action_items"]
        ]
        return gen_title, data["overview"], sections, actions
```

- [ ] **Step 5: Add the factory**

Create `worker/src/plaud_worker/summarizers/__init__.py`:

```python
from __future__ import annotations

from .anthropic import AnthropicSummarizer
from .base import Summarizer
from .openai import OpenAISummarizer

__all__ = ["Summarizer", "OpenAISummarizer", "AnthropicSummarizer", "build_summarizer"]


def build_summarizer(settings) -> Summarizer:
    if settings.summarizer_provider == "anthropic":
        return AnthropicSummarizer(settings.anthropic_api_key, settings.summarizer_model)
    return OpenAISummarizer(settings.openai_api_key, settings.summarizer_model)
```

- [ ] **Step 6: Add the anthropic runtime dependency**

Edit `worker/requirements.txt` — add this line under the `openai` line:

```text
anthropic>=0.49   # used by the Anthropic structuring stage (alt to OpenAI)
```

- [ ] **Step 7: Run to verify it passes**

Run: `cd worker && python -m pytest tests/test_summarizers.py -v`
Expected: PASS (2 tests). (No real `anthropic` install needed — the test monkeypatches `_import_anthropic`.)

- [ ] **Step 8: Commit**

```bash
git add worker/src/plaud_worker/summarizers/ worker/requirements.txt worker/tests/test_summarizers.py
git commit -m "feat: OpenAI/Anthropic summarizer abstraction + build_summarizer factory"
```

---

### Task 5: Ledger destination_refs

**Files:**
- Modify: `worker/src/plaud_worker/ledger.py:13-22` (schema) and add methods after `upsert`
- Test: `worker/tests/test_ledger_refs.py`

**Interfaces:**
- Consumes: existing `Ledger(db_path)` / `upsert` / `get`.
- Produces: `Ledger.get_ref(recording_id: str, destination: str) -> str | None` and `Ledger.set_ref(recording_id: str, destination: str, ref: str) -> None` (upsert keyed by `(recording_id, destination)`), backed by a new `destination_refs` table. The existing `processed` table and `notion_page_id` column are unchanged.

- [ ] **Step 1: Write the failing tests**

Create `worker/tests/test_ledger_refs.py`:

```python
from plaud_worker.ledger import Ledger


def test_get_ref_missing_returns_none(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    assert led.get_ref("rec-1", "local") is None
    led.close()


def test_set_then_get_ref(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    led.set_ref("rec-1", "notion", "page-abc")
    led.set_ref("rec-1", "local", "rec-1")
    assert led.get_ref("rec-1", "notion") == "page-abc"
    assert led.get_ref("rec-1", "local") == "rec-1"
    led.close()


def test_set_ref_is_upsert(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    led.set_ref("rec-1", "notion", "page-old")
    led.set_ref("rec-1", "notion", "page-new")
    assert led.get_ref("rec-1", "notion") == "page-new"
    led.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd worker && python -m pytest tests/test_ledger_refs.py -v`
Expected: FAIL with `AttributeError: 'Ledger' object has no attribute 'get_ref'`.

- [ ] **Step 3: Add the table to the schema**

In `worker/src/plaud_worker/ledger.py`, replace the `_SCHEMA` string (currently lines 13-22) with:

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed (
    recording_id    TEXT PRIMARY KEY,
    notion_page_id  TEXT,
    processing_hash TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS destination_refs (
    recording_id TEXT NOT NULL,
    destination  TEXT NOT NULL,
    ref          TEXT NOT NULL,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (recording_id, destination)
);
"""
```

- [ ] **Step 4: Add get_ref / set_ref methods**

In `worker/src/plaud_worker/ledger.py`, insert these two methods into the `Ledger` class, immediately after the `upsert` method (before `close`):

```python
    def get_ref(self, recording_id: str, destination: str) -> str | None:
        cur = self._conn.execute(
            "SELECT ref FROM destination_refs WHERE recording_id = ? AND destination = ?",
            (recording_id, destination),
        )
        row = cur.fetchone()
        return row["ref"] if row else None

    def set_ref(self, recording_id: str, destination: str, ref: str) -> None:
        self._conn.execute(
            """
            INSERT INTO destination_refs (recording_id, destination, ref)
            VALUES (?, ?, ?)
            ON CONFLICT(recording_id, destination) DO UPDATE SET
                ref        = excluded.ref,
                updated_at = datetime('now')
            """,
            (recording_id, destination, ref),
        )
        self._conn.commit()
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd worker && python -m pytest tests/test_ledger_refs.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add worker/src/plaud_worker/ledger.py worker/tests/test_ledger_refs.py
git commit -m "feat: ledger destination_refs table (get_ref/set_ref)"
```

---

### Task 6: Conditional config (provider + destination)

**Files:**
- Modify: `worker/src/plaud_worker/config.py` (Settings dataclass fields + `load`)
- Test: `worker/tests/test_config.py`

**Interfaces:**
- Consumes: `AppConfig.load` (Task 1).
- Produces: `Settings` gains fields `anthropic_api_key: str | None`, `destination: str`, `summarizer_provider: str`, `summarizer_model: str`, `speaker_naming_enabled: bool`; `notion_token` becomes `str | None`. `Settings.load()` reads `AppConfig` from the state dir, requires Notion creds only when `destination == "notion"`, and requires the chosen provider's key only for that provider. Reads `ANTHROPIC_API_KEY`; OpenAI key from `OPENAI_API_KEY_PERSONAL` or `OPENAI_API_KEY`.

- [ ] **Step 1: Write the failing tests**

Create `worker/tests/test_config.py`:

```python
import pytest

import plaud_worker.config as config_mod
from plaud_worker.appconfig import AppConfig
from plaud_worker.config import Settings


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """Neutralize dotenv loading and clear secret env vars so Settings.load()
    sees only what each test sets."""
    monkeypatch.setattr(config_mod, "SHARED_SECRETS", tmp_path / "nope-secrets.env")
    monkeypatch.setattr(config_mod, "WORKER_ENV", tmp_path / "nope.env")
    for var in [
        "NOTION_TOKEN", "NOTION_TEST_PARENT_PAGE_ID", "OTHER_MEETING_CENTRAL_PAGE_ID",
        "OPENAI_API_KEY_PERSONAL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    ]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("WORKER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("RIFFADO_BASE_URL", "http://127.0.0.1:3000")
    monkeypatch.setenv("RIFFADO_API_KEY", "op_test")
    return tmp_path


def _write_appconfig(tmp_path, **kw):
    AppConfig(**kw).save(tmp_path / "state")


def test_local_destination_needs_no_notion_creds(isolated_env, monkeypatch):
    _write_appconfig(isolated_env, destination="local",
                     summarizer_provider="openai", summarizer_model="gpt-5.5")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    s = Settings.load()
    assert s.destination == "local"
    assert s.notion_token is None
    assert s.summarizer_provider == "openai"
    assert s.openai_api_key == "sk-test"


def test_anthropic_provider_requires_anthropic_key(isolated_env):
    _write_appconfig(isolated_env, destination="local",
                     summarizer_provider="anthropic", summarizer_model="claude-opus-4-8")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        Settings.load()


def test_notion_destination_requires_token(isolated_env, monkeypatch):
    _write_appconfig(isolated_env, destination="notion",
                     summarizer_provider="openai", summarizer_model="gpt-5.5")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with pytest.raises(RuntimeError, match="NOTION_TOKEN"):
        Settings.load()


def test_notion_happy_path(isolated_env, monkeypatch):
    _write_appconfig(isolated_env, destination="notion",
                     summarizer_provider="anthropic", summarizer_model="claude-opus-4-8")
    monkeypatch.setenv("NOTION_TOKEN", "secret_tok")
    monkeypatch.setenv("OTHER_MEETING_CENTRAL_PAGE_ID", "page-xyz")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-test")
    s = Settings.load()
    assert s.notion_token == "secret_tok"
    assert s.notion_parent_page_id == "page-xyz"
    assert s.anthropic_api_key == "ak-test"
    assert s.summarizer_model == "claude-opus-4-8"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd worker && python -m pytest tests/test_config.py -v`
Expected: FAIL (e.g. `TypeError`/`RuntimeError` — Settings has no `anthropic_api_key`/`destination` fields and `load` still requires `NOTION_TOKEN`).

- [ ] **Step 3: Add the new dataclass fields**

In `worker/src/plaud_worker/config.py`, inside the `Settings` dataclass, change the `notion_token` line and add the new fields. Replace:

```python
    riffado_api_key: str
    notion_token: str
```

with:

```python
    riffado_api_key: str
    notion_token: str | None
```

Then, immediately after the existing `state_dir: Path` field declaration (and before `def skip_recordings`), add:

```python
    # Anthropic key — used only when summarizer_provider == "anthropic".
    anthropic_api_key: str | None = None
    # Output destination + summarizer choice (mirrors AppConfig / state/config.json).
    destination: str = "notion"
    summarizer_provider: str = "openai"
    summarizer_model: str = "gpt-5.5"
    speaker_naming_enabled: bool = True
```

- [ ] **Step 4: Rewrite Settings.load()**

In `worker/src/plaud_worker/config.py`, add the AppConfig import near the top (after `from dotenv import load_dotenv`):

```python
from .appconfig import AppConfig
```

Replace the entire `load` classmethod body (currently the `_load()` … `return cls(...)` block) with:

```python
    @classmethod
    def load(cls) -> "Settings":
        _load()
        state_dir = Path(
            os.getenv("WORKER_STATE_DIR", Path(__file__).resolve().parents[2] / "state")
        )
        state_dir.mkdir(parents=True, exist_ok=True)
        app = AppConfig.load(state_dir)

        notion_token = os.getenv("NOTION_TOKEN")
        parent = (
            os.getenv("NOTION_TEST_PARENT_PAGE_ID")
            or os.getenv("OTHER_MEETING_CENTRAL_PAGE_ID")
            or app.notion_parent_page_id
            or ""
        )
        if app.destination == "notion":
            if not notion_token:
                raise RuntimeError(
                    "destination=notion requires NOTION_TOKEN in worker/.env"
                )
            if not parent:
                raise RuntimeError(
                    "destination=notion requires NOTION_TEST_PARENT_PAGE_ID (scratch) "
                    "or OTHER_MEETING_CENTRAL_PAGE_ID (production)."
                )

        openai_key = os.getenv("OPENAI_API_KEY_PERSONAL") or os.getenv("OPENAI_API_KEY")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if app.summarizer_provider == "openai" and not openai_key:
            raise RuntimeError(
                "summarizer_provider=openai requires OPENAI_API_KEY_PERSONAL or OPENAI_API_KEY"
            )
        if app.summarizer_provider == "anthropic" and not anthropic_key:
            raise RuntimeError("summarizer_provider=anthropic requires ANTHROPIC_API_KEY")

        return cls(
            riffado_base_url=_require("RIFFADO_BASE_URL").rstrip("/"),
            riffado_api_key=_require("RIFFADO_API_KEY"),
            notion_token=notion_token,
            notion_parent_page_id=parent,
            openai_api_key=openai_key,
            hf_token=os.getenv("HF_TOKEN"),
            riffado_admin_email=os.getenv("RIFFADO_ADMIN_EMAIL"),
            riffado_admin_password=os.getenv("RIFFADO_ADMIN_PASSWORD"),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
            state_dir=state_dir,
            anthropic_api_key=anthropic_key,
            destination=app.destination,
            summarizer_provider=app.summarizer_provider,
            summarizer_model=app.summarizer_model,
            speaker_naming_enabled=app.speaker_naming_enabled,
        )
```

Note: the old docstring/comment on `notion_parent_page_id` stays as-is; only the `load` body and the `notion_token` annotation change.

- [ ] **Step 5: Run to verify it passes**

Run: `cd worker && python -m pytest tests/test_config.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add worker/src/plaud_worker/config.py worker/tests/test_config.py
git commit -m "feat: conditional config — Notion creds + provider key required only when chosen"
```

---

### Task 7: Wire pipeline to summarizer + destination

**Files:**
- Modify: `worker/src/plaud_worker/pipeline.py` (imports; `structure()` call at lines 121-127; write block at lines 152-157; remove now-unused `import os` at line 9 and the `OPENAI_MODEL` lookup)
- Test: `worker/tests/test_pipeline_dispatch.py`

**Interfaces:**
- Consumes: `build_summarizer(settings)` (Task 4), `build_destination(settings, *, parent_page_id=)` (Task 3), `Ledger.get_ref` / `set_ref` (Task 5).
- Produces: `process_recording(...)` unchanged signature; when `write=True` it publishes via the configured destination, records the ref with `ledger.set_ref` + `ledger.upsert(status="processed")`, and (for Notion) sets `meeting.source_url` to the page URL. Adds a testable seam `_write_meeting(meeting, settings, ledger) -> str` returning the destination ref.

- [ ] **Step 1: Write the failing test**

Create `worker/tests/test_pipeline_dispatch.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd worker && python -m pytest tests/test_pipeline_dispatch.py -v`
Expected: FAIL with `AttributeError: module 'plaud_worker.pipeline' has no attribute '_write_meeting'`.

- [ ] **Step 3: Update pipeline imports**

In `worker/src/plaud_worker/pipeline.py`:

Delete the top-level `import os` (line 9 — its only use, the `OPENAI_MODEL` lookup, is removed in Step 5).

Delete these two imports:
```python
from .notion import NotionWriter
from .structure import structure
```

Add these imports (alongside the other `from .` imports):
```python
from .destinations import build_destination
from .summarizers import build_summarizer
```

- [ ] **Step 4: Add the `_write_meeting` seam**

In `worker/src/plaud_worker/pipeline.py`, add this module-level function just above `def process_recording(`:

```python
def _write_meeting(meeting: Meeting, settings: Settings, ledger: Ledger,
                   *, parent_page_id: str | None = None) -> str:
    """Publish the meeting to the configured destination, record the ref, and
    return it. Notion publishes update in place when the prior page still exists."""
    destination = build_destination(settings, parent_page_id=parent_page_id)
    try:
        prior = ledger.get_ref(meeting.recording_id, destination.name)
        ref = destination.publish(meeting, prior_ref=prior)
    finally:
        close = getattr(destination, "close", None)
        if close:
            close()
    ledger.set_ref(meeting.recording_id, destination.name, ref)
    ledger.upsert(
        meeting.recording_id,
        notion_page_id=(ref if destination.name == "notion" else None),
        status="processed",
    )
    if destination.name == "notion":
        # link back to the page for the caller to open
        meeting.source_url = "https://www.notion.so/" + ref.replace("-", "")
    return ref
```

- [ ] **Step 5: Replace the summarize call**

In `worker/src/plaud_worker/pipeline.py`, replace the existing structuring block (currently lines 121-127):

```python
    gen_title, overview, sections, actions = structure(
        transcript_text,
        title=rec.get("title") or "Untitled",
        api_key=settings.openai_api_key,
        model=os.getenv("OPENAI_MODEL", "gpt-5.5"),
        participants=participants,
    )
```

with:

```python
    gen_title, overview, sections, actions = build_summarizer(settings).summarize(
        transcript_text,
        title=rec.get("title") or "Untitled",
        participants=participants,
    )
```

- [ ] **Step 6: Replace the write block**

In `worker/src/plaud_worker/pipeline.py`, replace the existing write block (currently lines 152-157):

```python
    if write:
        with NotionWriter(settings.notion_token) as w:
            page_id = w.create_meeting_page(parent, meeting)
            page_url = w.page_url(page_id)
        ledger.upsert(rid, notion_page_id=page_id, status="processed")
        meeting.source_url = page_url  # for the caller to open
    return meeting
```

with:

```python
    if write:
        _write_meeting(meeting, settings, ledger, parent_page_id=parent_page_id)
    return meeting
```

Note: `parent` (computed at the top of `process_recording` as `parent_page_id or settings.notion_parent_page_id`) is now unused — leave it; it is harmless and reconcile still passes `parent_page_id` through. (If a linter flags it, delete the `parent = ...` line at line 94.)

- [ ] **Step 7: Run the new test + the full suite**

Run: `cd worker && python -m pytest tests/test_pipeline_dispatch.py -v && python -m pytest`
Expected: `test_pipeline_dispatch.py` PASS (2 tests); full suite green.

- [ ] **Step 8: Commit**

```bash
git add worker/src/plaud_worker/pipeline.py worker/tests/test_pipeline_dispatch.py
git commit -m "feat: pipeline writes via configured destination + summarizer"
```

---

## Self-Review

**Spec coverage (Plan 1 portion of the spec):**
- §4 Destination abstraction → Tasks 2, 3, 7. ✓
- §5 Local notes store → Task 2. ✓
- §6 Summarizer abstraction + provider choice → Task 4 (picker UI is Plan 2; model-id constraint captured in Global Constraints). ✓
- §7 Config & secrets decoupling (AppConfig, conditional creds) → Tasks 1, 6. ✓
- §10 Idempotency / `destination_refs` + in-place update → Tasks 3, 5, 7. ✓
- Spec sections deferred to **Plan 2 (web app)**: §3 `app/` + `run`, §8 wizard/viewer/bootstrap, §9 speaker-naming panel, §11 installer error handling, §12 web/API + smoke tests, §13 privacy copy. (The model picker + cost table live in Plan 2; their values are fixed in the spec.)

**Placeholder scan:** none — every code/test step contains complete content; no TBD/TODO.

**Type consistency:** `Destination.publish(meeting, *, prior_ref=None) -> str` and `Summarizer.summarize(transcript_text, *, title, participants=None) -> tuple[str, list[str], list[Section], list[ActionItem]]` are used identically in producers (Tasks 2/3/4) and consumer (Task 7). `Ledger.get_ref/set_ref(recording_id, destination[, ref])` consistent across Tasks 5 and 7. `build_destination(settings, *, parent_page_id=None)` / `build_summarizer(settings)` signatures match call sites. `AppConfig` field names match `Settings.load()` reads in Task 6.

**Note on a deliberate refinement vs. the committed spec:** the spec's §6 cost table lists Opus 4.7/4.6 for reference; the *selectable* Anthropic summarizer models are constrained to `claude-opus-4-8` / `claude-sonnet-4-6` / `claude-haiku-4-5` (structured-output support). This is captured in Global Constraints and will be reflected in the Plan 2 picker.
