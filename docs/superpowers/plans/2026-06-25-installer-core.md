# Installer Core (Plan 2b-3a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The pure, fully-testable "installer brain" for the setup wizard — an ordered step registry, detection (parsers + thin shell probes), and argv command builders — with **zero** real subprocess calls in the test path.

**Architecture:** A new `app/install/` package. `steps.py` declares the ordered steps (pure data). `detect.py` has pure parsers plus thin probes that shell out only through an injected `run(argv) -> (rc, output)` callable (a real `subprocess` wrapper by default; a fake in tests). `commands.py`/`plan.py` build `list[str]` argv sequences (never shell strings). The impure execution/streaming shell, Riffado secrets, launchd templates, the `/api/install` SSE router, and the wizard UI are **later plans (2b-3b/2b-3c)** — see the design doc.

**Tech Stack:** Python 3.12, stdlib only (re, subprocess, pathlib, dataclasses), pytest. No FastAPI in this plan.

## Global Constraints
(from `docs/superpowers/specs/2026-06-25-installer-orchestration-design.md`)
- macOS/Apple Silicon, Python 3.12. App reuses `worker/.venv` for the server; the **ML stack targets a DEDICATED `worker/.venv-ml`** — never the live server venv.
- **Require Python 3.12** for ML: `find_python312` must return `None` if 3.12 is absent — **never** fall back to the user's `python3` (3.14 has no torch/pyannote wheels). When absent, the ML plan prepends `brew install python@3.12`.
- **Detect completeness by importing** `mlx_whisper, torch, pyannote.audio` in `.venv-ml` — not by venv existence (a half-finished pip must be re-run).
- Pure layer = the test target: parsers take captured strings; probes take an injected `run` callable. No side effects in the tested path.
- Command builders return **`list[str]` argv, never shell strings** (injection-safe).
- `brew` is classified **guide** (the Homebrew installer needs sudo/TTY the wizard can't supply); `docker` and `plaud_otp` are **guide**; `ffmpeg`/`py312`/`ml`/`riffado`/`launchd` are **auto**.
- DRY, YAGNI, TDD, frequent commits. Run app tests as `cd app && ../worker/.venv/bin/python -m pytest`.

---

### Task 1: Step registry

**Files:**
- Create: `app/install/__init__.py`
- Create: `app/install/steps.py`
- Test: `app/tests/test_install_steps.py`

**Interfaces:**
- Produces: frozen `Step(id, title, kind, detail, guide_url=None)` where `kind ∈ {"auto","guide"}`; ordered `ALL_STEPS: list[Step]` (ids in order: `brew, ffmpeg, py312, ml, docker, riffado, plaud_otp, launchd`); `STEPS_BY_ID: dict[str, Step]`.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_install_steps.py`:

```python
from app.install.steps import ALL_STEPS, STEPS_BY_ID, Step


def test_step_order():
    assert [s.id for s in ALL_STEPS] == [
        "brew", "ffmpeg", "py312", "ml", "docker", "riffado", "plaud_otp", "launchd"
    ]


def test_kind_classification():
    guide = {s.id for s in ALL_STEPS if s.kind == "guide"}
    assert guide == {"brew", "docker", "plaud_otp"}
    auto = {s.id for s in ALL_STEPS if s.kind == "auto"}
    assert auto == {"ffmpeg", "py312", "ml", "riffado", "launchd"}


def test_riffado_after_docker():
    ids = [s.id for s in ALL_STEPS]
    assert ids.index("riffado") > ids.index("docker")  # Riffado needs Docker


def test_guide_steps_have_a_url():
    for s in ALL_STEPS:
        if s.kind == "guide":
            assert s.guide_url, f"guide step {s.id} needs a guide_url"


def test_lookup_and_frozen():
    assert STEPS_BY_ID["ml"].title == "Local ML stack"
    import dataclasses
    assert dataclasses.is_dataclass(Step)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_install_steps.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.install'`.

- [ ] **Step 3: Implement the registry**

Create `app/install/__init__.py` (empty file).

Create `app/install/steps.py`:

```python
"""Ordered registry of setup-wizard install steps. Pure data — imports nothing
that shells out. `kind` is "auto" (the wizard can run it) or "guide" (a human /
GUI step: show a link + Test). Detection and command-planning live in
detect.py / plan.py and key off step.id; Step itself stays a plain dataclass."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    kind: str  # "auto" | "guide"
    detail: str
    guide_url: str | None = None


ALL_STEPS: list[Step] = [
    Step("brew", "Homebrew", "guide",
         "Package manager (ffmpeg + Python 3.12 come from it). Installs need your password in Terminal.",
         "https://brew.sh"),
    Step("ffmpeg", "ffmpeg", "auto", "Audio decoding for transcription."),
    Step("py312", "Python 3.12", "auto",
         "Required for the ML stack — torch/pyannote have no wheels for newer Python."),
    Step("ml", "Local ML stack", "auto",
         "Whisper + speaker diarization, installed into worker/.venv-ml."),
    Step("docker", "Docker Desktop", "guide",
         "Needed to run Riffado. Install the app, then start it.",
         "https://www.docker.com/products/docker-desktop/"),
    Step("riffado", "Riffado", "auto", "Self-hosted sync from Plaud (via docker compose)."),
    Step("plaud_otp", "Connect Plaud", "guide",
         "Log into Riffado (email OTP), then paste its API key into the Riffado field above.",
         "http://127.0.0.1:3000"),
    Step("launchd", "Background services", "auto",
         "Schedule the worker and keep the dashboard always-on."),
]

STEPS_BY_ID: dict[str, Step] = {s.id: s for s in ALL_STEPS}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_install_steps.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add app/install/__init__.py app/install/steps.py app/tests/test_install_steps.py
git commit -m "feat: install step registry (ordered, auto/guide classified)"
```

---

### Task 2: Detection (pure parsers + thin probes)

**Files:**
- Create: `app/install/detect.py`
- Test: `app/tests/test_install_detect.py`

**Interfaces:**
- Consumes: nothing (probes take an injected `run`).
- Produces:
  - Type alias `Run = Callable[[list[str]], tuple[int, str]]`; `real_run(argv, *, timeout=20.0) -> (rc, output)` (the only real-subprocess function; never raises).
  - Pure parsers: `is_py312(version_output) -> bool` (matches `Python 3.12.x`, rejects 3.14/empty); `parse_brew_prefix(stdout) -> str | None`; `parse_docker_info(rc) -> str` (`"running"` iff rc==0 else `"down"`); `ml_imports_ok(rc) -> bool`.
  - Thin probes (take `run`): `find_brew(run) -> str | None`; `brew_prefix(run) -> str | None`; `find_python312(run) -> str | None` (REQUIRES 3.12, else None); `ml_python(repo_root) -> Path`; `ml_installed(run, repo_root) -> bool`; `docker_running(run) -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_install_detect.py`:

```python
from pathlib import Path

from app.install import detect


def fake(mapping):
    """run-callable: maps an argv tuple to (rc, output); default (127, '')."""
    return lambda argv: mapping.get(tuple(argv), (127, ""))


def test_is_py312():
    assert detect.is_py312("Python 3.12.13") is True
    assert detect.is_py312("Python 3.14.6") is False
    assert detect.is_py312("") is False


def test_parse_brew_prefix():
    assert detect.parse_brew_prefix("/opt/homebrew\n") == "/opt/homebrew"
    assert detect.parse_brew_prefix("not a path") is None
    assert detect.parse_brew_prefix("") is None


def test_parse_docker_info_and_ml_imports():
    assert detect.parse_docker_info(0) == "running"
    assert detect.parse_docker_info(1) == "down"
    assert detect.ml_imports_ok(0) is True
    assert detect.ml_imports_ok(1) is False


def test_find_brew_prefers_opt_homebrew():
    run = fake({("/opt/homebrew/bin/brew", "--version"): (0, "Homebrew 4.x")})
    assert detect.find_brew(run) == "/opt/homebrew/bin/brew"


def test_find_brew_falls_back_to_which():
    run = fake({
        ("/opt/homebrew/bin/brew", "--version"): (1, ""),
        ("which", "brew"): (0, "/usr/local/bin/brew\n"),
    })
    assert detect.find_brew(run) == "/usr/local/bin/brew"


def test_find_brew_absent():
    assert detect.find_brew(fake({})) is None


def test_find_python312_at_brew_path():
    run = fake({("/opt/homebrew/opt/python@3.12/bin/python3.12", "--version"): (0, "Python 3.12.13")})
    assert detect.find_python312(run) == "/opt/homebrew/opt/python@3.12/bin/python3.12"


def test_find_python312_rejects_314():
    # every candidate reports 3.14 -> must be None (never fall back to python3)
    run = fake({
        ("/opt/homebrew/opt/python@3.12/bin/python3.12", "--version"): (1, ""),
        ("python3.12", "--version"): (0, "Python 3.14.6"),
    })
    assert detect.find_python312(run) is None


def test_find_python312_via_path_resolves_absolute():
    run = fake({
        ("/opt/homebrew/opt/python@3.12/bin/python3.12", "--version"): (1, ""),
        ("python3.12", "--version"): (0, "Python 3.12.9"),
        ("which", "python3.12"): (0, "/usr/local/bin/python3.12\n"),
    })
    assert detect.find_python312(run) == "/usr/local/bin/python3.12"


def test_ml_installed(tmp_path):
    repo = tmp_path
    py = detect.ml_python(repo)
    assert detect.ml_installed(fake({}), repo) is False  # binary absent
    py.parent.mkdir(parents=True)
    py.write_text("")  # binary present
    run = fake({(str(py), "-c", "import mlx_whisper, torch, pyannote.audio"): (0, "")})
    assert detect.ml_installed(run, repo) is True
    assert detect.ml_installed(fake({}), repo) is False  # import fails -> not installed


def test_docker_running():
    assert detect.docker_running(fake({("docker", "info"): (0, "...")})) is True
    assert detect.docker_running(fake({})) is False


def test_ml_python_path():
    assert detect.ml_python(Path("/r")) == Path("/r/worker/.venv-ml/bin/python")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_install_detect.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.install.detect'`.

- [ ] **Step 3: Implement detection**

Create `app/install/detect.py`:

```python
"""Detection for the installer: pure parsers (fed captured command output) plus
thin probes that shell out only through an injected `run` callable, so tests
stay subprocess-free. `run(argv) -> (returncode, combined_output)`."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable

Run = Callable[[list[str]], tuple[int, str]]


def real_run(argv: list[str], *, timeout: float = 20.0) -> tuple[int, str]:
    """The only real-subprocess function. Never raises — maps errors to rc 127."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return 127, type(exc).__name__
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# --------------------------- pure parsers --------------------------- #

_PY312 = re.compile(r"Python 3\.12\.\d+")


def is_py312(version_output: str) -> bool:
    return bool(_PY312.search(version_output or ""))


def parse_brew_prefix(stdout: str) -> str | None:
    lines = (stdout or "").strip().splitlines()
    first = lines[0].strip() if lines else ""
    return first if first.startswith("/") else None


def parse_docker_info(rc: int) -> str:
    # `docker info` exits 0 only when the daemon is reachable.
    return "running" if rc == 0 else "down"


def ml_imports_ok(rc: int) -> bool:
    return rc == 0


# ----------------------- thin probes (real-Mac) ---------------------- #


def find_brew(run: Run) -> str | None:
    rc, _ = run(["/opt/homebrew/bin/brew", "--version"])
    if rc == 0:
        return "/opt/homebrew/bin/brew"
    rc, out = run(["which", "brew"])
    path = out.strip().splitlines()[0] if out.strip() else ""
    return path if rc == 0 and path.startswith("/") else None


def brew_prefix(run: Run) -> str | None:
    rc, out = run(["/opt/homebrew/bin/brew", "--prefix"])
    return parse_brew_prefix(out) if rc == 0 else None


def find_python312(run: Run) -> str | None:
    """Resolve a Python 3.12 interpreter. REQUIRES 3.12 — returns None (never
    the user's python3) if absent, since torch/pyannote have no 3.14 wheels."""
    brew_path = "/opt/homebrew/opt/python@3.12/bin/python3.12"
    rc, out = run([brew_path, "--version"])
    if rc == 0 and is_py312(out):
        return brew_path
    rc, out = run(["python3.12", "--version"])
    if rc == 0 and is_py312(out):
        rc2, w = run(["which", "python3.12"])
        resolved = w.strip().splitlines()[0] if w.strip() else ""
        return resolved if rc2 == 0 and resolved.startswith("/") else "python3.12"
    return None


def ml_python(repo_root: Path) -> Path:
    return repo_root / "worker" / ".venv-ml" / "bin" / "python"


def ml_installed(run: Run, repo_root: Path) -> bool:
    py = ml_python(repo_root)
    if not py.exists():
        return False
    rc, _ = run([str(py), "-c", "import mlx_whisper, torch, pyannote.audio"])
    return ml_imports_ok(rc)


def docker_running(run: Run) -> bool:
    rc, _ = run(["docker", "info"])
    return parse_docker_info(rc) == "running"
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_install_detect.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add app/install/detect.py app/tests/test_install_detect.py
git commit -m "feat: installer detection (pure parsers + injected-run probes, require py3.12)"
```

---

### Task 3: Command + plan builders

**Files:**
- Create: `app/install/commands.py`
- Create: `app/install/plan.py`
- Test: `app/tests/test_install_commands.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `commands.py` pure argv builders: `brew_install(brew, formula)`, `make_ml_venv(py312, repo_root)`, `pip_upgrade(venv_py)`, `pip_install_ml(venv_py, repo_root)`, `compose_up(compose_file)` — each returns `list[str]`.
  - `plan.py`: frozen `Env(repo_root: Path, brew: str | None, py312: str | None, brew_prefix: str)`; `ml_venv_python(repo_root) -> Path`; `plan_for(step_id, env) -> list[list[str]]` (ordered argv commands for an auto step; the `ml` step prepends `brew install python@3.12` when `env.py312 is None`; raises `PrerequisiteMissing` if brew is needed but absent); `PrerequisiteMissing(Exception)`.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_install_commands.py`:

```python
from pathlib import Path

import pytest

from app.install import commands as cmd
from app.install.plan import Env, PrerequisiteMissing, ml_venv_python, plan_for


def test_argv_builders():
    assert cmd.brew_install("/b/brew", "ffmpeg") == ["/b/brew", "install", "ffmpeg"]
    assert cmd.make_ml_venv("py312", Path("/r")) == ["py312", "-m", "venv", "/r/worker/.venv-ml"]
    vp = ml_venv_python(Path("/r"))
    assert cmd.pip_upgrade(vp) == [str(vp), "-m", "pip", "install", "--upgrade", "pip"]
    assert cmd.pip_install_ml(vp, Path("/r")) == [
        str(vp), "-m", "pip", "install", "-r", "/r/worker/requirements-ml.txt"
    ]
    assert cmd.compose_up(Path("/c/docker-compose.yml")) == [
        "docker", "compose", "-f", "/c/docker-compose.yml", "up", "-d", "--wait"
    ]


def _env(**kw):
    base = dict(repo_root=Path("/r"), brew="/b/brew", py312="/p/python3.12", brew_prefix="/opt/homebrew")
    base.update(kw)
    return Env(**base)


def test_plan_ffmpeg_and_py312():
    assert plan_for("ffmpeg", _env()) == [["/b/brew", "install", "ffmpeg"]]
    assert plan_for("py312", _env()) == [["/b/brew", "install", "python@3.12"]]


def test_plan_ml_with_py312_present():
    cmds = plan_for("ml", _env(py312="/p/python3.12"))
    # venv create -> pip upgrade -> pip install ml  (no brew prepend)
    assert cmds[0] == ["/p/python3.12", "-m", "venv", "/r/worker/.venv-ml"]
    assert cmds[-1][-1] == "/r/worker/requirements-ml.txt"
    assert len(cmds) == 3


def test_plan_ml_prepends_py312_when_absent():
    cmds = plan_for("ml", _env(py312=None))
    assert cmds[0] == ["/b/brew", "install", "python@3.12"]  # prerequisite first
    assert cmds[1] == ["/opt/homebrew/opt/python@3.12/bin/python3.12", "-m", "venv", "/r/worker/.venv-ml"]
    assert len(cmds) == 4


def test_plan_ml_without_brew_or_py312_raises():
    with pytest.raises(PrerequisiteMissing):
        plan_for("ml", _env(py312=None, brew=None))


def test_plan_riffado():
    assert plan_for("riffado", _env()) == [
        ["docker", "compose", "-f", "/r/deploy/riffado/docker-compose.yml", "up", "-d", "--wait"]
    ]


def test_plan_unknown_step_raises():
    with pytest.raises(ValueError):
        plan_for("nope", _env())
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_install_commands.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.install.commands'`.

- [ ] **Step 3: Implement the command builders**

Create `app/install/commands.py`:

```python
"""Pure argv builders for installer steps — list[str], never shell strings
(injection-safe). Paths are passed in already-resolved."""

from __future__ import annotations

from pathlib import Path


def brew_install(brew: str, formula: str) -> list[str]:
    return [brew, "install", formula]


def make_ml_venv(py312: str, repo_root: Path) -> list[str]:
    return [py312, "-m", "venv", str(repo_root / "worker" / ".venv-ml")]


def pip_upgrade(venv_py: Path) -> list[str]:
    return [str(venv_py), "-m", "pip", "install", "--upgrade", "pip"]


def pip_install_ml(venv_py: Path, repo_root: Path) -> list[str]:
    return [str(venv_py), "-m", "pip", "install", "-r",
            str(repo_root / "worker" / "requirements-ml.txt")]


def compose_up(compose_file: Path) -> list[str]:
    return ["docker", "compose", "-f", str(compose_file), "up", "-d", "--wait"]
```

- [ ] **Step 4: Implement the plan composer**

Create `app/install/plan.py`:

```python
"""Compose the ordered argv commands for an auto install step from a resolved
Env (brew/py312 paths already discovered by detect.py, so this layer is pure)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.install import commands as cmd


class PrerequisiteMissing(Exception):
    """A needed prerequisite (Homebrew) is absent — the caller surfaces a guide step."""


@dataclass(frozen=True)
class Env:
    repo_root: Path
    brew: str | None         # path to `brew`, or None if absent
    py312: str | None        # path to a Python 3.12 interpreter, or None if absent
    brew_prefix: str         # e.g. "/opt/homebrew"


def ml_venv_python(repo_root: Path) -> Path:
    return repo_root / "worker" / ".venv-ml" / "bin" / "python"


def _require(val: str | None, name: str) -> str:
    if not val:
        raise PrerequisiteMissing(name)
    return val


def plan_for(step_id: str, env: Env) -> list[list[str]]:
    if step_id == "ffmpeg":
        return [cmd.brew_install(_require(env.brew, "Homebrew"), "ffmpeg")]
    if step_id == "py312":
        return [cmd.brew_install(_require(env.brew, "Homebrew"), "python@3.12")]
    if step_id == "ml":
        cmds: list[list[str]] = []
        py = env.py312
        if py is None:
            cmds.append(cmd.brew_install(_require(env.brew, "Homebrew"), "python@3.12"))
            py = env.brew_prefix.rstrip("/") + "/opt/python@3.12/bin/python3.12"
        cmds.append(cmd.make_ml_venv(py, env.repo_root))
        venv_py = ml_venv_python(env.repo_root)
        cmds.append(cmd.pip_upgrade(venv_py))
        cmds.append(cmd.pip_install_ml(venv_py, env.repo_root))
        return cmds
    if step_id == "riffado":
        return [cmd.compose_up(env.repo_root / "deploy" / "riffado" / "docker-compose.yml")]
    raise ValueError(f"no auto-plan for step '{step_id}'")
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_install_commands.py -v`
Expected: PASS (7 tests). Then the full suite: `cd app && ../worker/.venv/bin/python -m pytest`.

- [ ] **Step 6: Commit**

```bash
git add app/install/commands.py app/install/plan.py app/tests/test_install_commands.py
git commit -m "feat: installer argv builders + plan composer (ML targets .venv-ml, py3.12 prereq)"
```

---

## Self-Review

**Spec coverage (Plan 2b-3a = synthesis tasks 1-3):**
- Step registry (ordered, auto/guide) → Task 1. ✓
- Detection parsers + thin injected-run probes (require py3.12, ML-by-import, brew prefix, docker) → Task 2. ✓
- Argv command builders + plan composer (ML → `.venv-ml`, py3.12 prereq prepend) → Task 3. ✓
- **Deferred:** Riffado secret-gen + launchd templates (synthesis tasks 4-5 → Plan 2b-3b); orchestrate/runner + `/api/install` SSE router (tasks 6-7 → Plan 2b-3c); wizard UI + worker-plist repoint (tasks 8-9 → Plan 2b-3d); all real-Mac execution.

**Placeholder scan:** none — every code/test step is complete.

**Type/name consistency:** `Run = Callable[[list[str]], tuple[int, str]]` used by every probe in Task 2 and the fakes in its tests. `Env(repo_root, brew, py312, brew_prefix)` + `plan_for`/`ml_venv_python`/`PrerequisiteMissing` (Task 3) match their tests. `commands.*` builders are consumed by `plan_for`. `detect.ml_python` and `plan.ml_venv_python` both resolve `worker/.venv-ml/bin/python` (kept consistent; a later task may DRY them).

**Hardening honored:** require-3.12-never-fall-back (`find_python312` returns None on 3.14); ML targets `.venv-ml`; ML completeness by import; argv-not-shell; brew/docker/plaud_otp are guide. No side effects in the tested path (probes take injected `run`; only `real_run` touches subprocess and isn't exercised in tests).
