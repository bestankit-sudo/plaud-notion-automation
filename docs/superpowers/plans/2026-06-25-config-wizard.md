# Config Wizard (Plan 2b-1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** First-run setup through the browser — a config wizard that lets a fresh clone choose its **destination** (Local/Notion) and **AI provider + model** (with a live cost estimate), enter the needed keys, and persist them to `state/config.json` + `worker/.env`; once configured, `./run` routes to the viewer instead of the wizard.

**Architecture:** Extend the Plan-2a FastAPI app with a `/api/setup/*` router (status, model catalog, config write, secrets write) and a no-build wizard page. All logic is local + testable with no external network calls — writing config/secrets and serving the right page. The actual OS-level installers (Homebrew/Docker/pip-ML/Riffado/launchd) + live "Test connection" + SSE log streaming are **Plan 2b-2** (only validatable on a real Mac).

**Tech Stack:** Python 3.12, FastAPI (existing `app/`), the existing `plaud_worker.appconfig.AppConfig`, vanilla HTML/JS, pytest + FastAPI `TestClient`.

## Global Constraints

- macOS/Apple Silicon, Python 3.12. App reuses `worker/.venv`; binds 127.0.0.1 (in `./run`).
- **Selectable Anthropic models are exactly `claude-opus-4-8` (default), `claude-sonnet-4-6`, `claude-haiku-4-5`** (structured-output support — set in Plan 1; do NOT add Opus 4.7/4.6). OpenAI models per the catalog below. No date suffixes on Anthropic ids.
- **Cost basis:** a ~30-min meeting ≈ **8000 input + 1500 output tokens**. `per_meeting = in_per_1m*8000/1e6 + out_per_1m*1500/1e6`; `per_100 = per_meeting*100`.
- **Secrets go to `worker/.env`** (gitignored), non-secret choices to `state/config.json` (via `AppConfig.save`). The secrets endpoint accepts only an **allowlist** of known keys (no arbitrary env injection). Keys never ship to the browser; the wizard only POSTs them in.
- `worker/.env` location is overridable via `WORKER_ENV_FILE` (so tests never touch the real file); default `<repo>/worker/.env`.
- Frontend renders catalog/model data via `textContent`/DOM nodes (consistent with Plan 2a's injection-safety rule).
- Reuse `plaud_worker.appconfig.AppConfig` (fields: `destination`, `speaker_naming_enabled`, `summarizer_provider`, `summarizer_model`, `notion_parent_page_id`; `.save(state_dir)` writes `state/config.json`). Do not modify it.
- DRY, YAGNI, TDD, frequent commits. Run app tests as `cd app && ../worker/.venv/bin/python -m pytest`.

> **Decomposition:** This is Plan **2b-1** (config wizard). **Plan 2b-2** adds the installer orchestration (brew/docker/pip-ML/Riffado standup), live Test-connection endpoints, SSE install logs, and launchd generation — the parts that need a real Mac. 2b-1 ships the destination/provider/key collection + persistence + routing.

---

### Task 1: Model catalog + cost estimate

**Files:**
- Create: `app/models_catalog.py`
- Test: `app/tests/test_models_catalog.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `TOKEN_PROFILE = {"input_tokens": 8000, "output_tokens": 1500}`; `CATALOG: list[dict]` (each: `provider`, `model`, `label`, `in_per_1m`, `out_per_1m`, `tier`, optional `recommended`/`default`); `cost_for(in_per_1m, out_per_1m) -> dict` (`per_meeting`, `per_100`, rounded); `catalog_with_costs() -> dict` (`token_profile` + `models` = CATALOG entries each with a `cost` key).

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_models_catalog.py`:

```python
from app import models_catalog as mc


def test_cost_for_matches_basis():
    c = mc.cost_for(5.0, 25.0)  # Opus 4.8
    # 8000/1e6*5 + 1500/1e6*25 = 0.04 + 0.0375 = 0.0775
    assert round(c["per_meeting"], 4) == 0.0775
    assert round(c["per_100"], 2) == 7.75


def test_catalog_has_exactly_the_allowed_anthropic_models():
    anthro = {m["model"] for m in mc.CATALOG if m["provider"] == "anthropic"}
    assert anthro == {"claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"}


def test_default_is_opus_4_8():
    defaults = [m for m in mc.CATALOG if m.get("default")]
    assert len(defaults) == 1
    assert defaults[0]["model"] == "claude-opus-4-8"


def test_catalog_with_costs_attaches_cost():
    out = mc.catalog_with_costs()
    assert out["token_profile"]["input_tokens"] == 8000
    by_model = {m["model"]: m for m in out["models"]}
    assert round(by_model["claude-sonnet-4-6"]["cost"]["per_100"], 2) == 4.65
    assert round(by_model["gpt-5.4-nano"]["cost"]["per_100"], 2) == 0.35
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_models_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models_catalog'`.

- [ ] **Step 3: Implement the catalog**

Create `app/models_catalog.py`:

```python
"""Provider/model catalog + per-meeting cost estimate shown in the setup wizard.

Cost basis: a ~30-min meeting is approximated as 8000 input + 1500 output tokens
(title/overview/sections/action-items is light output). Prices are $/1M tokens.
Anthropic models are restricted to those with structured-output support
(see the worker AnthropicSummarizer): opus-4-8 / sonnet-4-6 / haiku-4-5.
"""

from __future__ import annotations

TOKEN_PROFILE = {"input_tokens": 8000, "output_tokens": 1500}

CATALOG: list[dict] = [
    {"provider": "anthropic", "model": "claude-opus-4-8", "label": "Claude Opus 4.8",
     "in_per_1m": 5.0, "out_per_1m": 25.0, "tier": "top quality", "recommended": True, "default": True},
    {"provider": "anthropic", "model": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6",
     "in_per_1m": 3.0, "out_per_1m": 15.0, "tier": "best value", "recommended": True},
    {"provider": "anthropic", "model": "claude-haiku-4-5", "label": "Claude Haiku 4.5",
     "in_per_1m": 1.0, "out_per_1m": 5.0, "tier": "budget"},
    {"provider": "openai", "model": "gpt-5.5", "label": "GPT-5.5",
     "in_per_1m": 5.0, "out_per_1m": 30.0, "tier": "flagship"},
    {"provider": "openai", "model": "gpt-5.5-pro", "label": "GPT-5.5 Pro",
     "in_per_1m": 30.0, "out_per_1m": 180.0, "tier": "premium"},
    {"provider": "openai", "model": "gpt-5.4", "label": "GPT-5.4",
     "in_per_1m": 2.5, "out_per_1m": 15.0, "tier": "balanced"},
    {"provider": "openai", "model": "gpt-5.4-mini", "label": "GPT-5.4 mini",
     "in_per_1m": 0.75, "out_per_1m": 4.5, "tier": "budget"},
    {"provider": "openai", "model": "gpt-5.4-nano", "label": "GPT-5.4 nano",
     "in_per_1m": 0.20, "out_per_1m": 1.25, "tier": "ultra-budget (lowest quality)"},
    {"provider": "openai", "model": "gpt-5", "label": "GPT-5",
     "in_per_1m": 1.25, "out_per_1m": 10.0, "tier": "balanced"},
    {"provider": "openai", "model": "gpt-5-mini", "label": "GPT-5 mini",
     "in_per_1m": 0.25, "out_per_1m": 2.0, "tier": "budget"},
    {"provider": "openai", "model": "gpt-5-nano", "label": "GPT-5 nano",
     "in_per_1m": 0.05, "out_per_1m": 0.40, "tier": "ultra-budget (lowest quality)"},
]


def cost_for(in_per_1m: float, out_per_1m: float) -> dict:
    per_meeting = (
        in_per_1m * TOKEN_PROFILE["input_tokens"] / 1_000_000
        + out_per_1m * TOKEN_PROFILE["output_tokens"] / 1_000_000
    )
    return {"per_meeting": round(per_meeting, 4), "per_100": round(per_meeting * 100, 2)}


def catalog_with_costs() -> dict:
    models = [
        {**m, "cost": cost_for(m["in_per_1m"], m["out_per_1m"])} for m in CATALOG
    ]
    return {"token_profile": TOKEN_PROFILE, "models": models}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_models_catalog.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/models_catalog.py app/tests/test_models_catalog.py
git commit -m "feat: provider/model catalog + per-meeting cost estimate"
```

---

### Task 2: worker/.env writer

**Files:**
- Modify: `app/paths.py` (add `worker_env()`)
- Create: `app/envfile.py`
- Test: `app/tests/test_envfile.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `paths.worker_env() -> Path` (`WORKER_ENV_FILE` env if set, else `<repo>/worker/.env`); `envfile.upsert(path: Path, values: dict[str, str]) -> None` — upserts `KEY=value` lines, preserving other lines/comments, creating the file with `0600` perms if missing.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_envfile.py`:

```python
import stat

from app import envfile, paths


def test_worker_env_honors_override(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_ENV_FILE", str(tmp_path / "x.env"))
    assert paths.worker_env() == tmp_path / "x.env"


def test_worker_env_default(monkeypatch):
    monkeypatch.delenv("WORKER_ENV_FILE", raising=False)
    p = paths.worker_env()
    assert p.name == ".env"
    assert p.parent.name == "worker"


def test_upsert_creates_file_0600(tmp_path):
    f = tmp_path / ".env"
    envfile.upsert(f, {"OPENAI_API_KEY": "sk-1"})
    assert "OPENAI_API_KEY=sk-1" in f.read_text()
    assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_upsert_updates_in_place_and_preserves_other_lines(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# comment\nNOTION_TOKEN=old\nRIFFADO_API_KEY=op_x\n")
    envfile.upsert(f, {"NOTION_TOKEN": "new"})
    text = f.read_text()
    assert "# comment" in text
    assert "RIFFADO_API_KEY=op_x" in text
    assert "NOTION_TOKEN=new" in text
    assert "NOTION_TOKEN=old" not in text
    # no duplicate NOTION_TOKEN lines
    assert text.count("NOTION_TOKEN=") == 1


def test_upsert_appends_new_keys(tmp_path):
    f = tmp_path / ".env"
    f.write_text("A=1\n")
    envfile.upsert(f, {"B": "2"})
    text = f.read_text()
    assert "A=1" in text and "B=2" in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_envfile.py -v`
Expected: FAIL with `AttributeError: module 'app.paths' has no attribute 'worker_env'` (and `ModuleNotFoundError` for `app.envfile`).

- [ ] **Step 3: Add `worker_env()` to paths**

In `app/paths.py`, add this function after `audio_dir`:

```python
def worker_env() -> Path:
    # secrets file the worker loads; overridable for tests via WORKER_ENV_FILE.
    return Path(os.getenv("WORKER_ENV_FILE", _repo_root() / "worker" / ".env"))
```

- [ ] **Step 4: Implement the env writer**

Create `app/envfile.py`:

```python
"""Minimal .env upsert — writes the wizard's secrets to worker/.env without
clobbering existing lines or comments. Creates the file 0600 if missing."""

from __future__ import annotations

import os
from pathlib import Path


def upsert(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    remaining = dict(values)
    out: list[str] = []
    for line in lines:
        replaced = False
        for key in list(remaining):
            if line.startswith(f"{key}="):
                out.append(f"{key}={remaining.pop(key)}")
                replaced = True
                break
        if not replaced:
            out.append(line)
    for key, val in remaining.items():  # new keys, in insertion order
        out.append(f"{key}={val}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n")
    os.chmod(path, 0o600)
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_envfile.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add app/paths.py app/envfile.py app/tests/test_envfile.py
git commit -m "feat: worker/.env writer (upsert, 0600) + paths.worker_env()"
```

---

### Task 3: Setup API (status / models / config / secrets)

**Files:**
- Create: `app/setup_api.py`
- Modify: `app/server.py` (include the router)
- Test: `app/tests/test_setup_api.py`

**Interfaces:**
- Consumes: `app.paths` (`state_dir`, `worker_env`), `app.envfile.upsert`, `app.models_catalog.catalog_with_costs`, `plaud_worker.appconfig.AppConfig`.
- Produces a FastAPI `APIRouter` (`router`) with prefix `/api/setup`:
  - `GET /api/setup/status` → `{configured: bool, destination, summarizer_provider, summarizer_model}` (`configured` = `state/config.json` exists)
  - `GET /api/setup/models` → `catalog_with_costs()`
  - `POST /api/setup/config` (body: `destination`, `summarizer_provider`, `summarizer_model`, `speaker_naming_enabled`=True, `notion_parent_page_id`=None) → writes `AppConfig`; returns `{ok: true}`
  - `POST /api/setup/secrets` (body: `{values: {KEY: value}}`) → upserts the allowlisted keys into `worker/.env`; 400 on any non-allowlisted key; returns `{ok: true, written: [...]}`. Allowlist: `NOTION_TOKEN, OPENAI_API_KEY, OPENAI_API_KEY_PERSONAL, ANTHROPIC_API_KEY, HF_TOKEN, RIFFADO_BASE_URL, RIFFADO_API_KEY, RIFFADO_ADMIN_EMAIL, RIFFADO_ADMIN_PASSWORD`.
- `app/server.py` includes the router.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_setup_api.py`:

```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    state = tmp_path / "state"
    monkeypatch.setenv("WORKER_STATE_DIR", str(state))
    monkeypatch.setenv("WORKER_ENV_FILE", str(tmp_path / ".env"))
    from app.server import app
    return TestClient(app)


def test_status_unconfigured_then_configured(client, tmp_path):
    assert client.get("/api/setup/status").json()["configured"] is False
    r = client.post("/api/setup/config", json={
        "destination": "local", "summarizer_provider": "anthropic",
        "summarizer_model": "claude-opus-4-8", "speaker_naming_enabled": True,
    })
    assert r.status_code == 200 and r.json()["ok"] is True
    st = client.get("/api/setup/status").json()
    assert st["configured"] is True
    assert st["destination"] == "local"
    assert st["summarizer_provider"] == "anthropic"
    assert st["summarizer_model"] == "claude-opus-4-8"


def test_models_endpoint_returns_costed_catalog(client):
    body = client.get("/api/setup/models").json()
    assert body["token_profile"]["input_tokens"] == 8000
    models = {m["model"]: m for m in body["models"]}
    assert "claude-opus-4-8" in models
    assert models["claude-opus-4-8"]["cost"]["per_100"] == 7.75
    # constraint: no Opus 4.7/4.6 offered
    assert "claude-opus-4-7" not in models and "claude-opus-4-6" not in models


def test_secrets_written_to_env_file(client, tmp_path):
    r = client.post("/api/setup/secrets", json={"values": {
        "ANTHROPIC_API_KEY": "ak-test", "HF_TOKEN": "hf-test",
    }})
    assert r.status_code == 200
    env_text = (tmp_path / ".env").read_text()
    assert "ANTHROPIC_API_KEY=ak-test" in env_text
    assert "HF_TOKEN=hf-test" in env_text


def test_secrets_rejects_unknown_key(client):
    r = client.post("/api/setup/secrets", json={"values": {"EVIL_KEY": "x"}})
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_setup_api.py -v`
Expected: FAIL — `/api/setup/*` routes 404 (router not added) / `ModuleNotFoundError` for `app.setup_api`.

- [ ] **Step 3: Implement the setup router**

Create `app/setup_api.py`:

```python
"""Setup wizard API — writes the destination/provider choice to state/config.json
and the secrets to worker/.env. No external calls (live 'Test connection' lands in
Plan 2b-2). Secret keys are allowlisted to prevent arbitrary env injection."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import envfile, paths
from app.models_catalog import catalog_with_costs
from plaud_worker.appconfig import AppConfig

router = APIRouter(prefix="/api/setup")

_ALLOWED_SECRETS = {
    "NOTION_TOKEN", "OPENAI_API_KEY", "OPENAI_API_KEY_PERSONAL", "ANTHROPIC_API_KEY",
    "HF_TOKEN", "RIFFADO_BASE_URL", "RIFFADO_API_KEY",
    "RIFFADO_ADMIN_EMAIL", "RIFFADO_ADMIN_PASSWORD",
}


@router.get("/status")
def status() -> dict:
    sd = paths.state_dir()
    cfg = AppConfig.load(sd)
    return {
        "configured": (sd / "config.json").exists(),
        "destination": cfg.destination,
        "summarizer_provider": cfg.summarizer_provider,
        "summarizer_model": cfg.summarizer_model,
    }


@router.get("/models")
def models() -> dict:
    return catalog_with_costs()


class ConfigIn(BaseModel):
    destination: str
    summarizer_provider: str
    summarizer_model: str
    speaker_naming_enabled: bool = True
    notion_parent_page_id: str | None = None


@router.post("/config")
def write_config(body: ConfigIn) -> dict:
    AppConfig(
        destination=body.destination,
        speaker_naming_enabled=body.speaker_naming_enabled,
        summarizer_provider=body.summarizer_provider,
        summarizer_model=body.summarizer_model,
        notion_parent_page_id=body.notion_parent_page_id,
    ).save(paths.state_dir())
    return {"ok": True}


class SecretsIn(BaseModel):
    values: dict[str, str]


@router.post("/secrets")
def write_secrets(body: SecretsIn) -> dict:
    bad = sorted(set(body.values) - _ALLOWED_SECRETS)
    if bad:
        raise HTTPException(status_code=400, detail=f"unknown secret keys: {bad}")
    envfile.upsert(paths.worker_env(), body.values)
    return {"ok": True, "written": sorted(body.values)}
```

- [ ] **Step 4: Include the router in the app**

In `app/server.py`, add this import with the other `from app...` imports:

```python
from app.setup_api import router as setup_router
```

and add this line immediately after `app = FastAPI(title="plaudautomation")`:

```python
app.include_router(setup_router)
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_setup_api.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add app/setup_api.py app/server.py app/tests/test_setup_api.py
git commit -m "feat: setup API (status/models/config/secrets) with allowlisted secrets"
```

---

### Task 4: Wizard frontend + first-run routing

**Files:**
- Create: `app/web/wizard.html`
- Create: `app/web/wizard.js`
- Modify: `app/server.py` (`GET /` serves wizard vs viewer)
- Modify: `app/web/style.css` (append wizard styles)
- Test: `app/tests/test_wizard_routing.py`

**Interfaces:**
- Consumes: the `/api/setup/*` endpoints (Task 3).
- Produces: `GET /` returns `wizard.html` when `state/config.json` is absent, else the viewer `index.html`. The wizard page collects destination + provider/model (from `/api/setup/models`, with cost) + keys + speaker toggle, POSTs `/api/setup/config` and `/api/setup/secrets`, then reloads (→ viewer).

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_wizard_routing.py`:

```python
import pytest
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WORKER_ENV_FILE", str(tmp_path / ".env"))
    from app.server import app
    return TestClient(app)


def test_root_serves_wizard_when_unconfigured(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/")
    assert r.status_code == 200
    assert "Setup" in r.text  # wizard page marker
    assert "/api/setup/models" in r.text or "wizard.js" in r.text


def test_root_serves_viewer_when_configured(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.post("/api/setup/config", json={
        "destination": "local", "summarizer_provider": "anthropic",
        "summarizer_model": "claude-opus-4-8",
    })
    r = client.get("/")
    assert r.status_code == 200
    # viewer markup (from Plan 2a index.html): the meetings list container
    assert 'id="list"' in r.text


def test_wizard_js_served(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/static/wizard.js")
    assert r.status_code == 200
    assert "/api/setup/config" in r.text
    assert "/api/setup/secrets" in r.text
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_wizard_routing.py -v`
Expected: FAIL — `GET /` always serves the viewer (no wizard branch) and `/static/wizard.js` 404s.

- [ ] **Step 3: Create the wizard page**

Create `app/web/wizard.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>plaudautomation — Setup</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <header><h1>plaudautomation — Setup</h1></header>
  <main class="wizard">
    <form id="setup">
      <fieldset>
        <legend>1 · Where should notes go?</legend>
        <label><input type="radio" name="destination" value="local" checked /> Local (on this Mac — nothing leaves the machine)</label>
        <label><input type="radio" name="destination" value="notion" /> Notion (cloud)</label>
        <div id="notion-fields" hidden>
          <label>Notion integration token <input type="password" name="NOTION_TOKEN" autocomplete="off" /></label>
          <label>Parent page id <input type="text" name="notion_parent_page_id" /></label>
        </div>
      </fieldset>

      <fieldset>
        <legend>2 · Which AI writes the summaries?</legend>
        <div id="models" class="models"></div>
        <label id="provider-key-label">Provider API key
          <input type="password" name="PROVIDER_KEY" autocomplete="off" />
        </label>
      </fieldset>

      <fieldset>
        <legend>3 · Worker access</legend>
        <label>HuggingFace token (one-time, for speaker diarization) <input type="password" name="HF_TOKEN" autocomplete="off" /></label>
        <label>Riffado base URL <input type="text" name="RIFFADO_BASE_URL" value="http://127.0.0.1:3000" /></label>
        <label>Riffado API key <input type="password" name="RIFFADO_API_KEY" autocomplete="off" /></label>
        <label><input type="checkbox" name="speaker_naming_enabled" checked /> Enable speaker naming (name voices from snippets later)</label>
      </fieldset>

      <button type="submit">Finish setup</button>
      <p id="error" class="error" role="alert"></p>
    </form>
  </main>
  <script src="/static/wizard.js"></script>
</body>
</html>
```

- [ ] **Step 4: Create the wizard script**

Create `app/web/wizard.js`:

```javascript
const form = document.getElementById("setup");
const notionFields = document.getElementById("notion-fields");
const modelsEl = document.getElementById("models");
let selectedModel = null;

form.destination.forEach((r) =>
  r.addEventListener("change", () => {
    notionFields.hidden = form.destination.value !== "notion";
  })
);

async function loadModels() {
  const { models } = await (await fetch("/api/setup/models")).json();
  modelsEl.innerHTML = "";
  for (const m of models) {
    const row = document.createElement("label");
    row.className = "model-row";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "model";
    radio.value = m.model;
    radio.dataset.provider = m.provider;
    if (m.default) {
      radio.checked = true;
      selectedModel = m;
    }
    radio.addEventListener("change", () => { selectedModel = m; });
    const name = document.createElement("span");
    name.className = "model-name";
    name.textContent = `${m.label} — ${m.tier}`;
    const cost = document.createElement("span");
    cost.className = "model-cost";
    cost.textContent = `~$${m.cost.per_100.toFixed(2)} / 100 mtgs`;
    row.append(radio, name, cost);
    modelsEl.appendChild(row);
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = document.getElementById("error");
  err.textContent = "";
  if (!selectedModel) { err.textContent = "Pick a model."; return; }
  const destination = form.destination.value;

  const cfg = {
    destination,
    summarizer_provider: selectedModel.provider,
    summarizer_model: selectedModel.model,
    speaker_naming_enabled: form.speaker_naming_enabled.checked,
    notion_parent_page_id: destination === "notion" ? form.notion_parent_page_id.value : null,
  };

  const secrets = {};
  const providerKey = form.PROVIDER_KEY.value.trim();
  if (providerKey) {
    secrets[selectedModel.provider === "anthropic" ? "ANTHROPIC_API_KEY" : "OPENAI_API_KEY"] = providerKey;
  }
  for (const k of ["HF_TOKEN", "RIFFADO_BASE_URL", "RIFFADO_API_KEY"]) {
    if (form[k].value.trim()) secrets[k] = form[k].value.trim();
  }
  if (destination === "notion" && form.NOTION_TOKEN.value.trim()) {
    secrets["NOTION_TOKEN"] = form.NOTION_TOKEN.value.trim();
  }

  try {
    let res = await fetch("/api/setup/config", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cfg),
    });
    if (!res.ok) throw new Error("config save failed");
    if (Object.keys(secrets).length) {
      res = await fetch("/api/setup/secrets", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values: secrets }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "secrets save failed");
    }
    window.location.reload(); // configured → viewer
  } catch (e2) {
    err.textContent = String(e2.message || e2);
  }
});

loadModels();
```

- [ ] **Step 5: Append wizard styles**

Append to `app/web/style.css`:

```css
.wizard { display: block; padding: 24px 28px; max-width: 720px; }
.wizard fieldset { border: 1px solid #e5e5e5; border-radius: 8px; margin: 0 0 18px; padding: 14px 16px; }
.wizard legend { font-weight: 600; padding: 0 6px; }
.wizard label { display: block; margin: 8px 0; }
.wizard input[type=text], .wizard input[type=password] { width: 100%; padding: 6px 8px; margin-top: 4px; }
.wizard input[type=radio], .wizard input[type=checkbox] { width: auto; margin-right: 6px; }
.models { display: flex; flex-direction: column; gap: 4px; margin-bottom: 12px; }
.model-row { display: grid; grid-template-columns: 20px 1fr auto; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px; }
.model-row:hover { background: #fafafa; }
.model-cost { color: #888; font-size: 13px; white-space: nowrap; }
.wizard button { background: #335; color: #fff; border: 0; border-radius: 6px; padding: 10px 18px; font-size: 15px; cursor: pointer; }
.error { color: #c0392b; }
```

- [ ] **Step 6: Route `GET /` to wizard vs viewer**

In `app/server.py`, replace the existing `index` route body so it serves the wizard until configured:

```python
@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    name = "index.html" if (state_dir() / "config.json").exists() else "wizard.html"
    return HTMLResponse((WEB_DIR / name).read_text())
```

(The `/static` mount already serves `wizard.js` / `wizard.html` from `web/`.)

- [ ] **Step 7: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_wizard_routing.py tests/test_setup_api.py tests/test_static.py -v`
Expected: PASS — wizard served when unconfigured, viewer when configured, `wizard.js` served; setup + static suites still green. Then run the full suite: `cd app && ../worker/.venv/bin/python -m pytest`.

- [ ] **Step 8: Commit**

```bash
git add app/web/wizard.html app/web/wizard.js app/web/style.css app/server.py app/tests/test_wizard_routing.py
git commit -m "feat: setup wizard page + first-run routing (wizard until configured)"
```

---

## Self-Review

**Spec coverage (Plan 2b-1 scope):**
- §8 step 5 destination picker (Local/Notion) → Task 4. ✓
- §6 / §8 step 6 provider + model picker with cost table → Tasks 1, 3, 4. ✓
- §7 config + secrets decoupling (state/config.json + worker/.env, conditional/allowlisted) → Tasks 2, 3. ✓
- §8 first-run routing (wizard vs viewer) → Task 4. ✓
- §8 step 7 speaker-naming opt-in toggle → Task 4 (writes `speaker_naming_enabled`). ✓
- **Deferred to Plan 2b-2:** the auto-installers (brew/ffmpeg, pip ML, Docker/Riffado standup), live "Test connection" endpoints, SSE install-log streaming, the Plaud OTP step, and launchd generation (§8 steps 1-4, 8; §11). These need a real Mac to validate.

**Placeholder scan:** none — every code/test step has complete content.

**Type/name consistency:** `models_catalog.cost_for/catalog_with_costs/CATALOG/TOKEN_PROFILE` (Task 1) are used by `setup_api` (Task 3) and asserted in tests. `paths.worker_env()` (Task 2) + `envfile.upsert(path, values)` (Task 2) are used by `setup_api.write_secrets` (Task 3). `AppConfig(...)` fields match Plan 1's dataclass. The `/api/setup/*` routes (Task 3) are consumed by `wizard.js` (Task 4). The `GET /` routing (Task 4) reuses `state_dir()` + `WEB_DIR` from Plan 2a's `server.py`.

**Security/scope:** secrets are allowlisted (no arbitrary env injection), written 0600, never sent to the browser; the wizard page builds model rows via DOM `textContent`; `WORKER_ENV_FILE` keeps tests off the real `worker/.env`. No external network calls in 2b-1 (live Test-connection is 2b-2).
