"""Map install steps to their current state on this machine (via the detect
probes) and resolve an Env. Probes take an injected `run`, so this is testable
with no real subprocess. riffado/plaud_otp are human/runtime-gated -> reported
not-done (the wizard surfaces them as guide/Test steps)."""

from __future__ import annotations

import os
from pathlib import Path

from app.install import detect
from app.install.launchd import WEB_LABEL
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
        rc, _ = run(["launchctl", "print", f"gui/{os.getuid()}/{WEB_LABEL}"])
        return (rc == 0, "loaded" if rc == 0 else "not loaded")
    return (False, "")


def step_status(run: detect.Run, repo_root: Path) -> list[dict]:
    rows: list[dict] = []
    for s in ALL_STEPS:
        done, detail = step_done(s.id, run, repo_root)
        rows.append({
            "id": s.id, "title": s.title, "kind": s.kind,
            "guide_url": s.guide_url, "done": done, "detail": detail,
        })
    return rows
