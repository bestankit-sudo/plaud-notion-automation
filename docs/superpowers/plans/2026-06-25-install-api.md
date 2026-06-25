# Install API Router (Plan 2b-3d) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the installer backend to the web app — a `/api/install` router with a step-status endpoint (resume), an **SSE streaming** endpoint that runs a step's install and streams its log (surviving client disconnect), Riffado secret writing, and launchd plist rendering.

**Architecture:** `app/install/status.py` (pure-with-injected-run: `resolve_env` + per-step `step_status` via the 2b-3a detect probes). `app/install_api.py` (FastAPI `APIRouter`): `GET /status` (resume view), `GET /stream/{step_id}` (StreamingResponse; the blocking subprocess runs in a daemon thread bridged by a `queue.Queue` with a 15s heartbeat, so it never blocks the event loop and the install completes even if the browser tab closes), `POST /riffado/secrets`, `GET /launchd` (rendered plists + the `launchctl` argv + a port-8787-in-use warning). The module-level `_runner`/`_run` seams are overridden in tests (FakeRunner / fake run) so no real subprocess runs; `RealRunner` + `detect.real_run` are the real-Mac defaults.

**Tech Stack:** Python 3.12, FastAPI (existing), stdlib (`queue`, `threading`, `socket`), the `app/install/*` backend, pytest + FastAPI `TestClient`.

## Global Constraints
- macOS/arm64, Python 3.12. App binds 127.0.0.1.
- The SSE endpoint runs the install in a **daemon thread** feeding a `queue.Queue`; the generator yields frames with a 15s heartbeat comment (`: heartbeat\n\n`). The worker thread runs `orchestrate.run_step` to completion regardless of client disconnect (tab-close-safe).
- **Tests never run a real subprocess:** override `install_api._runner` (a `FakeRunner`) and `install_api._run` (a fake `run`); override the Riffado env path via the `RIFFADO_ENV_FILE` env var so tests never touch `deploy/riffado/.env`.
- The SSE error frame already carries only the command + code (from `orchestrate`, 2b-3c) — no env/secret leak. `/riffado/secrets` writes via `riffado.write_env_idempotent` (0600, no rotation) and returns only the **key names** written.
- `GET /launchd` is render-only (no `launchctl` side effects) — it returns the plist XML + the `launchctl` argv (from `launchd.install_argv`) + `port_in_use` so the UI can warn before the user loads the agent. Actually loading the agent is a real-Mac step (manual or a later real-Mac-gated endpoint).
- Reuse: `app.install.detect/plan/steps/orchestrate/riffado/launchd/runner` (2b-3a/b/c). Mount the router in `app/server.py` alongside `setup_router` (do not alter the existing routes).
- DRY, YAGNI, TDD, frequent commits. Run app tests as `cd app && ../worker/.venv/bin/python -m pytest`.

> **Decomposition:** Plan 2b-3d of the installer. Done: 2b-3a/b/c (full pure backend). Next: 2b-3e (multi-step wizard UI consuming these endpoints + worker-plist repoint), then real-Mac validation (RealRunner actually installing; `launchctl` load).

---

### Task 1: Step status + Env resolution

**Files:**
- Create: `app/install/status.py`
- Test: `app/tests/test_install_status.py`

**Interfaces:**
- Consumes: `app.install.detect` (probes), `app.install.plan.Env`, `app.install.steps.ALL_STEPS`.
- Produces: `resolve_env(run, repo_root) -> Env`; `step_done(step_id, run, repo_root) -> tuple[bool, str]` (per-step done + detail via the detect probes; `riffado`/`plaud_otp` are human/runtime-gated so report `(False, ...)`); `step_status(run, repo_root) -> list[dict]` (`[{id, title, kind, done, detail}]` for all steps).

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_install_status.py`:

```python
from pathlib import Path

from app.install import status as S


def fake(mapping):
    return lambda argv: mapping.get(tuple(argv), (127, ""))


def test_resolve_env_from_probes():
    run = fake({
        ("/opt/homebrew/bin/brew", "--version"): (0, "Homebrew 4"),
        ("/opt/homebrew/bin/brew", "--prefix"): (0, "/opt/homebrew\n"),
        ("/opt/homebrew/opt/python@3.12/bin/python3.12", "--version"): (0, "Python 3.12.9"),
    })
    env = S.resolve_env(run, Path("/r"))
    assert env.brew == "/opt/homebrew/bin/brew"
    assert env.brew_prefix == "/opt/homebrew"
    assert env.py312 == "/opt/homebrew/opt/python@3.12/bin/python3.12"
    assert env.repo_root == Path("/r")


def test_step_done_brew_ffmpeg_docker():
    run = fake({
        ("/opt/homebrew/bin/brew", "--version"): (0, "Homebrew 4"),
        ("ffmpeg", "-version"): (0, "ffmpeg version 7"),
        ("docker", "info"): (1, "Cannot connect"),
    })
    assert S.step_done("brew", run, Path("/r"))[0] is True
    assert S.step_done("ffmpeg", run, Path("/r"))[0] is True
    assert S.step_done("docker", run, Path("/r"))[0] is False  # daemon down


def test_step_done_ml_absent():
    done, detail = S.step_done("ml", fake({}), Path("/r"))
    assert done is False  # no .venv-ml binary


def test_step_done_human_steps_are_false():
    assert S.step_done("riffado", fake({}), Path("/r"))[0] is False
    assert S.step_done("plaud_otp", fake({}), Path("/r"))[0] is False


def test_step_status_covers_all_steps():
    rows = S.step_status(fake({}), Path("/r"))
    assert [r["id"] for r in rows] == [
        "brew", "ffmpeg", "py312", "ml", "docker", "riffado", "plaud_otp", "launchd"
    ]
    for r in rows:
        assert set(r) == {"id", "title", "kind", "done", "detail"}
        assert isinstance(r["done"], bool)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_install_status.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.install.status'`.

- [ ] **Step 3: Implement status.py**

Create `app/install/status.py`:

```python
"""Map install steps to their current state on this machine (via the detect
probes) and resolve an Env. Probes take an injected `run`, so this is testable
with no real subprocess. riffado/plaud_otp are human/runtime-gated -> reported
not-done (the wizard surfaces them as guide/Test steps)."""

from __future__ import annotations

import os
from pathlib import Path

from app.install import detect
from app.install.plan import Env
from app.install.steps import ALL_STEPS


def resolve_env(run: detect.Run, repo_root: Path) -> Env:
    return Env(
        repo_root=repo_root,
        brew=detect.find_brew(run),
        py312=detect.find_python312(run),
        brew_prefix=detect.brew_prefix(run) or "/opt/homebrew",
    )


def step_done(step_id: str, run: detect.Run, repo_root: Path) -> tuple[bool, str]:
    if step_id == "brew":
        b = detect.find_brew(run)
        return (b is not None, b or "not found")
    if step_id == "ffmpeg":
        rc, _ = run(["ffmpeg", "-version"])
        return (rc == 0, "installed" if rc == 0 else "missing")
    if step_id == "py312":
        p = detect.find_python312(run)
        return (p is not None, p or "missing")
    if step_id == "ml":
        ok = detect.ml_installed(run, repo_root)
        return (ok, "installed" if ok else "not installed")
    if step_id == "docker":
        up = detect.docker_running(run)
        return (up, "running" if up else "not running — start Docker Desktop")
    if step_id == "riffado":
        return (False, "run to start the container")
    if step_id == "plaud_otp":
        return (False, "log into Riffado and paste its API key")
    if step_id == "launchd":
        label = "com.example.plaudautomation.web"
        rc, _ = run(["launchctl", "print", f"gui/{os.getuid()}/{label}"])
        return (rc == 0, "loaded" if rc == 0 else "not loaded")
    return (False, "")


def step_status(run: detect.Run, repo_root: Path) -> list[dict]:
    rows: list[dict] = []
    for s in ALL_STEPS:
        done, detail = step_done(s.id, run, repo_root)
        rows.append({"id": s.id, "title": s.title, "kind": s.kind, "done": done, "detail": detail})
    return rows
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_install_status.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add app/install/status.py app/tests/test_install_status.py
git commit -m "feat: install step status + Env resolution (detect-backed, injected run)"
```

---

### Task 2: install_api router (status / SSE stream / riffado secrets / launchd)

**Files:**
- Create: `app/install_api.py`
- Modify: `app/server.py` (mount the router)
- Test: `app/tests/test_install_api.py`

**Interfaces:**
- Consumes: `app.install.status` (Task 1), `app.install.detect`, `app.install.orchestrate`, `app.install.riffado`, `app.install.launchd`, `app.install.runner.RealRunner`, `app.install.steps.STEPS_BY_ID`.
- Produces a FastAPI `APIRouter` (`router`) with prefix `/api/install`:
  - `GET /status` → `{"steps": [...]}` (from `status.step_status`).
  - `GET /stream/{step_id}` → `StreamingResponse(text/event-stream)`; 404 on unknown step; runs the step's install in a daemon thread (queue-bridged, 15s heartbeat), streams `orchestrate` frames, completes even if the client disconnects.
  - `POST /riffado/secrets` → writes the Riffado `.env` via `riffado.write_env_idempotent`; returns `{"ok": True, "written": [...]}`.
  - `GET /launchd` → `{"worker": <plist xml>, "web": <plist xml>, "load_argv": [[...], ...], "port_in_use": bool}`.
- Module-level overridable seams: `_runner = RealRunner()`, `_run = detect.real_run`. `app/server.py` includes the router.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_install_api.py`:

```python
import pytest
from fastapi.testclient import TestClient

import app.install_api as install_api
from app.install.runner import FakeRunner


def fake_run(mapping):
    return lambda argv: mapping.get(tuple(argv), (127, ""))


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("RIFFADO_ENV_FILE", str(tmp_path / "riffado.env"))
    from app.server import app
    return TestClient(app)


def test_status_lists_steps(client, monkeypatch):
    monkeypatch.setattr(install_api, "_run", fake_run({("/opt/homebrew/bin/brew", "--version"): (0, "Homebrew")}))
    body = client.get("/api/install/status").json()
    ids = [s["id"] for s in body["steps"]]
    assert ids[0] == "brew" and "launchd" in ids
    brew = next(s for s in body["steps"] if s["id"] == "brew")
    assert brew["done"] is True


def test_stream_runs_step_and_emits_frames(client, monkeypatch):
    # fake machine: brew present, ffmpeg NOT installed (so the step runs)
    run = fake_run({
        ("/opt/homebrew/bin/brew", "--version"): (0, "Homebrew"),
        ("/opt/homebrew/bin/brew", "--prefix"): (0, "/opt/homebrew\n"),
        ("ffmpeg", "-version"): (1, "not found"),
    })
    monkeypatch.setattr(install_api, "_run", run)
    monkeypatch.setattr(install_api, "_runner", FakeRunner({
        ("/opt/homebrew/bin/brew", "install", "ffmpeg"): (0, ["==> Pouring ffmpeg", "ok"]),
    }))
    r = client.get("/api/install/stream/ffmpeg")
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert "event: log" in r.text
    assert "install ffmpeg" in r.text  # the $ <cmd> line
    assert "==> Pouring ffmpeg" in r.text
    assert "event: done" in r.text


def test_stream_unknown_step_404(client):
    assert client.get("/api/install/stream/nope").status_code == 404


def test_stream_skips_when_already_done(client, monkeypatch):
    # ffmpeg already installed -> skip without running the runner
    run = fake_run({
        ("/opt/homebrew/bin/brew", "--version"): (0, "Homebrew"),
        ("ffmpeg", "-version"): (0, "ffmpeg version 7"),
    })
    monkeypatch.setattr(install_api, "_run", run)
    fr = FakeRunner({})
    monkeypatch.setattr(install_api, "_runner", fr)
    r = client.get("/api/install/stream/ffmpeg")
    assert "event: skip" in r.text and "event: done" in r.text
    assert fr.calls == []  # nothing ran


def test_riffado_secrets_written(client, tmp_path):
    r = client.post("/api/install/riffado/secrets")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert set(body["written"]) == {"BETTER_AUTH_SECRET", "ENCRYPTION_KEY", "POSTGRES_PASSWORD"}
    assert (tmp_path / "riffado.env").exists()


def test_launchd_render(client, monkeypatch):
    monkeypatch.setattr(install_api, "_run", fake_run({("/opt/homebrew/bin/brew", "--prefix"): (0, "/opt/homebrew\n")}))
    body = client.get("/api/install/launchd").json()
    assert "com.example.plaudautomation.web" in body["web"]
    assert ".venv-ml/bin/python" in body["worker"]
    assert body["load_argv"][0][0] == "launchctl"
    assert isinstance(body["port_in_use"], bool)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_install_api.py -v`
Expected: FAIL — `/api/install/*` 404 (router not mounted) / `ModuleNotFoundError: No module named 'app.install_api'`.

- [ ] **Step 3: Implement install_api.py**

Create `app/install_api.py`:

```python
"""/api/install router — wires the installer backend to the web app. The blocking
subprocess runs in a daemon thread bridged by a queue so it never blocks the event
loop and the install completes even if the browser tab closes. `_runner`/`_run` are
module-level seams overridden in tests; RealRunner/detect.real_run are the real-Mac
defaults."""

from __future__ import annotations

import os
import queue
import socket
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.install import detect, launchd, orchestrate, riffado
from app.install import status as status_mod
from app.install.runner import RealRunner
from app.install.steps import STEPS_BY_ID

router = APIRouter(prefix="/api/install")

# overridable seams (tests replace these with a fake run / FakeRunner)
_run = detect.real_run
_runner = RealRunner()

_HEARTBEAT_SECS = 15
_SENTINEL = object()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _riffado_env(repo_root: Path) -> Path:
    return Path(os.getenv("RIFFADO_ENV_FILE", str(repo_root / "deploy" / "riffado" / ".env")))


def _port_in_use(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


@router.get("/status")
def status() -> dict:
    return {"steps": status_mod.step_status(_run, _repo_root())}


@router.get("/stream/{step_id}")
def stream(step_id: str) -> StreamingResponse:
    if step_id not in STEPS_BY_ID:
        raise HTTPException(status_code=404, detail="unknown step")
    repo = _repo_root()
    env = status_mod.resolve_env(_run, repo)
    already_done, _ = status_mod.step_done(step_id, _run, repo)

    q: "queue.Queue" = queue.Queue()

    def work() -> None:
        try:
            orchestrate.run_step(step_id, env, _runner, already_done=already_done, emit=q.put)
        except Exception as exc:  # noqa: BLE001 - never leak a traceback to the stream
            q.put(orchestrate.sse_format("error", {"step": step_id, "detail": type(exc).__name__}))
        finally:
            q.put(_SENTINEL)

    threading.Thread(target=work, daemon=True).start()

    def gen():
        while True:
            try:
                item = q.get(timeout=_HEARTBEAT_SECS)
            except queue.Empty:
                yield ": heartbeat\n\n"
                continue
            if item is _SENTINEL:
                break
            yield item

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/riffado/secrets")
def riffado_secrets() -> dict:
    written = riffado.write_env_idempotent(_riffado_env(_repo_root()), riffado.gen_secrets())
    return {"ok": True, "written": written}


@router.get("/launchd")
def launchd_render() -> dict:
    repo = _repo_root()
    env = status_mod.resolve_env(_run, repo)
    ml_py = detect.ml_python(repo)
    server_py = repo / "worker" / ".venv" / "bin" / "python"
    return {
        "worker": launchd.render_worker_plist(repo, ml_py, env.brew_prefix),
        "web": launchd.render_web_plist(repo, server_py, env.brew_prefix),
        "load_argv": launchd.install_argv(
            launchd.WEB_LABEL,
            Path.home() / "Library" / "LaunchAgents" / f"{launchd.WEB_LABEL}.plist",
            os.getuid(),
        ),
        "port_in_use": _port_in_use(8787),
    }
```

- [ ] **Step 4: Mount the router in server.py**

In `app/server.py`, add the import with the other `from app...` imports:

```python
from app.install_api import router as install_router
```

and add this line immediately after the existing `app.include_router(setup_router)`:

```python
app.include_router(install_router)
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_install_api.py -v`
Expected: PASS (6 tests). Then the full suite: `cd app && ../worker/.venv/bin/python -m pytest`.

- [ ] **Step 6: Commit**

```bash
git add app/install_api.py app/server.py app/tests/test_install_api.py
git commit -m "feat: /api/install router (status + SSE stream + riffado secrets + launchd render)"
```

---

## Self-Review

**Spec coverage (Plan 2b-3d = synthesis task 7, the install_api half):**
- Step status / resume → Task 1 (`step_status`) + Task 2 (`GET /status`). ✓
- SSE streaming install (threadpool+queue, heartbeat, tab-close-safe) → Task 2 (`GET /stream/{step_id}`). ✓
- Riffado secrets endpoint (separate from the stream — no secret in the log) → Task 2 (`POST /riffado/secrets`). ✓
- launchd render + load argv + port warning → Task 2 (`GET /launchd`). ✓
- **Deferred:** the multi-step wizard UI consuming these endpoints + the worker-plist repoint (2b-3e); the actual `launchctl` load + real installs (real-Mac).

**Placeholder scan:** none — every code/test step is complete.

**Type/name consistency:** `status.resolve_env/step_done/step_status` (Task 1) are used by `install_api` (Task 2) and asserted in both test files. `install_api._run`/`_runner` are the overridable seams the tests monkeypatch. `orchestrate.run_step`/`sse_format` (2b-3c), `riffado.write_env_idempotent`/`gen_secrets` (2b-3b), `launchd.render_*`/`install_argv`/`WEB_LABEL` (2b-3b), `detect.real_run`/`ml_python` (2b-3a), `STEPS_BY_ID` (2b-3a) are all consumed with their existing signatures. `RIFFADO_ENV_FILE` keeps tests off the real `deploy/riffado/.env`.

**Hardening honored:** the SSE worker thread is a daemon that runs `run_step` to completion regardless of client disconnect (tab-close-safe), with a 15s heartbeat so a minutes-long install doesn't idle-timeout; the error path emits only the exception type (no traceback/secret); `/riffado/secrets` returns only key names and writes 0600 (no rotation); `/launchd` is render-only (no `launchctl` side effects), surfaces the `launchctl` argv + a port-in-use warning so the UI can warn before loading the agent over a running `./run`; tests never run a real subprocess (`_runner`/`_run` overridden).
