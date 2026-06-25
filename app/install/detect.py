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
