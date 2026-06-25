"""Minimal .env upsert — writes the wizard's secrets to worker/.env without
clobbering existing lines or comments. Creates the file 0600 if missing."""

from __future__ import annotations

import os
from pathlib import Path


def upsert(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    remaining = dict(values)
    out: list[str] = []
    for line in lines:
        replaced = False
        for key in list(remaining):
            if line.startswith(f"{key}="):
                out.append(f"{key}={remaining.pop(key)}")
                replaced = True
                break
        if not replaced:
            out.append(line)
    for key, val in remaining.items():  # new keys, in insertion order
        out.append(f"{key}={val}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n")
    os.chmod(path, 0o600)
