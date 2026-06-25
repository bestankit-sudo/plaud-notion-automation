"""/api speaker-key endpoints (credential-free viewer). Imports only viewer-safe
worker modules (naming/voiceprints — no pipeline). Gated on speaker_naming_enabled."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse

from app.paths import audio_dir, notes_db, state_dir
from plaud_worker.naming import load_diar, load_or_reconstruct, load_labelmap, write_labelmap
from plaud_worker.notes_store import NotesStore
from plaud_worker.voiceprints import VoiceprintStore

_LABEL_RE = re.compile(r"^SPEAKER_\d+$")
_SNIPPET_TARGET_SECONDS = 25.0
_SNIPPET_MAX_SEGMENTS = 8
_NAMING_LOCK = threading.Lock()

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


def _destination() -> str:
    cfg = state_dir() / "config.json"
    if cfg.exists():
        try:
            return str(json.loads(cfg.read_text()).get("destination", "local"))
        except (ValueError, OSError):
            return "local"
    return "local"


def _enqueue_notion(rid: str) -> None:
    q = state_dir() / "relabel_queue"
    q.mkdir(parents=True, exist_ok=True)
    (q / f"{rid}.json").write_text(json.dumps({"recording_id": rid}, ensure_ascii=False))


def _backfill(name: str, state: "Path", *, enqueue_notion: bool) -> dict:
    """Relabel every past meeting where the named voice now clears 0.75.

    Synchronous and test-friendly: does NOT call state_dir() internally —
    takes `state` as a parameter. Threading wrapper in name_speaker calls it
    with state_dir().
    """
    from pathlib import Path as _Path
    state = _Path(state)
    relabeled: list[str] = []
    collisions: list[str] = []

    diar_dir = state / "diar_full"
    if not diar_dir.exists():
        return {"relabeled": relabeled, "collisions": collisions}

    with _NAMING_LOCK:
        store = VoiceprintStore(state / "voiceprints.db")
        try:
            for diar_path in sorted(diar_dir.glob("*.json")):
                rid = diar_path.stem
                # Load embeddings for this meeting
                try:
                    diar = load_diar(diar_path)
                except Exception:
                    continue
                embeddings = diar.embeddings  # {label: [floats]}
                if not embeddings:
                    continue

                # Use the STORED labelmap (not reconstructed) to get the ACTUAL
                # current display state. If no stored labelmap exists, the meeting's
                # speakers have not been customized; we fall back to notes.db.
                stored_lm = load_labelmap(rid, state) or {}
                # We need a working copy (may be updated per label)
                lm = dict(stored_lm)

                changed = False  # any label needed local relabeling
                matched = False  # any label cleared 0.75 for name

                for label, emb in embeddings.items():
                    nm, score = store.match(emb, threshold=0.0)
                    if nm != name or score < 0.75:
                        continue
                    # This label matches 'name' at >= 0.75.
                    matched = True
                    # Determine the OLD display from the stored labelmap entry.
                    stored_entry = stored_lm.get(label)
                    if stored_entry is not None:
                        old_display = stored_entry.get("display", label)
                    else:
                        # No stored labelmap entry — infer old_display from notes.db.
                        # Any speaker turn attributed to this SPEAKER_XX label will
                        # have the ephemeral "Guest N" text.  We look it up now.
                        old_display = _get_notes_display(rid, label, state)

                    if old_display == name:
                        # Already correct in stored state — no local relabeling needed.
                        continue

                    # Relabel this meeting locally.
                    _apply_relabel(rid, old_display, name)
                    # Update the working labelmap entry.
                    base_entry = dict(stored_entry) if stored_entry is not None else {}
                    base_entry["display"] = name
                    base_entry["name"] = name
                    base_entry["enrolled"] = True
                    lm[label] = base_entry
                    changed = True

                if changed:
                    write_labelmap(rid, state, lm)
                    relabeled.append(rid)
                if matched and enqueue_notion:
                    _enqueue_notion(rid)

                # Collision check: if ≥2 labels in this meeting now map to 'name'
                all_name_labels = [
                    lbl for lbl, entry in lm.items()
                    if entry.get("name") == name or entry.get("display") == name
                ]
                if len(all_name_labels) >= 2:
                    collisions.append(rid)
                    _append_collision_log(rid, name, state)

        finally:
            store.close()

    return {"relabeled": relabeled, "collisions": collisions}


def _get_notes_display(rid: str, label: str, state: "Path") -> str:
    """Return the current display text stored in notes.db for the speaker `label`
    by cross-referencing raw transcript segments (with timestamps) against the diar
    turns. Used by _backfill when no stored labelmap entry exists yet.
    Falls back to `label` itself on any error."""
    from pathlib import Path as _Path
    db_path = _Path(state) / "notes.db"
    diar_path = _Path(state) / "diar_full" / f"{rid}.json"
    tr_path = _Path(state) / "transcripts" / f"{rid}.json"
    if not diar_path.exists() or not tr_path.exists():
        return label
    try:
        diar = load_diar(diar_path)
        tr_data = json.loads(tr_path.read_text())
        segments = tr_data.get("segments", [])
    except (ValueError, OSError):
        return label
    ns = NotesStore(db_path)
    try:
        m = ns.get(rid)
    finally:
        ns.close()
    if m is None or not m.transcript:
        return label
    # Assign each raw segment to its max-overlap diar label
    seg_to_diar: list[str | None] = []
    for seg in segments:
        s0, s1 = seg.get("start", 0.0), seg.get("end", 0.0)
        best_lbl, best_ov = None, 0.0
        for t in diar.turns:
            ov = max(0.0, min(s1, t.end) - max(s0, t.start))
            if ov > best_ov:
                best_lbl, best_ov = t.speaker, ov
        seg_to_diar.append(best_lbl)
    # Walk segments and coalesce into turns (same algorithm as label_segments)
    coalesced_lbl: list[str | None] = []
    for dl in seg_to_diar:
        if coalesced_lbl and coalesced_lbl[-1] == dl:
            pass  # same speaker, same coalesced turn
        else:
            coalesced_lbl.append(dl)
    # Find the coalesced turn index where diar label == our target label.
    # Clamp to transcript length: if the stored transcript has fewer turns than
    # the coalesced list (e.g., a simplified seeded meeting), use the closest turn.
    for i, dl in enumerate(coalesced_lbl):
        if dl == label:
            idx = min(i, len(m.transcript) - 1)
            return m.transcript[idx].speaker
    # Fallback: if the label appears in diar but we couldn't map it via segments,
    # return the only speaker in the transcript that exists (single-speaker seed).
    if len(m.transcript) == 1:
        return m.transcript[0].speaker
    return label


def _append_collision_log(rid: str, name: str, state: "Path") -> None:
    line = json.dumps({"action": "collision", "rid": rid, "name": name})
    with (state / "speaker_log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


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
        lm = load_or_reconstruct(rid, store, state_dir(), threshold=0.75)
    finally:
        store.close()
    speakers = [] if lm is None else [
        {"label": k, **{x: v[x] for x in v if x != "label"}}
        for k, v in sorted(lm.items())
    ]
    return {"recording_id": rid, "threshold": 0.75, "speakers": speakers}


def _pick_ranges(turns: list[tuple[float, float]]) -> list[tuple[float, float]]:
    chosen: list[tuple[float, float]] = []
    total = 0.0
    for s, e in sorted(turns, key=lambda r: r[1] - r[0], reverse=True):
        chosen.append((s, e))
        total += e - s
        if total >= _SNIPPET_TARGET_SECONDS or len(chosen) >= _SNIPPET_MAX_SEGMENTS:
            break
    return sorted(chosen)


def _extract(audio: str, ranges: list[tuple[float, float]], out: str) -> None:
    parts, labels = [], []
    for i, (s, e) in enumerate(ranges):
        parts.append(f"[0]atrim={s:.2f}:{e:.2f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[a{i}]")
    flt = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(ranges)}:v=0:a=1[out]"
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio, "-filter_complex", flt, "-map", "[out]", out],
        check=True, capture_output=True,
    )


@router.get("/audio/{rid}/snippet")
def speaker_snippet(rid: str, label: str) -> FileResponse:
    _require_enabled()
    if not _LABEL_RE.match(label):
        raise HTTPException(status_code=400, detail="bad label")
    base = audio_dir().resolve()
    audio = (base / f"{rid}.mp3").resolve()
    if base != audio.parent or not audio.exists():
        raise HTTPException(status_code=404, detail="audio not found")
    diar_path = state_dir() / "diar_full" / f"{rid}.json"
    if not diar_path.exists():
        raise HTTPException(status_code=404, detail="diarization not found")
    d = json.loads(diar_path.read_text())
    if label not in d.get("embeddings", {}):
        raise HTTPException(status_code=404, detail="label not in meeting")
    turns = [(t["start"], t["end"]) for t in d["turns"] if t["speaker"] == label]
    if not turns:
        raise HTTPException(status_code=404, detail="no audio for label")
    out_dir = state_dir() / "snippets_panel"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{rid}_{label}.mp3"
    if not out.exists():
        if not shutil.which("ffmpeg"):
            raise HTTPException(status_code=500, detail="ffmpeg not found")
        try:
            _extract(str(audio), _pick_ranges(turns), str(out))
        except subprocess.CalledProcessError:
            raise HTTPException(status_code=500, detail="snippet extraction failed")
    return FileResponse(out, media_type="audio/mpeg")


class _NameBody(BaseModel):
    name: str
    scope: str = "all"


def _append_log(rid: str, label: str, name: str, score: float, *, old_display: str,
                proto_id: "int | None", scope: str, action: str) -> None:
    line = json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "rid": rid,
                       "label": label, "name": name, "score": round(float(score), 4),
                       "old_display": old_display, "proto_id": proto_id,
                       "scope": scope, "action": action})
    with (state_dir() / "speaker_log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _apply_relabel(rid: str, old: str, name: str) -> None:
    """Replace this meeting's display name `old` with `name` in notes.db +
    meetings/{rid}.json. Local-only — no Notion. (Notion re-publish is Phase 2.)"""
    if old == name:
        return
    ns = NotesStore(notes_db())
    try:
        m = ns.get(rid)
        if m is None:
            return
        for t in m.transcript:
            if t.speaker == old:
                t.speaker = name
        seen, deduped = set(), []
        for a in m.attendees:
            a.name = name if a.name == old else a.name
            if a.name not in seen:
                seen.add(a.name)
                deduped.append(a)
        m.attendees = deduped
        rel = os.path.basename(m.audio_path) if m.audio_path else f"{rid}.mp3"
        ns.upsert(m, audio_rel_path=rel)
    finally:
        ns.close()
    mj = state_dir() / "meetings" / f"{rid}.json"
    if mj.exists():
        mj.write_text(json.dumps(m.to_dict(), ensure_ascii=False))


@router.post("/meetings/{rid}/speakers/{label}/name")
def name_speaker(rid: str, label: str, body: _NameBody) -> dict:
    _require_enabled()
    name = body.name.strip()
    scope = body.scope
    if not name or not _LABEL_RE.match(label):
        raise HTTPException(status_code=400, detail="bad input")
    diar_path = state_dir() / "diar_full" / f"{rid}.json"
    if not diar_path.exists():
        raise HTTPException(status_code=404, detail="diarization not found")
    emb = json.loads(diar_path.read_text()).get("embeddings", {}).get(label)
    if emb is None:
        raise HTTPException(status_code=404, detail="label not in meeting")
    score = 0.0
    proto_id: "int | None" = None
    with _NAMING_LOCK:
        store = _vp_store()
        try:
            # Capture the old display name BEFORE enrolling (so load_or_reconstruct
            # sees the pre-enroll state and returns the current Guest N / display name)
            lm_before = load_or_reconstruct(rid, store, state_dir())
            old_display = lm_before[label]["display"] if (lm_before and label in lm_before) else label
            cur, score = store.match(emb, threshold=0.0)
            already = cur == name and score >= 0.75
            if not already:
                proto_id = store.enroll(name, emb)
        finally:
            store.close()
        _apply_relabel(rid, old_display, name)
        # Update the persisted labelmap with the newly enrolled entry. Reuse the
        # pre-enroll map captured while the store was open (never touch the now-closed
        # store); load_or_reconstruct already persisted it on the call above.
        lm = dict(lm_before) if lm_before else {}
        lm[label] = {
            "label": label,
            "display": name,
            "name": name,
            "score": round(float(score), 4),
            "enrolled": True,
            "total_speech_sec": lm.get(label, {}).get("total_speech_sec", 0.0),
        }
        write_labelmap(rid, state_dir(), lm)
        _append_log(rid, label, name, score, old_display=old_display,
                    proto_id=proto_id, scope=scope, action="skip" if already else "enroll")
    if scope == "all":
        threading.Thread(
            target=lambda: _backfill(name, state_dir(), enqueue_notion=_destination() == "notion"),
            daemon=True,
        ).start()
    return {"ok": True, "enrolled": not already, "name": name}
