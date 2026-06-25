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
