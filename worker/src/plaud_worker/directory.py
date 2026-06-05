"""Speaker Directory page — who appears in which meetings, grouped by the names
currently in the voiceprint library (so it always reflects renames).
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import Settings
from .notion import NotionWriter, _bullet, _h3, _paragraph, _rich
from .riffado import RiffadoClient
from .voiceprints import VoiceprintStore

IST = ZoneInfo("Asia/Kolkata")


def _label(rec: dict) -> str:
    title = rec.get("title") or "?"
    ra = rec.get("recorded_at")
    if ra:
        d = datetime.fromisoformat(ra.replace("Z", "+00:00")).astimezone(IST)
        return f"{title}  ·  {d:%d %b %y}"
    return title


def _blocks(settings: Settings, store: VoiceprintStore, recs: dict) -> list[dict]:
    # Mirror the pipeline exactly: match each recording's per-speaker embedding
    # against the library at the same 0.55 threshold, so the directory's
    # "who's in which meeting" matches what the meeting pages actually show.
    # Per-recording speaker embeddings: prefer the full diarization cache the
    # pipeline writes (turns + embeddings, all recordings); fall back to the
    # legacy embeddings-only cache for any recording not yet reprocessed.
    skip = settings.skip_recordings()
    embeddings_by_rid: dict[str, dict] = {}
    for p in sorted((settings.state_dir / "diar_cache").glob("*.json")):
        if p.stem not in skip:
            embeddings_by_rid[p.stem] = json.loads(p.read_text())
    for p in sorted((settings.state_dir / "diar_full").glob("*.json")):
        if p.stem not in skip:
            embeddings_by_rid[p.stem] = json.loads(p.read_text()).get("embeddings", {})

    person: dict[str, set[str]] = defaultdict(set)
    for rid, embs in embeddings_by_rid.items():
        for _spk, vec in embs.items():
            name, _score = store.match(vec, threshold=0.55)
            if name:
                person[name].add(rid)

    blocks = [
        _paragraph(_rich(
            "Cross-meeting speaker directory. Real people are named; 'Speaker A/B/…' "
            "are recurring voices not yet identified — rename one (scripts/rename_speaker.py) "
            "and every meeting page updates."
        ))
    ]
    # named people first (by meeting count), then unnamed handles
    for name in sorted(person, key=lambda n: (n.startswith("Speaker "), -len(person[n]), n)):
        suffix = "   (unnamed — rename once identified)" if name.startswith("Speaker ") else ""
        blocks.append(_h3(f"{name} — {len(person[name])} meetings{suffix}"))
        for rid in sorted(person[name], key=lambda r: recs.get(r, {}).get("recorded_at", "")):
            blocks.append(_bullet(_label(recs.get(rid, {"title": rid}))))
    return blocks


def build_and_upsert(settings: Settings) -> str:
    """Create or update the single Speaker Directory page; return its id."""
    parent = os.environ["OTHER_MEETING_CENTRAL_PAGE_ID"]
    id_file = settings.state_dir / "directory_page.txt"
    store = VoiceprintStore(settings.state_dir / "voiceprints.db")
    with RiffadoClient(settings.riffado_base_url, settings.riffado_api_key) as r:
        recs = {x["id"]: x for x in r.list_recordings()}
    blocks = _blocks(settings, store, recs)
    store.close()

    with NotionWriter(settings.notion_token) as w:
        existing = id_file.read_text().strip() if id_file.exists() else ""
        if existing and w.page_exists(existing):
            w.replace_content(existing, blocks)
            return existing
        page_id = w.create_page_with_blocks(
            parent, "🔑 Speaker Directory — Plaud", blocks, emoji="🔑"
        )
        id_file.write_text(page_id)
        return page_id
