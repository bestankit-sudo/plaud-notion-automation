"""/api speaker-key endpoints (credential-free viewer). Imports only viewer-safe
worker modules (naming/voiceprints — no pipeline). Gated on speaker_naming_enabled."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from app.paths import state_dir
from plaud_worker.naming import reconstruct_labelmap
from plaud_worker.voiceprints import VoiceprintStore

router = APIRouter(prefix="/api")


def _vp_store() -> VoiceprintStore:
    return VoiceprintStore(state_dir() / "voiceprints.db")


def _naming_enabled() -> bool:
    cfg = state_dir() / "config.json"
    if cfg.exists():
        try:
            return bool(json.loads(cfg.read_text()).get("speaker_naming_enabled", True))
        except (ValueError, OSError):
            return True
    return True


def _require_enabled() -> None:
    if not _naming_enabled():
        raise HTTPException(status_code=404, detail="speaker naming disabled")


@router.get("/speakers")
def list_speakers() -> dict:
    _require_enabled()
    store = _vp_store()
    try:
        return {"speakers": [{"name": n, "samples": c} for n, c in store.names()]}
    finally:
        store.close()


@router.get("/meetings/{rid}/speakers")
def meeting_speakers(rid: str) -> dict:
    _require_enabled()
    store = _vp_store()
    try:
        lm = reconstruct_labelmap(rid, store, state_dir(), threshold=0.75)
    finally:
        store.close()
    speakers = [] if lm is None else [{"label": k, **v} for k, v in sorted(lm.items())]
    return {"recording_id": rid, "threshold": 0.75, "speakers": speakers}
