"""Non-secret app settings the setup wizard writes; read by the worker.

Stored at state/config.json so a shared clone can configure itself without the
owner's central secrets store. Secrets stay in worker/.env (see config.py).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    destination: str = "notion"            # "notion" | "local"
    speaker_naming_enabled: bool = True
    summarizer_provider: str = "openai"    # "openai" | "anthropic"
    summarizer_model: str = "gpt-5.5"
    notion_parent_page_id: str | None = None

    @classmethod
    def load(cls, state_dir: Path) -> "AppConfig":
        path = state_dir / "config.json"
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, state_dir: Path) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "config.json").write_text(json.dumps(asdict(self), indent=2))
