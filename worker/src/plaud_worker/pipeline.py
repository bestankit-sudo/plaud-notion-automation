"""Orchestrator: one recording -> a Circleback-style Notion page.

    pull metadata -> download audio -> transcribe -> diarize -> identify speakers
    -> structure (OpenAI) -> build Meeting -> write Notion -> record in ledger
"""

from __future__ import annotations

from datetime import datetime, timezone

from .config import Settings
from .destinations import build_destination
from .diarize import diarize_cached, label_segments
from .identify import identify_speakers
from .ledger import Ledger
from .models import Attendee, Meeting
from .riffado import RiffadoClient
from .summarizers import build_summarizer
from .transcribe import transcribe_cached
from .voiceprints import VoiceprintStore


def _labelled_transcript(audio_path: str, rid: str, diar, settings) -> list:
    """Speaker-labelled transcript turns. Multilingual meetings (mixed
    Chinese/Hindi/English) are transcribed per speaker-block so each turn keeps
    its original language; monolingual meetings use the faster single pass.
    Both the multilingual flag and the per-block result are cached."""
    import json as _json

    from .models import TranscriptTurn
    from . import multilang

    ml_dir = settings.state_dir / "transcripts_ml"
    ml_cache = ml_dir / f"{rid}.json"
    if ml_cache.exists():
        data = _json.loads(ml_cache.read_text())
        return [TranscriptTurn(speaker=t["speaker"], text=t["text"]) for t in data]

    flag_path = settings.state_dir / "ml_flag" / f"{rid}.json"
    blocks = multilang.merge_blocks(diar.turns)
    if flag_path.exists():
        flag = _json.loads(flag_path.read_text())
        is_ml, secondary = flag["multilingual"], flag.get("secondary")
    else:
        from mlx_whisper.audio import load_audio

        audio = load_audio(audio_path)
        is_ml, secondary = multilang.detect(audio, blocks)
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.write_text(_json.dumps({"multilingual": is_ml, "secondary": secondary}))

    if not is_ml:
        tr = transcribe_cached(audio_path, cache_path=settings.state_dir / "transcripts" / f"{rid}.json")
        return label_segments(tr.segments, diar.turns)

    from mlx_whisper.audio import load_audio

    audio = load_audio(audio_path)
    turns = multilang.transcribe_blocks(audio, blocks, secondary=secondary)
    ml_dir.mkdir(parents=True, exist_ok=True)
    ml_cache.write_text(_json.dumps([{"speaker": t.speaker, "text": t.text} for t in turns],
                                    ensure_ascii=False))
    return turns


def _display_names(turns, id_map: dict[str, str | None]) -> dict[str, str]:
    """Map anonymous labels to display names: an identified person or stable
    handle (Sam Rivers / Jordan / Speaker A...), else an ephemeral 'Guest N'
    for one-off voices we don't recognise (these aren't in the Speaker Key)."""
    display: dict[str, str] = {}
    guest = 0
    for t in turns:
        if t.speaker in display:
            continue
        name = id_map.get(t.speaker)
        if name:
            display[t.speaker] = name
        else:
            guest += 1
            display[t.speaker] = f"Guest {guest}"
    return display


def _write_meeting(meeting: Meeting, settings: Settings, ledger: Ledger,
                   *, parent_page_id: str | None = None) -> str:
    """Publish the meeting to the configured destination, record the ref, and
    return it. Notion publishes update in place when the prior page still exists."""
    destination = build_destination(settings, parent_page_id=parent_page_id)
    try:
        prior = ledger.get_ref(meeting.recording_id, destination.name)
        ref = destination.publish(meeting, prior_ref=prior)
    finally:
        close = getattr(destination, "close", None)
        if close:
            close()
    ledger.set_ref(meeting.recording_id, destination.name, ref)
    ledger.upsert(
        meeting.recording_id,
        notion_page_id=(ref if destination.name == "notion" else None),
        status="processed",
    )
    if destination.name == "notion":
        # link back to the page for the caller to open
        meeting.source_url = "https://www.notion.so/" + ref.replace("-", "")
    return ref


def process_recording(
    rid: str,
    settings: Settings,
    *,
    store: VoiceprintStore,
    ledger: Ledger,
    parent_page_id: str | None = None,
    write: bool = True,
) -> Meeting:
    parent = parent_page_id or settings.notion_parent_page_id

    with RiffadoClient(settings.riffado_base_url, settings.riffado_api_key) as r:
        rec = r.get_recording(rid)
        audio_dir = settings.state_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        dest = audio_dir / f"{rid}.mp3"
        if not dest.exists():
            r.download_audio(rid, str(dest))

    diar = diarize_cached(
        str(dest), settings.hf_token, cache_path=settings.state_dir / "diar_full" / f"{rid}.json"
    )
    # Precision-first: a borderline voice stays a 'Guest' rather than risk a
    # wrong name (we prefer more speakers over a mis-attribution). 0.75 is
    # calibrated from leave-one-out over the prototype library: it cuts the
    # impostor false-accept rate hard (0.55 let voices match a wrong name at
    # ~0.57) while genuine speakers still clear it via their closest prototype.
    id_map = identify_speakers(diar, store, threshold=0.75)
    labelled = _labelled_transcript(str(dest), rid, diar, settings)

    display = _display_names(labelled, id_map)
    for turn in labelled:
        turn.speaker = display.get(turn.speaker, turn.speaker)
    transcript_text = "\n".join(f"{t.speaker}: {t.text}" for t in labelled)

    participants = sorted(set(display.values()))
    gen_title, overview, sections, actions = build_summarizer(settings).summarize(
        transcript_text,
        title=rec.get("title") or "Untitled",
        participants=participants,
    )

    recorded_at = datetime.fromisoformat(rec["recorded_at"].replace("Z", "+00:00"))
    meeting = Meeting(
        recording_id=rid,
        title=gen_title or rec.get("title") or "Untitled recording",
        recorded_at=recorded_at.astimezone(timezone.utc),
        duration_ms=rec.get("duration_ms"),
        source_url=f"{settings.riffado_base_url}/recordings/{rid}",
        audio_path=str(dest),
        overview=overview,
        sections=sections,
        action_items=actions,
        attendees=[Attendee(name=p) for p in participants],
        transcript=labelled,
    )

    # cache the structured meeting so a later speaker-rename can re-render the
    # page without re-transcribing (see scripts/rename_speaker.py)
    import json as _json

    meetings_dir = settings.state_dir / "meetings"
    meetings_dir.mkdir(parents=True, exist_ok=True)
    (meetings_dir / f"{rid}.json").write_text(_json.dumps(meeting.to_dict(), ensure_ascii=False))

    if write:
        _write_meeting(meeting, settings, ledger, parent_page_id=parent_page_id)
    return meeting
