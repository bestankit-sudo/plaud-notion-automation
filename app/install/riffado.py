"""Riffado standup prep — pure secret generation + idempotent .env fill. The real
`docker compose up` is real-Mac (later plan); this layer only prepares
deploy/riffado/.env. Reuses app.envfile.upsert (chmod 0600). Existing NON-EMPTY
values are kept (a running pgdata volume's POSTGRES_PASSWORD is never rotated)."""

from __future__ import annotations

import secrets as _secrets
from pathlib import Path
from typing import Callable

from app import envfile

# secret name -> number of random bytes (token_hex returns 2x hex chars)
_SECRET_BYTES = {"BETTER_AUTH_SECRET": 32, "ENCRYPTION_KEY": 32, "POSTGRES_PASSWORD": 24}

RngHex = Callable[[int], str]  # nbytes -> hex string


def gen_secrets(rng: RngHex = _secrets.token_hex) -> dict[str, str]:
    return {name: rng(nbytes) for name, nbytes in _SECRET_BYTES.items()}


def _parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip()
    return out


def missing_secret_keys(existing_text: str) -> list[str]:
    """Secret keys whose VALUE is blank/absent (key-present-but-empty counts as missing)."""
    cur = _parse_env(existing_text)
    return [k for k in _SECRET_BYTES if not cur.get(k)]


def fill_secrets(existing_text: str, generated: dict[str, str]) -> dict[str, str]:
    need = set(missing_secret_keys(existing_text))
    return {k: v for k, v in generated.items() if k in need}


def write_env_idempotent(env_path: Path, generated: dict[str, str]) -> list[str]:
    """Fill only the blank/absent secret keys via envfile.upsert (0600), preserving
    every other line. Returns the keys written (empty if all already present)."""
    existing = env_path.read_text() if env_path.exists() else ""
    to_write = fill_secrets(existing, generated)
    if to_write:
        envfile.upsert(env_path, to_write)
    return sorted(to_write)
