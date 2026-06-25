"""Local web app — Plan 2a serves the read-only notes viewer. Binds to
127.0.0.1 (see ./run). Credential-free: reads state/notes.db directly."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from plaud_worker.appconfig import AppConfig
from plaud_worker.notes_store import NotesStore

from app.paths import audio_dir, notes_db, state_dir

app = FastAPI(title="plaudautomation")

WEB_DIR = Path(__file__).resolve().parent / "web"


@app.get("/api/meetings")
def list_meetings() -> dict:
    store = NotesStore(notes_db())
    try:
        meetings = store.list_summaries()
    finally:
        store.close()
    return {"destination": AppConfig.load(state_dir()).destination, "meetings": meetings}


@app.get("/api/meetings/{recording_id}")
def get_meeting(recording_id: str) -> dict:
    store = NotesStore(notes_db())
    try:
        meeting = store.get(recording_id)
    finally:
        store.close()
    if meeting is None:
        raise HTTPException(status_code=404, detail="meeting not found")
    data = meeting.to_dict()
    data["duration_label"] = meeting.duration_label
    return data


@app.get("/api/audio/{recording_id}")
def get_audio(recording_id: str) -> FileResponse:
    base = audio_dir().resolve()
    path = (base / f"{recording_id}.mp3").resolve()
    # traversal guard: the resolved file must sit directly under audio_dir()
    if base != path.parent or not path.exists():
        raise HTTPException(status_code=404, detail="audio not found")
    return FileResponse(path, media_type="audio/mpeg")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((WEB_DIR / "index.html").read_text())

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
