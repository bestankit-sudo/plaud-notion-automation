"""State-dir resolution for the viewer — credential-free (does not import
plaud_worker.config, which requires RIFFADO_* secrets). Mirrors config.py's
WORKER_STATE_DIR / <repo>/worker/state default."""

from __future__ import annotations

import os
from pathlib import Path


def _repo_root() -> Path:
    # app/ lives at <repo>/app — the repo root is its parent.
    return Path(__file__).resolve().parents[1]


def state_dir() -> Path:
    return Path(os.getenv("WORKER_STATE_DIR", _repo_root() / "worker" / "state"))


def notes_db() -> Path:
    return state_dir() / "notes.db"


def audio_dir() -> Path:
    return state_dir() / "audio"


def worker_env() -> Path:
    # secrets file the worker loads; overridable for tests via WORKER_ENV_FILE.
    return Path(os.getenv("WORKER_ENV_FILE", _repo_root() / "worker" / ".env"))
