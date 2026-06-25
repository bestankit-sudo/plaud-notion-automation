# Installer Orchestration Control Flow (Plan 2b-3c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The execution control flow for installer steps — a `Runner` seam (the only place subprocess lives) plus a pure `run_step` orchestrator that detect-gates, runs the planned commands, and emits SSE frames — fully tested against a `FakeRunner` with **zero real subprocess**.

**Architecture:** `app/install/runner.py` defines the `Runner` protocol (`run(argv, on_line) -> rc`), a `FakeRunner` (scripted output for tests), and a thin `RealRunner` (Popen, real-Mac, not unit-tested). `app/install/orchestrate.py` has `sse_format()` (pure) and `run_step()` — the control flow that gates on a caller-supplied `already_done`, builds the plan (2b-3a), streams each command's output through the runner as `log` SSE frames, and on a non-zero exit emits an `error` frame carrying **only `shlex.join(argv)` + the code** (never env/secrets). The `/api/install` SSE router (threadpool+queue bridge) and the multi-step UI are later plans.

**Tech Stack:** Python 3.12, stdlib (`subprocess`, `shlex`, `json`), the 2b-3a `plan`/`steps` modules, pytest.

## Global Constraints
- macOS/arm64, Python 3.12.
- `Runner.run(argv, on_line) -> int`: calls `on_line(line)` per output line, returns the exit code. `RealRunner` is the **only** subprocess in this plan and is **not** exercised in tests; all orchestrate tests use `FakeRunner`.
- `run_step` emits SSE frames via an injected `emit(frame_str)`: `skip`+`done` (when `already_done`), `log` (the `$ <cmd>` line then each output line), `done`, or `error`. The **error frame carries only `cmd = shlex.join(argv)` and the exit `code` — never the env, never a secret value**. A non-zero exit stops the step (remaining commands not run).
- `run_step` returns `True` on success/skip, `False` on error (incl. `plan.PrerequisiteMissing`).
- Commands come from `plan.plan_for(step_id, env)` (2b-3a) — pure argv, no shell.
- DRY, YAGNI, TDD, frequent commits. Run app tests as `cd app && ../worker/.venv/bin/python -m pytest`.

> **Decomposition:** Plan 2b-3c of the installer. Done: 2b-3a (detect/plan core), 2b-3b (Riffado secrets + launchd templates). Next: 2b-3d (`/api/install` SSE router + status), 2b-3e (multi-step wizard UI + worker-plist repoint), then real-Mac validation. (Carried note: a later plan should DRY `detect.ml_python`/`plan.ml_venv_python` and add a runner test that ignores `launchctl bootout`'s non-zero exit.)

---

### Task 1: Runner seam (protocol + FakeRunner + RealRunner)

**Files:**
- Create: `app/install/runner.py`
- Test: `app/tests/test_install_runner.py`

**Interfaces:**
- Produces: `Runner` Protocol with `run(self, argv: list[str], on_line: Callable[[str], None]) -> int`; `FakeRunner(scripts: dict[tuple[str, ...], tuple[int, list[str]]])` (replays scripted `(rc, lines)` per argv tuple; records `.calls`; unknown argv → `(0, [])`); `RealRunner` (Popen line-streamer; real-Mac).

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_install_runner.py`:

```python
from app.install.runner import FakeRunner


def test_fake_runner_replays_lines_and_rc():
    fr = FakeRunner({("brew", "install", "ffmpeg"): (0, ["==> Installing", "done"])})
    seen = []
    rc = fr.run(["brew", "install", "ffmpeg"], seen.append)
    assert rc == 0
    assert seen == ["==> Installing", "done"]
    assert fr.calls == [["brew", "install", "ffmpeg"]]


def test_fake_runner_unknown_argv_is_noop_success():
    fr = FakeRunner({})
    seen = []
    rc = fr.run(["whatever"], seen.append)
    assert rc == 0 and seen == []


def test_fake_runner_nonzero_rc():
    fr = FakeRunner({("x",): (1, ["boom"])})
    seen = []
    assert fr.run(["x"], seen.append) == 1
    assert seen == ["boom"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_install_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.install.runner'`.

- [ ] **Step 3: Implement runner.py**

Create `app/install/runner.py`:

```python
"""Execution seam for installer steps. `Runner.run(argv, on_line) -> rc` is the
only place a subprocess lives. The orchestrator is tested against FakeRunner, so
no real process runs in tests. RealRunner (Popen) is exercised only on a real Mac."""

from __future__ import annotations

import subprocess
from typing import Callable, Protocol

OnLine = Callable[[str], None]


class Runner(Protocol):
    def run(self, argv: list[str], on_line: OnLine) -> int:
        """Run argv, call on_line(line) for each output line, return the exit code."""
        ...


class FakeRunner:
    """Replays scripted output per argv tuple — for tests. Unknown argv -> (0, [])."""

    def __init__(self, scripts: dict[tuple[str, ...], tuple[int, list[str]]]):
        self._scripts = scripts
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], on_line: OnLine) -> int:
        self.calls.append(list(argv))
        rc, lines = self._scripts.get(tuple(argv), (0, []))
        for line in lines:
            on_line(line)
        return rc


class RealRunner:
    """Real-Mac executor: streams a subprocess's combined output line-by-line.
    Not exercised in unit tests (the only impure surface in the installer)."""

    def run(self, argv: list[str], on_line: OnLine) -> int:  # pragma: no cover
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            on_line(line.rstrip("\n"))
        return proc.wait()
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_install_runner.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/install/runner.py app/tests/test_install_runner.py
git commit -m "feat: installer Runner seam (Protocol + FakeRunner + RealRunner)"
```

---

### Task 2: Orchestration (sse_format + run_step)

**Files:**
- Create: `app/install/orchestrate.py`
- Test: `app/tests/test_install_orchestrate.py`

**Interfaces:**
- Consumes: `app.install.plan` (`plan_for`, `Env`, `PrerequisiteMissing`); a `Runner` (Task 1).
- Produces: `sse_format(event: str, data: dict) -> str` (`"event: <e>\ndata: <json>\n\n"`); `run_step(step_id, env, runner, *, already_done, emit) -> bool`. Frames: `skip`+`done(skipped=True)` when `already_done`; `log` for the `$ <cmd>` line and each output line; `error` with `{step, cmd, code}` (or `{step, detail}` for a missing prerequisite) on failure (stops the step); `done(skipped=False)` on success.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_install_orchestrate.py`:

```python
import json
from pathlib import Path

from app.install.orchestrate import run_step, sse_format
from app.install.plan import Env
from app.install.runner import FakeRunner


def _frames(captured):
    """Parse captured SSE frame strings into (event, data) tuples."""
    out = []
    for f in captured:
        lines = f.strip().split("\n")
        ev = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        out.append((ev, data))
    return out


def _env(**kw):
    base = dict(repo_root=Path("/r"), brew="/b/brew", py312="/p/python3.12", brew_prefix="/opt/homebrew")
    base.update(kw)
    return Env(**base)


def test_sse_format():
    assert sse_format("log", {"a": 1}) == 'event: log\ndata: {"a": 1}\n\n'


def test_already_done_skips_without_running():
    cap = []
    fr = FakeRunner({})
    ok = run_step("ffmpeg", _env(), fr, already_done=True, emit=cap.append)
    assert ok is True
    evs = [e for e, _ in _frames(cap)]
    assert evs == ["skip", "done"]
    assert _frames(cap)[1][1]["skipped"] is True
    assert fr.calls == []  # nothing ran


def test_success_streams_logs_then_done():
    cap = []
    fr = FakeRunner({("/b/brew", "install", "ffmpeg"): (0, ["==> Installing ffmpeg", "ok"])})
    ok = run_step("ffmpeg", _env(), fr, already_done=False, emit=cap.append)
    assert ok is True
    frames = _frames(cap)
    assert frames[0] == ("log", {"step": "ffmpeg", "line": "$ /b/brew install ffmpeg"})
    assert ("log", {"step": "ffmpeg", "line": "==> Installing ffmpeg"}) in frames
    assert frames[-1][0] == "done" and frames[-1][1]["skipped"] is False


def test_nonzero_exit_emits_error_with_exact_cmd_and_stops():
    cap = []
    # ml plan: venv create fails -> error, pip steps must NOT run
    fr = FakeRunner({tuple(["/p/python3.12", "-m", "venv", "/r/worker/.venv-ml"]): (1, ["boom"])})
    ok = run_step("ml", _env(py312="/p/python3.12"), fr, already_done=False, emit=cap.append)
    assert ok is False
    err = [d for e, d in _frames(cap) if e == "error"][0]
    assert err["cmd"] == "/p/python3.12 -m venv /r/worker/.venv-ml"
    assert err["code"] == 1
    assert "env" not in err and "PATH" not in err  # no env/secret leak
    # only the failing command ran; pip install never started
    assert fr.calls == [["/p/python3.12", "-m", "venv", "/r/worker/.venv-ml"]]


def test_prerequisite_missing_emits_error():
    cap = []
    fr = FakeRunner({})
    ok = run_step("ml", _env(py312=None, brew=None), fr, already_done=False, emit=cap.append)
    assert ok is False
    err = [d for e, d in _frames(cap) if e == "error"][0]
    assert "prerequisite" in err["detail"].lower()
    assert fr.calls == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_install_orchestrate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.install.orchestrate'`.

- [ ] **Step 3: Implement orchestrate.py**

Create `app/install/orchestrate.py`:

```python
"""Pure orchestration: detect-gate -> run the planned commands via a Runner ->
emit SSE frames. Tested against a FakeRunner (no real subprocess). Error frames
carry only the failed command (shlex.join argv) + exit code — never env/secrets."""

from __future__ import annotations

import json
import shlex
from typing import Callable

from app.install import plan as plan_mod
from app.install.runner import Runner

Emit = Callable[[str], None]  # receives a preformatted SSE frame string


def sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def run_step(step_id: str, env: plan_mod.Env, runner: Runner, *,
             already_done: bool, emit: Emit) -> bool:
    """Run one auto step. Returns True on success/skip, False on error.
    `already_done` is the detect-gate result (the caller computes it)."""
    if already_done:
        emit(sse_format("skip", {"step": step_id}))
        emit(sse_format("done", {"step": step_id, "skipped": True}))
        return True

    try:
        cmds = plan_mod.plan_for(step_id, env)
    except plan_mod.PrerequisiteMissing as exc:
        emit(sse_format("error", {"step": step_id, "detail": f"missing prerequisite: {exc}"}))
        return False

    for argv in cmds:
        emit(sse_format("log", {"step": step_id, "line": "$ " + shlex.join(argv)}))
        rc = runner.run(argv, lambda line: emit(sse_format("log", {"step": step_id, "line": line})))
        if rc != 0:
            emit(sse_format("error", {"step": step_id, "cmd": shlex.join(argv), "code": rc}))
            return False

    emit(sse_format("done", {"step": step_id, "skipped": False}))
    return True
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_install_orchestrate.py -v`
Expected: PASS (5 tests). Then the full suite: `cd app && ../worker/.venv/bin/python -m pytest`.

- [ ] **Step 5: Commit**

```bash
git add app/install/orchestrate.py app/tests/test_install_orchestrate.py
git commit -m "feat: installer run_step orchestration (detect-gate, SSE frames, error carries only argv)"
```

---

## Self-Review

**Spec coverage (Plan 2b-3c = synthesis task 6, control-flow half):**
- Runner seam (Protocol + FakeRunner + RealRunner stub) → Task 1. ✓
- `sse_format` + `run_step` (detect-gate skip, log streaming, stop-on-error, prerequisite error, no env/secret in error frame) → Task 2. ✓
- **Deferred:** the `/api/install` SSE HTTP router (threadpool+queue bridge) + `/status` (2b-3d); the multi-step wizard UI (2b-3e); `RealRunner` actually Popen-ing brew/pip/docker (real-Mac).

**Placeholder scan:** none — every code/test step is complete.

**Type/name consistency:** `Runner.run(argv, on_line) -> int` (Task 1) is consumed by `run_step` (Task 2) and the tests inject `FakeRunner`. `sse_format`/`run_step` signatures match their tests. `run_step` builds commands via `plan.plan_for`/`Env`/`PrerequisiteMissing` from 2b-3a (consistent). The error frame's `cmd` is `shlex.join(argv)`; the closure passed to `runner.run` re-emits each line as a `log` frame.

**Hardening honored:** the only subprocess (`RealRunner.run`) is `# pragma: no cover` and never run in tests; the error frame carries only the command string + exit code (asserted: no `env`/`PATH` key); a non-zero exit stops the step (asserted: pip steps don't run after a failed venv create); a missing prerequisite is a clean error, not a crash.
