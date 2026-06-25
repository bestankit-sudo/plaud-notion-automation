"""Configuration — loads from a shared secrets file plus an optional worker .env.

Secrets live in a shared file outside the repo. By default this is
    ~/.config/env-variables/secrets.env
but you can point elsewhere with the PLAUD_SECRETS_FILE env var. Worker-specific,
non-secret settings (e.g. the scratch test page id) can go in worker/.env, which
overrides nothing sensitive and is gitignored.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

SHARED_SECRETS = Path(
    os.getenv("PLAUD_SECRETS_FILE", str(Path.home() / ".config/env-variables/secrets.env"))
)
WORKER_ENV = Path(__file__).resolve().parents[2] / ".env"


def _load() -> None:
    # Shared secrets first, then worker/.env overrides for non-secret settings.
    if SHARED_SECRETS.exists():
        load_dotenv(SHARED_SECRETS, override=False)
    if WORKER_ENV.exists():
        load_dotenv(WORKER_ENV, override=True)


def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


@dataclass(frozen=True)
class Settings:
    riffado_base_url: str
    riffado_api_key: str
    notion_token: str
    # Parent page the worker writes meeting child-pages under.
    # Defaults to the scratch TEST page; switch to OTHER_MEETING_CENTRAL_PAGE_ID
    # only once the rendered output is verified.
    notion_parent_page_id: str
    openai_api_key: str | None
    # HuggingFace token — used once to download the (gated) pyannote models;
    # diarization/embedding then run fully locally.
    hf_token: str | None
    # Riffado admin login — only needed to TRIGGER a sync headlessly
    # (POST /api/plaud/sync is session-authed). Reconcile works without it.
    riffado_admin_email: str | None
    riffado_admin_password: str | None
    # Telegram bot creds for failure alerts (optional — alerts no-op if unset).
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    # Where the SQLite ledger + voiceprint DB live.
    state_dir: Path

    def skip_recordings(self) -> set[str]:
        """Recording ids to never process (state/skip_recordings.txt, one per
        line, '#' comments). Honoured by reconcile + reprocess_all so a recording
        we deliberately drop never reappears via the headless automation."""
        f = self.state_dir / "skip_recordings.txt"
        if not f.exists():
            return set()
        return {
            line.strip()
            for line in f.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

    @classmethod
    def load(cls) -> "Settings":
        _load()
        state_dir = Path(
            os.getenv("WORKER_STATE_DIR", Path(__file__).resolve().parents[2] / "state")
        )
        state_dir.mkdir(parents=True, exist_ok=True)
        parent = (
            os.getenv("NOTION_TEST_PARENT_PAGE_ID")
            or os.getenv("OTHER_MEETING_CENTRAL_PAGE_ID")
            or ""
        )
        if not parent:
            raise RuntimeError(
                "Set NOTION_TEST_PARENT_PAGE_ID (scratch page) in worker/.env, "
                "or OTHER_MEETING_CENTRAL_PAGE_ID for production."
            )
        return cls(
            riffado_base_url=_require("RIFFADO_BASE_URL").rstrip("/"),
            riffado_api_key=_require("RIFFADO_API_KEY"),
            notion_token=_require("NOTION_TOKEN"),
            notion_parent_page_id=parent,
            openai_api_key=os.getenv("OPENAI_API_KEY_PERSONAL"),
            hf_token=os.getenv("HF_TOKEN"),
            riffado_admin_email=os.getenv("RIFFADO_ADMIN_EMAIL"),
            riffado_admin_password=os.getenv("RIFFADO_ADMIN_PASSWORD"),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
            state_dir=state_dir,
        )
