# Test-Connections (Plan 2b-2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the setup wizard **validate** the credentials it collects — a "Test" button per service (Riffado, Notion, OpenAI, Anthropic, HuggingFace) that makes a cheap authenticated request and reports ✓/✗ — so a fresh clone catches a bad key/URL before finishing setup.

**Architecture:** A `app/conn_check.py` helper (one `probe()` + per-service `check_*` builders, each a single authenticated GET via `httpx`), exposed through `POST /api/setup/test/{service}` endpoints on the existing setup router, with "Test" buttons wired into the Plan-2b-1 wizard page. All logic is unit-tested with a **mocked `httpx`** here; the live calls hit the real services when the user runs `./run` on their Mac.

**Tech Stack:** Python 3.12, FastAPI (existing `app/`), `httpx` (already a dep), vanilla JS, pytest + FastAPI `TestClient`.

## Global Constraints

- macOS/Apple Silicon, Python 3.12. App reuses `worker/.venv`; binds 127.0.0.1.
- Test endpoints take the credential **in the request body** (the wizard validates before saving) and **never echo the credential** back in the response.
- `probe()` maps: 2xx → `{ok: true}`; 401/403 → `{ok: false, detail: "authentication failed ..."}`; other status → `{ok: false, detail: "HTTP <n>"}`; network exception → `{ok: false, detail: "could not reach service: <ExcType>"}` (no secret/stack leakage). Short timeout (8s).
- Service probes (cheap, auth-validating GETs):
  - Riffado: `GET {base_url}/api/v1/recordings` with `Authorization: Bearer {api_key}`.
  - Notion: `GET https://api.notion.com/v1/users/me` with `Authorization: Bearer {token}` + `Notion-Version: 2022-06-28`.
  - OpenAI: `GET https://api.openai.com/v1/models` with `Authorization: Bearer {key}`.
  - Anthropic: `GET https://api.anthropic.com/v1/models` with `x-api-key: {key}` + `anthropic-version: 2023-06-01`.
  - HuggingFace: `GET https://huggingface.co/api/whoami-v2` with `Authorization: Bearer {token}`.
- No real network in tests — monkeypatch `httpx` (conn_check tests) or the `check_*` functions (endpoint tests).
- Frontend keeps the Plan-2a/2b-1 injection-safety discipline (status text via `textContent`).
- DRY, YAGNI, TDD, frequent commits. Run app tests as `cd app && ../worker/.venv/bin/python -m pytest`.

> **Decomposition:** Plan 2b-2 of the wizard. Earlier: 2b-1 (config write). Later: installer orchestration + SSE logs + Riffado standup + launchd (Plan 2b-3, real-Mac), and the speaker-naming panel (Plan 2c).

---

### Task 1: Connection-probe helper

**Files:**
- Create: `app/conn_check.py`
- Test: `app/tests/test_conn_check.py`

**Interfaces:**
- Consumes: `httpx`.
- Produces: `probe(method, url, headers, *, timeout=8.0) -> dict` (`{ok, detail}` per the status mapping above); per-service builders `check_riffado(base_url, api_key)`, `check_notion(token)`, `check_openai(key)`, `check_anthropic(key)`, `check_hf(token)` — each builds the URL+headers and returns `probe(...)`.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_conn_check.py`:

```python
import app.conn_check as cc


class _FakeResp:
    def __init__(self, status_code):
        self.status_code = status_code


class _FakeHttpx:
    """Records the last request and returns a configurable status/exception."""
    def __init__(self):
        self.last = None
        self.status = 200
        self.raise_exc = None

    def request(self, method, url, headers=None, timeout=None):
        self.last = {"method": method, "url": url, "headers": headers or {}, "timeout": timeout}
        if self.raise_exc:
            raise self.raise_exc
        return _FakeResp(self.status)


def _patch(monkeypatch):
    fake = _FakeHttpx()
    monkeypatch.setattr(cc, "httpx", fake)
    return fake


def test_probe_2xx_ok(monkeypatch):
    fake = _patch(monkeypatch); fake.status = 200
    assert cc.probe("GET", "https://x", {})["ok"] is True


def test_probe_401_auth_failed(monkeypatch):
    fake = _patch(monkeypatch); fake.status = 401
    r = cc.probe("GET", "https://x", {})
    assert r["ok"] is False and "auth" in r["detail"].lower()


def test_probe_other_status(monkeypatch):
    fake = _patch(monkeypatch); fake.status = 500
    r = cc.probe("GET", "https://x", {})
    assert r["ok"] is False and "500" in r["detail"]


def test_probe_network_error(monkeypatch):
    fake = _patch(monkeypatch); fake.raise_exc = ConnectionError("boom")
    r = cc.probe("GET", "https://x", {})
    assert r["ok"] is False and "reach" in r["detail"].lower()
    assert "boom" not in r["detail"]  # no exception message / secret leakage


def test_check_riffado_builds_request(monkeypatch):
    fake = _patch(monkeypatch); fake.status = 200
    assert cc.check_riffado("http://127.0.0.1:3000/", "op_k")["ok"] is True
    assert fake.last["url"] == "http://127.0.0.1:3000/api/v1/recordings"
    assert fake.last["headers"]["Authorization"] == "Bearer op_k"


def test_check_anthropic_uses_x_api_key(monkeypatch):
    fake = _patch(monkeypatch); fake.status = 200
    cc.check_anthropic("ak-1")
    assert fake.last["url"] == "https://api.anthropic.com/v1/models"
    assert fake.last["headers"]["x-api-key"] == "ak-1"
    assert fake.last["headers"]["anthropic-version"] == "2023-06-01"


def test_check_notion_and_openai_and_hf_targets(monkeypatch):
    fake = _patch(monkeypatch); fake.status = 200
    cc.check_notion("nt"); assert fake.last["url"] == "https://api.notion.com/v1/users/me"
    assert fake.last["headers"]["Notion-Version"] == "2022-06-28"
    cc.check_openai("sk"); assert fake.last["url"] == "https://api.openai.com/v1/models"
    cc.check_hf("hf"); assert fake.last["url"] == "https://huggingface.co/api/whoami-v2"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_conn_check.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.conn_check'`.

- [ ] **Step 3: Implement the probe + builders**

Create `app/conn_check.py`:

```python
"""Live connection checks for the setup wizard — validate a credential against
its service with one cheap authenticated GET. Returns {ok, detail}; never echoes
the credential or a raw exception message."""

from __future__ import annotations

import httpx


def probe(method: str, url: str, headers: dict[str, str], *, timeout: float = 8.0) -> dict:
    try:
        resp = httpx.request(method, url, headers=headers, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - map any transport error to a clean message
        return {"ok": False, "detail": f"could not reach service: {type(exc).__name__}"}
    if 200 <= resp.status_code < 300:
        return {"ok": True, "detail": "ok"}
    if resp.status_code in (401, 403):
        return {"ok": False, "detail": "authentication failed (check the key/token)"}
    return {"ok": False, "detail": f"HTTP {resp.status_code}"}


def check_riffado(base_url: str, api_key: str) -> dict:
    return probe("GET", base_url.rstrip("/") + "/api/v1/recordings",
                 {"Authorization": f"Bearer {api_key}"})


def check_notion(token: str) -> dict:
    return probe("GET", "https://api.notion.com/v1/users/me",
                 {"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28"})


def check_openai(key: str) -> dict:
    return probe("GET", "https://api.openai.com/v1/models",
                 {"Authorization": f"Bearer {key}"})


def check_anthropic(key: str) -> dict:
    return probe("GET", "https://api.anthropic.com/v1/models",
                 {"x-api-key": key, "anthropic-version": "2023-06-01"})


def check_hf(token: str) -> dict:
    return probe("GET", "https://huggingface.co/api/whoami-v2",
                 {"Authorization": f"Bearer {token}"})
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_conn_check.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add app/conn_check.py app/tests/test_conn_check.py
git commit -m "feat: connection-probe helper for wizard Test buttons"
```

---

### Task 2: Test-connection endpoints

**Files:**
- Modify: `app/setup_api.py` (add 5 `POST /api/setup/test/{service}` endpoints)
- Test: `app/tests/test_setup_test_api.py`

**Interfaces:**
- Consumes: `app.conn_check` (Task 1).
- Produces on the existing `/api/setup` router:
  - `POST /api/setup/test/riffado` (body `{base_url, api_key}`) → `conn_check.check_riffado(...)`
  - `POST /api/setup/test/notion` (body `{token}`) → `check_notion`
  - `POST /api/setup/test/openai` (body `{key}`) → `check_openai`
  - `POST /api/setup/test/anthropic` (body `{key}`) → `check_anthropic`
  - `POST /api/setup/test/hf` (body `{token}`) → `check_hf`
  Each returns the `{ok, detail}` dict from `conn_check`.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_setup_test_api.py`:

```python
import pytest
from fastapi.testclient import TestClient

import app.setup_api as setup_api


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WORKER_ENV_FILE", str(tmp_path / ".env"))
    from app.server import app
    return TestClient(app)


def test_riffado_test_ok(client, monkeypatch):
    captured = {}

    def fake(base_url, api_key):
        captured.update(base_url=base_url, api_key=api_key)
        return {"ok": True, "detail": "ok"}

    monkeypatch.setattr(setup_api.conn_check, "check_riffado", fake)
    r = client.post("/api/setup/test/riffado", json={"base_url": "http://x", "api_key": "k"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert captured == {"base_url": "http://x", "api_key": "k"}


def test_anthropic_test_failure_passthrough(client, monkeypatch):
    monkeypatch.setattr(setup_api.conn_check, "check_anthropic",
                        lambda key: {"ok": False, "detail": "authentication failed (check the key/token)"})
    r = client.post("/api/setup/test/anthropic", json={"key": "bad"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and "auth" in body["detail"].lower()


def test_each_service_endpoint_wired(client, monkeypatch):
    for svc, field in [("notion", "token"), ("openai", "key"), ("hf", "token")]:
        monkeypatch.setattr(setup_api.conn_check, f"check_{svc}",
                            lambda v: {"ok": True, "detail": "ok"})
        r = client.post(f"/api/setup/test/{svc}", json={field: "v"})
        assert r.status_code == 200 and r.json()["ok"] is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_setup_test_api.py -v`
Expected: FAIL — `/api/setup/test/*` routes 404 (not implemented).

- [ ] **Step 3: Add the test endpoints**

In `app/setup_api.py`, add the import at the top (with the other `from app...` imports):

```python
from app import conn_check
```

and append these endpoints to the end of the file:

```python
class RiffadoTestIn(BaseModel):
    base_url: str
    api_key: str


@router.post("/test/riffado")
def test_riffado(body: RiffadoTestIn) -> dict:
    return conn_check.check_riffado(body.base_url, body.api_key)


class TokenIn(BaseModel):
    token: str


class KeyIn(BaseModel):
    key: str


@router.post("/test/notion")
def test_notion(body: TokenIn) -> dict:
    return conn_check.check_notion(body.token)


@router.post("/test/openai")
def test_openai(body: KeyIn) -> dict:
    return conn_check.check_openai(body.key)


@router.post("/test/anthropic")
def test_anthropic(body: KeyIn) -> dict:
    return conn_check.check_anthropic(body.key)


@router.post("/test/hf")
def test_hf(body: TokenIn) -> dict:
    return conn_check.check_hf(body.token)
```

Also update the module docstring's parenthetical "(live 'Test connection' lands in Plan 2b-2)" to "(live 'Test connection' via /api/setup/test/*)".

- [ ] **Step 4: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_setup_test_api.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/setup_api.py app/tests/test_setup_test_api.py
git commit -m "feat: /api/setup/test/* connection-check endpoints"
```

---

### Task 3: Wizard "Test" buttons

**Files:**
- Modify: `app/web/wizard.html` (add Test buttons + status spans)
- Modify: `app/web/wizard.js` (wire the buttons)
- Modify: `app/web/style.css` (append `.test-btn` / `.test-status` styles)
- Test: `app/tests/test_wizard_test_buttons.py`

**Interfaces:**
- Consumes: the `/api/setup/test/*` endpoints (Task 2).
- Produces: in the wizard page, a "Test" button next to the provider key, HF token, Riffado, and Notion fields; clicking POSTs the field value(s) to the matching endpoint and writes ✓/✗ + detail into a status span (via `textContent`). Buttons never block form submit.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_wizard_test_buttons.py`:

```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_STATE_DIR", str(tmp_path / "state"))
    from app.server import app
    return TestClient(app)


def test_wizard_html_has_test_buttons(client):
    html = client.get("/static/wizard.html").text
    assert html.count('class="test-btn"') >= 3  # provider key, HF, riffado (+ notion)


def test_wizard_js_calls_test_endpoints(client):
    js = client.get("/static/wizard.js").text
    assert "/api/setup/test/" in js
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_wizard_test_buttons.py -v`
Expected: FAIL — no `test-btn` in wizard.html, no `/api/setup/test/` in wizard.js.

- [ ] **Step 3: Add Test buttons to the wizard HTML**

In `app/web/wizard.html`, add a Test button + status span next to the relevant inputs. Replace the provider-key label block:

```html
        <label id="provider-key-label">Provider API key
          <input type="password" name="PROVIDER_KEY" autocomplete="off" />
        </label>
```

with:

```html
        <label id="provider-key-label">Provider API key
          <input type="password" name="PROVIDER_KEY" autocomplete="off" />
        </label>
        <button type="button" class="test-btn" data-test="provider">Test key</button>
        <span class="test-status" data-status="provider"></span>
```

Replace the HF token label:

```html
        <label>HuggingFace token (one-time, for speaker diarization) <input type="password" name="HF_TOKEN" autocomplete="off" /></label>
```

with:

```html
        <label>HuggingFace token (one-time, for speaker diarization) <input type="password" name="HF_TOKEN" autocomplete="off" /></label>
        <button type="button" class="test-btn" data-test="hf">Test token</button>
        <span class="test-status" data-status="hf"></span>
```

Replace the Riffado API key label:

```html
        <label>Riffado API key <input type="password" name="RIFFADO_API_KEY" autocomplete="off" /></label>
```

with:

```html
        <label>Riffado API key <input type="password" name="RIFFADO_API_KEY" autocomplete="off" /></label>
        <button type="button" class="test-btn" data-test="riffado">Test connection</button>
        <span class="test-status" data-status="riffado"></span>
```

And inside the `#notion-fields` div, after the parent-page input, add:

```html
          <button type="button" class="test-btn" data-test="notion">Test token</button>
          <span class="test-status" data-status="notion"></span>
```

- [ ] **Step 4: Wire the buttons in wizard.js**

In `app/web/wizard.js`, add this block at the end of the file (after the existing `loadModels()` call):

```javascript
function setStatus(which, ok, detail) {
  const el = document.querySelector(`.test-status[data-status="${which}"]`);
  if (!el) return;
  el.textContent = (ok ? "✓ " : "✗ ") + detail;
  el.className = "test-status " + (ok ? "ok" : "bad");
}

async function runTest(which) {
  let endpoint, payload;
  if (which === "provider") {
    if (!selectedModel) { setStatus("provider", false, "pick a model first"); return; }
    endpoint = selectedModel.provider; // "anthropic" | "openai"
    payload = { key: form.PROVIDER_KEY.value.trim() };
  } else if (which === "hf") {
    endpoint = "hf"; payload = { token: form.HF_TOKEN.value.trim() };
  } else if (which === "notion") {
    endpoint = "notion"; payload = { token: form.NOTION_TOKEN.value.trim() };
  } else if (which === "riffado") {
    endpoint = "riffado";
    payload = { base_url: form.RIFFADO_BASE_URL.value.trim(), api_key: form.RIFFADO_API_KEY.value.trim() };
  }
  setStatus(which, false, "testing…");
  try {
    const res = await fetch(`/api/setup/test/${endpoint}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    const body = await res.json();
    setStatus(which, !!body.ok, body.detail || (body.ok ? "ok" : "failed"));
  } catch (e) {
    setStatus(which, false, "request failed");
  }
}

document.querySelectorAll(".test-btn").forEach((b) =>
  b.addEventListener("click", () => runTest(b.dataset.test))
);
```

Note: the `"testing…"` interim status is shown with `ok=false`; the result overwrites it. `setStatus` uses `textContent` (no injection).

- [ ] **Step 5: Append button styles**

Append to `app/web/style.css`:

```css
.test-btn { background: #eef; color: #335; border: 1px solid #ccd; border-radius: 6px; padding: 4px 10px; font-size: 13px; cursor: pointer; margin: 4px 8px 4px 0; }
.test-status { font-size: 13px; }
.test-status.ok { color: #2ea44f; }
.test-status.bad { color: #c0392b; }
```

- [ ] **Step 6: Run to verify it passes**

Run: `cd app && ../worker/.venv/bin/python -m pytest tests/test_wizard_test_buttons.py tests/test_wizard_routing.py -v`
Expected: PASS — Test buttons present, wizard.js references the test endpoints, routing still works. Then full suite: `cd app && ../worker/.venv/bin/python -m pytest`.

- [ ] **Step 7: Commit**

```bash
git add app/web/wizard.html app/web/wizard.js app/web/style.css app/tests/test_wizard_test_buttons.py
git commit -m "feat: wizard Test buttons (validate keys/services before finishing)"
```

---

## Self-Review

**Spec coverage (Plan 2b-2 scope):**
- §8 "Test connection" buttons per step → Tasks 2, 3 (Riffado, Notion, OpenAI/Anthropic, HF). ✓
- §11 surface a clear pass/fail (no half-state) → `probe()` clean status mapping + inline ✓/✗. ✓
- **Deferred to Plan 2b-3:** the auto-installers (brew/ffmpeg, pip ML, Docker/Riffado standup), SSE install-log streaming, Plaud OTP, launchd generation. **Plan 2c:** speaker-naming panel.

**Placeholder scan:** none — every code/test step has complete content.

**Type/name consistency:** `conn_check.probe` + `check_riffado/notion/openai/anthropic/hf` (Task 1) are called by the `/api/setup/test/*` endpoints (Task 2) and monkeypatched in their tests; `wizard.js runTest` (Task 3) posts to `/api/setup/test/{provider|hf|notion|riffado}` matching the Task 2 routes; `selectedModel.provider` (set in the Plan-2b-1 wizard.js) drives the provider-key endpoint.

**Security/scope:** credentials are sent in the request body and never echoed; `probe()` returns only a generic detail (no exception text, no secret); status rendered via `textContent`; no real network in tests (httpx / check_* mocked). Live validation runs on the user's Mac.
