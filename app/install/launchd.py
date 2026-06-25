"""Pure launchd plist generation — XML strings via plistlib (paths XML-escaped).
The worker schedule points at worker/.venv-ml; a NEW always-on web agent keeps the
dashboard up. install_argv builds the idempotent bootout->bootstrap launchctl
sequence. No launchctl runs here (real-Mac)."""

from __future__ import annotations

import plistlib
from pathlib import Path

WORKER_LABEL = "com.plaudautomation"
WEB_LABEL = "com.plaudautomation.web"


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
