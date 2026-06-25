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
