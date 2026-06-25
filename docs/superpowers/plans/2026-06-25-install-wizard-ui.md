# Install Wizard UI (Plan 2b-3e) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the setup wizard drive the installer end-to-end — a new **Phase 0 ("Set up your Mac")** that auto-detects each install step (`/api/install/status`), runs the auto steps with live SSE logs (`/api/install/stream/{id}`), generates Riffado secrets, and loads the launchd background agents (worker + always-on web) — then hands off to the existing destination + AI config phase, then the viewer.

**Architecture:** One new backend endpoint `POST /api/install/launchd/load` (writes both rendered plists to `~/Library/LaunchAgents` — dir overridable via `LAUNCH_AGENTS_DIR` for tests — then `bootout`→`bootstrap` each via the `_runner` seam; this is the "worker-plist repoint" — the worker agent now points at `.venv-ml`). Frontend: a new `app/web/install.js` rendering into a `<section id="install">` added atop `wizard.html`; it consumes the install API (status badges, per-step Run buttons opening an `EventSource`, guide links + Re-check, secrets, launchd load). The existing config `<form id="setup">` and `wizard.js` are unchanged except for a heading. All step/log text rendered via `textContent` (no innerHTML).

**Tech Stack:** Python 3.12, FastAPI, `EventSource` (browser SSE), vanilla JS, the `app/install/*` backend + `/api/install` router (2b-3d).

## Global Constraints
- macOS/arm64, Python 3.12. App binds 127.0.0.1.
- The load endpoint writes only the two FIXED plists (no user input in paths/labels); writes to `LAUNCH_AGENTS_DIR` (default `~/Library/LaunchAgents`); runs `launchctl` only via the `_runner` seam. Tests override `_run`/`_runner`/`LAUNCH_AGENTS_DIR` — no real `launchctl`, no real `~/Library/LaunchAgents` write.
- No secret/PII in any response: the load endpoint returns labels + plist paths + exit codes only (plists contain no secrets).
- Frontend renders all dynamic text (step titles, details, log lines) via `textContent`; SSE log frames are appended as text. Guide/help links use a fixed allowlist from the step registry (`guide_url`), not user input.
- Reuse the `/api/install` router (2b-3d) and the existing wizard (2b-2). DRY, YAGNI, TDD for the endpoint; the UI is validated by driving it in a browser (Playwright), since DOM/SSE glue is not unit-testable.

> **Decomposition:** Plan 2b-3e (final installer plan). Done: 2b-3a/b/c (pure backend), 2b-3d (router). After this: 2c (speaker-naming panel).

---

### Task 1: `POST /api/install/launchd/load` (write plists + bootstrap agents)

**Files:**
- Modify: `app/install_api.py` (add `_launch_agents_dir` + the `launchd_load` route)
- Test: `app/tests/test_install_api.py` (add one test)

**Interfaces:**
- Consumes: `status.resolve_env`, `detect.ml_python`, `launchd.render_worker_plist/render_web_plist/install_argv/WORKER_LABEL/WEB_LABEL`, `_runner.run(argv, on_line)`.
- Produces: `POST /api/install/launchd/load -> {"ok": bool, "agents": [{"label", "plist", "rc"}, ...]}`. `ok` = every agent's `bootstrap` rc == 0. Writes `<LAUNCH_AGENTS_DIR>/<label>.plist` for both labels; for each runs `install_argv` (bootout rc ignored, bootstrap rc recorded).

- [ ] **Step 1: Failing test** — append to `app/tests/test_install_api.py`:

```python
def test_launchd_load_writes_plists_and_bootstraps(client, monkeypatch, tmp_path):
    agents = tmp_path / "agents"
    monkeypatch.setenv("LAUNCH_AGENTS_DIR", str(agents))
    monkeypatch.setattr(install_api, "_run", fake_run({("/opt/homebrew/bin/brew", "--prefix"): (0, "/opt/homebrew\n")}))
    fr = FakeRunner({})  # launchctl bootout/bootstrap -> (0, [])
    monkeypatch.setattr(install_api, "_runner", fr)
    body = client.post("/api/install/launchd/load").json()
    assert body["ok"] is True
    labels = {a["label"] for a in body["agents"]}
    assert labels == {"com.example.plaudautomation", "com.example.plaudautomation.web"}
    assert (agents / "com.example.plaudautomation.plist").exists()
    assert (agents / "com.example.plaudautomation.web.plist").exists()
    bootstraps = [c for c in fr.calls if len(c) >= 2 and c[1] == "bootstrap"]
    assert len(bootstraps) == 2  # one per label
```

- [ ] **Step 2:** Run `cd app && ../worker/.venv/bin/python -m pytest tests/test_install_api.py -k launchd_load -v` → FAIL (404 / no route).

- [ ] **Step 3:** In `app/install_api.py`, add after `_riffado_env`:

```python
def _launch_agents_dir() -> Path:
    return Path(os.getenv("LAUNCH_AGENTS_DIR", str(Path.home() / "Library" / "LaunchAgents")))
```

and after the `launchd_render` route:

```python
@router.post("/launchd/load")
def launchd_load() -> dict:
    repo = _repo_root()
    env = status_mod.resolve_env(_run, repo)
    ml_py = detect.ml_python(repo)
    server_py = repo / "worker" / ".venv" / "bin" / "python"
    agents_dir = _launch_agents_dir()
    agents_dir.mkdir(parents=True, exist_ok=True)
    specs = [
        (launchd.WORKER_LABEL, launchd.render_worker_plist(repo, ml_py, env.brew_prefix)),
        (launchd.WEB_LABEL, launchd.render_web_plist(repo, server_py, env.brew_prefix)),
    ]
    uid = os.getuid()
    agents = []
    for label, xml in specs:
        plist_path = agents_dir / f"{label}.plist"
        plist_path.write_text(xml)
        bootstrap_rc = 0
        for argv in launchd.install_argv(label, plist_path, uid):
            rc = _runner.run(argv, lambda _line: None)
            if argv[1] == "bootstrap":
                bootstrap_rc = rc
        agents.append({"label": label, "plist": str(plist_path), "rc": bootstrap_rc})
    return {"ok": all(a["rc"] == 0 for a in agents), "agents": agents}
```

- [ ] **Step 4:** Run the test + full suite → PASS. Commit.

---

### Task 2: Wizard Phase 0 UI (install.js + wizard.html section)

**Files:**
- Modify: `app/web/wizard.html` (add `<section id="install">` + `<script src="/static/install.js">`)
- Create: `app/web/install.js`
- Modify: `app/web/style.css` (install-phase styles)

**Interfaces:** consumes `GET /api/install/status`, `GET /api/install/stream/{id}` (EventSource), `POST /api/install/riffado/secrets`, `GET /api/install/launchd`, `POST /api/install/launchd/load`. The step registry's `kind` (`auto`/`guide`) and `guide_url` come back in `/status`.

Validated by driving in a browser (Playwright): load → status renders 8 steps → run an auto step → log streams → done badge; guide steps show their link + Re-check; "Start background services" calls load. (No unit test — DOM/SSE glue.)

- [ ] Build `install.js`: fetch status, render each step row (badge: ✓done / ●pending; auto→Run button, guide→link+Re-check). Run opens `EventSource('/api/install/stream/'+id)`, appends each `log` frame's lines to a `<pre>` via `textContent`, sets done/error badge on those frames, closes the source. Riffado step has a "Generate secrets" button (POST secrets) then its Run streams compose-up. Launchd step has "Start background services" (POST load) showing per-agent rc. A "Continue to configuration ↓" link scrolls to the existing form.
- [ ] Add the section to `wizard.html` above the form; give the form a "2 · Configure" heading. Style in `style.css`.
- [ ] Playwright demo against an isolated tmp state (never the live config): status renders, a Run streams a (fake/echo) log, badges update. Screenshot.

---

## Self-Review
- Phase 0 drives every install step + secrets + launchd load → Task 2; the load endpoint (worker-plist repoint) → Task 1. ✓
- Security: load writes only fixed plists to an overridable dir, launchctl only via `_runner`, returns no secrets; UI renders via `textContent`, links from the registry allowlist. ✓
- Deferred: real `launchctl`/install execution is real-Mac (the endpoints are exercised with fakes in tests + driven in a browser against fake/echo streams). 2c (speaker panel) is the next plan.
