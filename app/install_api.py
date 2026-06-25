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
