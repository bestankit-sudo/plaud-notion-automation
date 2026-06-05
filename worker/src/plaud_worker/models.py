"""The Meeting model — the structured object the Notion writer renders.

Shaped to match the Circleback note template already in use under the meeting
centrals: overview → topic sections → action items → metadata → attendees table
→ speaker-labelled transcript.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ActionItem:
    owner: str | None  # identified speaker; None -> rendered blank (never "null")
    task: str
    description: str = ""


@dataclass
class Attendee:
    name: str | None
    email: str | None = None


@dataclass
class TranscriptTurn:
    speaker: str | None  # identified name, or "Speaker N" if unknown
    text: str


@dataclass
class Section:
    heading: str
    bullets: list[str]


@dataclass
class Meeting:
    recording_id: str  # Riffado recording id — idempotency key
    title: str
    recorded_at: datetime
    duration_ms: int | None = None
    source_url: str | None = None  # link back to the Riffado recording / audio
    audio_path: str | None = None  # local mp3 to embed as a playable Notion block
    overview: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)
    attendees: list[Attendee] = field(default_factory=list)
    transcript: list[TranscriptTurn] = field(default_factory=list)

    # ---- formatting helpers shared with the writer ----

    @property
    def duration_label(self) -> str:
        if not self.duration_ms:
            return "—"
        secs = round(self.duration_ms / 1000)
        m, s = divmod(secs, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h} hr {m} min {s} sec"
        if m:
            return f"{m} min {s} sec"
        return f"{s} sec"

    # ---- JSON (round-trips for the local meeting cache / rename re-render) ----

    def to_dict(self) -> dict[str, Any]:
        return {
            "recording_id": self.recording_id,
            "title": self.title,
            "recorded_at": self.recorded_at.isoformat(),
            "duration_ms": self.duration_ms,
            "source_url": self.source_url,
            "audio_path": self.audio_path,
            "overview": self.overview,
            "sections": [{"heading": s.heading, "bullets": s.bullets} for s in self.sections],
            "action_items": [
                {"owner": a.owner, "task": a.task, "description": a.description}
                for a in self.action_items
            ],
            "attendees": [{"name": a.name, "email": a.email} for a in self.attendees],
            "transcript": [{"speaker": t.speaker, "text": t.text} for t in self.transcript],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Meeting":
        return cls(
            recording_id=d["recording_id"],
            title=d["title"],
            recorded_at=datetime.fromisoformat(d["recorded_at"]),
            duration_ms=d.get("duration_ms"),
            source_url=d.get("source_url"),
            audio_path=d.get("audio_path"),
            overview=list(d.get("overview", [])),
            sections=[Section(s["heading"], list(s["bullets"])) for s in d.get("sections", [])],
            action_items=[
                ActionItem(a.get("owner"), a["task"], a.get("description", ""))
                for a in d.get("action_items", [])
            ],
            attendees=[Attendee(a.get("name"), a.get("email")) for a in d.get("attendees", [])],
            transcript=[
                TranscriptTurn(t.get("speaker"), t["text"]) for t in d.get("transcript", [])
            ],
        )
