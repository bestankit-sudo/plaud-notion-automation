# Riffado Secrets + launchd Templates (Plan 2b-3b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The pure, fully-testable preparation layer for Riffado standup and the launchd agents — generate Riffado secrets idempotently (never rotating a live `POSTGRES_PASSWORD`), and render the worker-schedule + always-on-web launchd plists (with the Homebrew PATH fix and a crash-safe `KeepAlive`).

**Architecture:** Two new pure modules in `app/install/`. `riffado.py` generates secrets via an injectable RNG and writes only the *blank* secret keys into `deploy/riffado/.env` (reusing the existing `app.envfile.upsert`, which chmods 0600). `launchd.py` renders plist XML via `plistlib` (paths XML-escaped) for the worker schedule (pointed at `worker/.venv-ml`) and a NEW always-on web agent, plus the idempotent `launchctl bootout`→`bootstrap` argv. A committed `*.web.plist` fallback template ships alongside. No `docker`/`launchctl`/`openssl` is run here — that's the real-Mac execution shell (later plan).

**Tech Stack:** Python 3.12, stdlib only (`secrets`, `plistlib`, `pathlib`), the existing `app.envfile`, pytest.

## Global Constraints
(from `docs/superpowers/specs/2026-06-25-installer-orchestration-design.md`)
- macOS/arm64, Python 3.12.
- **Riffado secrets:** generate via `secrets.token_hex` — `BETTER_AUTH_SECRET`=hex(32), `ENCRYPTION_KEY`=hex(32), `POSTGRES_PASSWORD`=hex(24). The RNG is **injectable** for deterministic tests. **Reuse existing values only when NON-EMPTY** (a key present but blank counts as missing) so a running `pgdata` volume's `POSTGRES_PASSWORD` is never rotated. Write via `app.envfile.upsert` (inherits chmod 0600), preserving other lines (`RIFFADO_VERSION`/`APP_URL`/`DISABLE_REGISTRATION`). Secrets are never returned in a stream/log (this layer just writes the file).
- **launchd worker plist** points `ProgramArguments[0]` at `worker/.venv-ml/bin/python` (the ML interpreter), `scripts/sync_and_reconcile.py`; `WorkingDirectory={repo}/worker`; `PYTHONPATH=src`; **`PATH` includes `{brew_prefix}/bin:{brew_prefix}/sbin`** (fixes the documented launchd ffmpeg-not-found); `RunAtLoad`, `StartInterval=1800`, logs → `state/automation.log`, `ProcessType=Background`.
- **launchd web plist** runs `uvicorn server:app --host 127.0.0.1 --port {port}`; `WorkingDirectory={repo}/app`; `PYTHONPATH={repo}:{repo}/worker/src` (mirrors `./run`); `RunAtLoad`; **`KeepAlive` is the DICT `{"SuccessfulExit": False, "Crashed": True}`** + **`ThrottleInterval=10`** (not bare `KeepAlive=True`, to avoid a crash-loop when port 8787 is held); logs → `state/web.log`, `ProcessType=Interactive`.
- **`install_argv`** = idempotent `[["launchctl","bootout","gui/{uid}/{label}"], ["launchctl","bootstrap","gui/{uid}",path]]`.
- DRY, YAGNI, TDD, frequent commits. Run app tests as `cd app && ../worker/.venv/bin/python -m pytest`.

> **Decomposition:** Plan 2b-3b of the installer. Done: 2b-3a (pure detect/plan core). Next: 2b-3c (orchestrate/runner + `/api/install` SSE router), 2b-3d (multi-step wizard UI + worker-plist repoint), then real-Mac validation.

---

### Task 1: Riffado secret generation + idempotent .env fill

**Files:**
- Create: `app/install/riffado.py`
- Test: `app/tests/test_riffado_secrets.py`

**Interfaces:**
- Consumes: `app.envfile.upsert(path, values)`.
- Produces: `gen_secrets(rng=secrets.token_hex) -> dict[str,str]` (`BETTER_AUTH_SECRET`/`ENCRYPTION_KEY`/`POSTGRES_PASSWORD`); `missing_secret_keys(existing_text) -> list[str]` (keys whose VALUE is blank/absent); `fill_secrets(existing_text, generated) -> dict[str,str]` (subset to write); `write_env_idempotent(env_path, generated) -> list[str]` (writes only blank keys via `envfile.upsert`, returns the sorted keys written).

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_riffado_secrets.py`:

```python
import stat

from app.install import riffado


def test_gen_secrets_lengths_with_injected_rng():
    s = riffado.gen_secrets(rng=lambda n: "x" * (2 * n))  # mimic token_hex(n) -> 2n chars
    assert s["BETTER_AUTH_SECRET"] == "x" * 64
    assert s["ENCRYPTION_KEY"] == "x" * 64
    assert s["POSTGRES_PASSWORD"] == "x" * 48
    assert set(s) == {"BETTER_AUTH_SECRET", "ENCRYPTION_KEY", "POSTGRES_PASSWORD"}


def test_gen_secrets_default_rng_is_hex():
    s = riffado.gen_secrets()
    assert len(s["BETTER_AUTH_SECRET"]) == 64
    assert all(c in "0123456789abcdef" for c in s["POSTGRES_PASSWORD"])


def test_missing_secret_keys_blank_counts_as_missing():
    assert set(riffado.missing_secret_keys("")) == {
        "BETTER_AUTH_SECRET", "ENCRYPTION_KEY", "POSTGRES_PASSWORD"
    }
    text = "RIFFADO_VERSION=0.5.6\nPOSTGRES_PASSWORD=\nBETTER_AUTH_SECRET=already\nENCRYPTION_KEY=also\n"
    assert riffado.missing_secret_keys(text) == ["POSTGRES_PASSWORD"]  # blank value -> missing
    full = "POSTGRES_PASSWORD=p\nBETTER_AUTH_SECRET=a\nENCRYPTION_KEY=e\n"
    assert riffado.missing_secret_keys(full) == []


def test_fill_secrets_only_missing():
    existing = "BETTER_AUTH_SECRET=keep\nENCRYPTION_KEY=\n"  # POSTGRES absent, ENC blank
    gen = {"BETTER_AUTH_SECRET": "new", "ENCRYPTION_KEY": "newenc", "POSTGRES_PASSWORD": "newpw"}
    out = riffado.fill_secrets(existing, gen)
    assert out == {"ENCRYPTION_KEY": "newenc", "POSTGRES_PASSWORD": "newpw"}  # BETTER_AUTH kept


def test_write_env_idempotent_preserves_and_no_rotation(tmp_path):
    env = tmp_path / ".env"
    env.write_text("RIFFADO_VERSION=0.5.6\nPOSTGRES_PASSWORD=livepw\nBETTER_AUTH_SECRET=\nENCRYPTION_KEY=\n")
    gen = {"BETTER_AUTH_SECRET": "A", "ENCRYPTION_KEY": "E", "POSTGRES_PASSWORD": "ROTATED"}
    written = riffado.write_env_idempotent(env, gen)
    assert written == ["BETTER_AUTH_SECRET", "ENCRYPTION_KEY"]  # POSTGRES not rotated
    text = env.read_text()
    assert "RIFFADO_VERSION=0.5.6" in text
    assert "POSTGRES_PASSWORD=livepw" in text and "ROTATED" not in text
    assert "BETTER_AUTH_SECRET=A" in text and "ENCRYPTION_KEY=E" in text
    assert stat.S_IMODE(env.stat().st_mode) == 0o600  # envfile.upsert chmods
    # re-run writes nothing
    assert riffado.write_env_idempotent(env, gen) == []


def test_write_env_idempotent_creates_when_absent(tmp_path):
    env = tmp_path / "riffado.env"
    written = riffado.write_env_idempotent(env, {"BETTER_AUTH_SECRET": "A", "ENCRYPTION_KEY": "E", "POSTGRES_PASSWORD": "P"})
    assert set(written) == {"BETTER_AUTH_SECRET", "ENCRYPTION_KEY", "POSTGRES_PASSWORD"}
    assert env.exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_riffado_secrets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.install.riffado'`.

- [ ] **Step 3: Implement riffado.py**

Create `app/install/riffado.py`:

```python
"""Riffado standup prep — pure secret generation + idempotent .env fill. The real
`docker compose up` is real-Mac (later plan); this layer only prepares
deploy/riffado/.env. Reuses app.envfile.upsert (chmod 0600). Existing NON-EMPTY
values are kept (a running pgdata volume's POSTGRES_PASSWORD is never rotated)."""

from __future__ import annotations

import secrets as _secrets
from pathlib import Path
from typing import Callable

from app import envfile

# secret name -> number of random bytes (token_hex returns 2x hex chars)
_SECRET_BYTES = {"BETTER_AUTH_SECRET": 32, "ENCRYPTION_KEY": 32, "POSTGRES_PASSWORD": 24}

RngHex = Callable[[int], str]  # nbytes -> hex string


def gen_secrets(rng: RngHex = _secrets.token_hex) -> dict[str, str]:
    return {name: rng(nbytes) for name, nbytes in _SECRET_BYTES.items()}


def _parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip()
    return out


def missing_secret_keys(existing_text: str) -> list[str]:
    """Secret keys whose VALUE is blank/absent (key-present-but-empty counts as missing)."""
    cur = _parse_env(existing_text)
    return [k for k in _SECRET_BYTES if not cur.get(k)]


def fill_secrets(existing_text: str, generated: dict[str, str]) -> dict[str, str]:
    need = set(missing_secret_keys(existing_text))
    return {k: v for k, v in generated.items() if k in need}


def write_env_idempotent(env_path: Path, generated: dict[str, str]) -> list[str]:
    """Fill only the blank/absent secret keys via envfile.upsert (0600), preserving
    every other line. Returns the keys written (empty if all already present)."""
    existing = env_path.read_text() if env_path.exists() else ""
    to_write = fill_secrets(existing, generated)
    if to_write:
        envfile.upsert(env_path, to_write)
    return sorted(to_write)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_riffado_secrets.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add app/install/riffado.py app/tests/test_riffado_secrets.py
git commit -m "feat: Riffado secret-gen + idempotent .env fill (no POSTGRES rotation)"
```

---

### Task 2: launchd plist templates (worker + always-on web) + load argv

**Files:**
- Create: `app/install/launchd.py`
- Create: `deploy/launchd/com.example.plaudautomation.web.plist`
- Test: `app/tests/test_launchd_templates.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `WORKER_LABEL = "com.example.plaudautomation"`, `WEB_LABEL = "com.example.plaudautomation.web"`.
  - `render_worker_plist(repo_root: Path, ml_python: Path, brew_prefix: str) -> str` (plist XML).
  - `render_web_plist(repo_root: Path, server_python: Path, brew_prefix: str, port: int = 8787) -> str` (plist XML).
  - `install_argv(label: str, plist_path: Path, uid: int) -> list[list[str]]` (bootout then bootstrap).
- A committed `deploy/launchd/com.example.plaudautomation.web.plist` template (the documented fallback) with `{repo}`/`{port}` placeholders.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_launchd_templates.py`:

```python
import plistlib
from pathlib import Path

from app.install import launchd


def test_worker_plist_points_at_venv_ml_and_has_brew_path():
    xml = launchd.render_worker_plist(Path("/r"), Path("/r/worker/.venv-ml/bin/python"), "/opt/homebrew")
    d = plistlib.loads(xml.encode())  # valid XML
    assert d["Label"] == "com.example.plaudautomation"
    assert d["ProgramArguments"][0] == "/r/worker/.venv-ml/bin/python"
    assert d["ProgramArguments"][1] == "scripts/sync_and_reconcile.py"
    assert d["WorkingDirectory"] == "/r/worker"
    assert d["EnvironmentVariables"]["PYTHONPATH"] == "src"
    assert "/opt/homebrew/bin" in d["EnvironmentVariables"]["PATH"]
    assert d["StartInterval"] == 1800
    assert d["RunAtLoad"] is True
    assert d["StandardOutPath"].endswith("worker/state/automation.log")
    assert d["ProcessType"] == "Background"


def test_web_plist_keepalive_dict_and_uvicorn():
    xml = launchd.render_web_plist(Path("/r"), Path("/r/worker/.venv/bin/python"), "/opt/homebrew", port=8787)
    d = plistlib.loads(xml.encode())
    assert d["Label"] == "com.example.plaudautomation.web"
    assert d["ProgramArguments"] == [
        "/r/worker/.venv/bin/python", "-m", "uvicorn", "server:app",
        "--host", "127.0.0.1", "--port", "8787",
    ]
    assert d["WorkingDirectory"] == "/r/app"
    assert d["EnvironmentVariables"]["PYTHONPATH"] == "/r:/r/worker/src"
    assert d["KeepAlive"] == {"SuccessfulExit": False, "Crashed": True}  # dict, not bare True
    assert d["ThrottleInterval"] == 10
    assert d["StandardOutPath"].endswith("worker/state/web.log")
    assert d["ProcessType"] == "Interactive"


def test_web_plist_respects_port():
    xml = launchd.render_web_plist(Path("/r"), Path("/p/python"), "/opt/homebrew", port=9001)
    d = plistlib.loads(xml.encode())
    assert "9001" in d["ProgramArguments"]


def test_install_argv_bootout_then_bootstrap():
    argv = launchd.install_argv("com.example.plaudautomation.web", Path("/u/Library/LaunchAgents/x.plist"), 501)
    assert argv == [
        ["launchctl", "bootout", "gui/501/com.example.plaudautomation.web"],
        ["launchctl", "bootstrap", "gui/501", "/u/Library/LaunchAgents/x.plist"],
    ]


def test_committed_web_template_is_valid_plist():
    p = Path(__file__).resolve().parents[2] / "deploy" / "launchd" / "com.example.plaudautomation.web.plist"
    d = plistlib.loads(p.read_bytes())  # parses as a plist
    assert d["Label"] == "com.example.plaudautomation.web"
    assert d["KeepAlive"] == {"SuccessfulExit": False, "Crashed": True}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_launchd_templates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.install.launchd'`.

- [ ] **Step 3: Implement launchd.py**

Create `app/install/launchd.py`:

```python
"""Pure launchd plist generation — XML strings via plistlib (paths XML-escaped).
The worker schedule points at worker/.venv-ml; a NEW always-on web agent keeps the
dashboard up. install_argv builds the idempotent bootout->bootstrap launchctl
sequence. No launchctl runs here (real-Mac)."""

from __future__ import annotations

import plistlib
from pathlib import Path

WORKER_LABEL = "com.example.plaudautomation"
WEB_LABEL = "com.example.plaudautomation.web"


def _path_env(brew_prefix: str) -> str:
    p = brew_prefix.rstrip("/")
    return f"{p}/bin:{p}/sbin:/usr/bin:/bin:/usr/sbin:/sbin"


def render_worker_plist(repo_root: Path, ml_python: Path, brew_prefix: str) -> str:
    plist = {
        "Label": WORKER_LABEL,
        "ProgramArguments": [str(ml_python), "scripts/sync_and_reconcile.py"],
        "WorkingDirectory": str(repo_root / "worker"),
        "EnvironmentVariables": {"PYTHONPATH": "src", "PATH": _path_env(brew_prefix)},
        "RunAtLoad": True,
        "StartInterval": 1800,
        "StandardOutPath": str(repo_root / "worker" / "state" / "automation.log"),
        "StandardErrorPath": str(repo_root / "worker" / "state" / "automation.log"),
        "ProcessType": "Background",
    }
    return plistlib.dumps(plist).decode("utf-8")


def render_web_plist(repo_root: Path, server_python: Path, brew_prefix: str, port: int = 8787) -> str:
    plist = {
        "Label": WEB_LABEL,
        "ProgramArguments": [
            str(server_python), "-m", "uvicorn", "server:app",
            "--host", "127.0.0.1", "--port", str(port),
        ],
        "WorkingDirectory": str(repo_root / "app"),
        "EnvironmentVariables": {
            "PYTHONPATH": f"{repo_root}:{repo_root / 'worker' / 'src'}",
            "PATH": _path_env(brew_prefix),
        },
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False, "Crashed": True},
        "ThrottleInterval": 10,
        "StandardOutPath": str(repo_root / "worker" / "state" / "web.log"),
        "StandardErrorPath": str(repo_root / "worker" / "state" / "web.log"),
        "ProcessType": "Interactive",
    }
    return plistlib.dumps(plist).decode("utf-8")


def install_argv(label: str, plist_path: Path, uid: int) -> list[list[str]]:
    """Idempotent load: bootout (caller ignores 'not loaded') then bootstrap into gui/$UID."""
    return [
        ["launchctl", "bootout", f"gui/{uid}/{label}"],
        ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
    ]
```

- [ ] **Step 4: Create the committed web-plist fallback template**

Create `deploy/launchd/com.example.plaudautomation.web.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!--
  Always-on web dashboard for plaudautomation. KeepAlive (crash-only) keeps
  http://127.0.0.1:8787 up so the bookmarked dashboard survives terminal close.
  The wizard generates this with real paths (app/install/launchd.py); this file
  is the documented fallback template — replace {repo} and load with:
    cp deploy/launchd/com.example.plaudautomation.web.plist ~/Library/LaunchAgents/
    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.plaudautomation.web.plist
-->
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.example.plaudautomation.web</string>
    <key>ProgramArguments</key>
    <array>
        <string>{repo}/worker/.venv/bin/python</string>
        <string>-m</string>
        <string>uvicorn</string>
        <string>server:app</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>8787</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{repo}/app</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>{repo}:{repo}/worker/src</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/opt/homebrew/sbin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>{repo}/worker/state/web.log</string>
    <key>StandardErrorPath</key>
    <string>{repo}/worker/state/web.log</string>
    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_launchd_templates.py -v`
Expected: PASS (5 tests). Then the full suite: `cd app && ../worker/.venv/bin/python -m pytest`.

Note: the committed-template test parses the `.web.plist` with `plistlib`. The `{repo}` placeholders are inside `<string>` values, so it is still valid plist XML and parses fine.

- [ ] **Step 6: Commit**

```bash
git add app/install/launchd.py deploy/launchd/com.example.plaudautomation.web.plist app/tests/test_launchd_templates.py
git commit -m "feat: launchd plist templates (worker -> .venv-ml; crash-safe always-on web agent)"
```

---

## Self-Review

**Spec coverage (Plan 2b-3b = synthesis tasks 4-5):**
- Riffado secret-gen (token_hex 32/32/24, injectable RNG) + idempotent .env fill (non-empty reuse, no POSTGRES rotation, 0600 via envfile) → Task 1. ✓
- launchd worker plist (→ `.venv-ml`, brew PATH) + always-on web plist (`KeepAlive` dict + `ThrottleInterval`, mirrors `./run`) + idempotent `install_argv` (bootout→bootstrap) + committed fallback template → Task 2. ✓
- **Deferred:** the orchestrate/runner control flow + `/api/install` SSE router (2b-3c); wizard UI + worker-plist repoint (2b-3d); real `docker compose`/`launchctl` execution (real-Mac).

**Placeholder scan:** none — every code/test step is complete. (The `{repo}` tokens in the committed template are intentional documented placeholders inside valid plist strings.)

**Type/name consistency:** `riffado.gen_secrets/missing_secret_keys/fill_secrets/write_env_idempotent` (Task 1) match their tests and reuse `app.envfile.upsert`. `launchd.render_worker_plist/render_web_plist/install_argv/WORKER_LABEL/WEB_LABEL` (Task 2) match their tests. The web plist's `ProgramArguments`/`WorkingDirectory`/`PYTHONPATH` mirror the `./run` launch exactly (so launchd and manual launches behave identically). The worker plist's `ProgramArguments[0]` is the caller-supplied `.venv-ml` python (consistent with 2b-3a's `detect.ml_python`).

**Hardening honored:** no rotation of a populated `POSTGRES_PASSWORD`; secrets via stdlib (no openssl subprocess) and written 0600, not streamed; brew prefix injected into the plist PATH (fixes the ffmpeg launchd bug); `KeepAlive` dict + throttle (no crash-loop); pure (no `launchctl`/`docker` executed here).
