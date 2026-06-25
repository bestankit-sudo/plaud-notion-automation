"""Setup wizard API — writes the destination/provider choice to state/config.json
and the secrets to worker/.env. No external calls (live 'Test connection' lands in
Plan 2b-2). Secret keys are allowlisted to prevent arbitrary env injection."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import envfile, paths
from app.models_catalog import catalog_with_costs
from plaud_worker.appconfig import AppConfig

router = APIRouter(prefix="/api/setup")

_ALLOWED_SECRETS = {
    "NOTION_TOKEN", "OPENAI_API_KEY", "OPENAI_API_KEY_PERSONAL", "ANTHROPIC_API_KEY",
    "HF_TOKEN", "RIFFADO_BASE_URL", "RIFFADO_API_KEY",
    "RIFFADO_ADMIN_EMAIL", "RIFFADO_ADMIN_PASSWORD",
}


@router.get("/status")
def status() -> dict:
    sd = paths.state_dir()
    cfg = AppConfig.load(sd)
    return {
        "configured": (sd / "config.json").exists(),
        "destination": cfg.destination,
        "summarizer_provider": cfg.summarizer_provider,
        "summarizer_model": cfg.summarizer_model,
    }


@router.get("/models")
def models() -> dict:
    return catalog_with_costs()


class ConfigIn(BaseModel):
    destination: str
    summarizer_provider: str
    summarizer_model: str
    speaker_naming_enabled: bool = True
    notion_parent_page_id: str | None = None


@router.post("/config")
def write_config(body: ConfigIn) -> dict:
    AppConfig(
        destination=body.destination,
        speaker_naming_enabled=body.speaker_naming_enabled,
        summarizer_provider=body.summarizer_provider,
        summarizer_model=body.summarizer_model,
        notion_parent_page_id=body.notion_parent_page_id,
    ).save(paths.state_dir())
    return {"ok": True}


class SecretsIn(BaseModel):
    values: dict[str, str]


@router.post("/secrets")
def write_secrets(body: SecretsIn) -> dict:
    bad = sorted(set(body.values) - _ALLOWED_SECRETS)
    if bad:
        raise HTTPException(status_code=400, detail=f"unknown secret keys: {bad}")
    if any(("\n" in v) or ("\r" in v) for v in body.values.values()):
        raise HTTPException(status_code=400, detail="secret values must not contain newlines")
    envfile.upsert(paths.worker_env(), body.values)
    return {"ok": True, "written": sorted(body.values)}
