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
