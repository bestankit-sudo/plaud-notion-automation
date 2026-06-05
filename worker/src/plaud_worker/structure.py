"""OpenAI structuring — speaker-labelled transcript -> Circleback-style notes.

Produces the overview / topic sections / action items. This is the one stage
that sends transcript text off-machine (to OpenAI), per the approved exception.
"""

from __future__ import annotations

import json

from .models import ActionItem, Section

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "overview": {"type": "array", "items": {"type": "string"}},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "heading": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["heading", "bullets"],
            },
        },
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "owner": {"type": ["string", "null"]},
                    "task": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["owner", "task", "description"],
            },
        },
    },
    "required": ["title", "overview", "sections", "action_items"],
}

_SYSTEM = """You write meeting notes in the exact style of Circleback. From a \
speaker-labelled transcript, produce:
- title: a short, specific meeting title (≈3-8 words) that captures what the \
meeting was actually about — e.g. "Smart Coffee Supply Chain Review" or \
"Q3 Roadmap & Hiring Plan". No date, no time, no trailing punctuation. Always in \
English even when the transcript is in another language.
- overview: 3-6 crisp executive-summary bullets. Bold key facts, names, numbers, \
and dates with **markdown bold**.
- sections: group the discussion into topical sections; each has a short heading \
and detail bullets.
- action_items: concrete next steps. owner MUST be a participant name that appears \
in the transcript, or null if genuinely unclear (never invent a name). task is a \
short imperative; description is one explanatory line.
Be faithful to the transcript. Do not fabricate decisions or owners.
ALWAYS write the overview, sections, and action items in English, even when the \
transcript is in another language (e.g. Chinese). Only the transcript itself stays \
in the original language."""


def structure(
    transcript_text: str,
    *,
    title: str,
    api_key: str,
    model: str = "gpt-5.5",
    participants: list[str] | None = None,
) -> tuple[str, list[str], list[Section], list[ActionItem]]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    who = f"Known participants: {', '.join(participants)}.\n" if participants else ""
    user = f"Meeting title: {title}\n{who}\nTranscript:\n{transcript_text}"

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "meeting_notes", "strict": True, "schema": _SCHEMA},
        },
    )
    data = json.loads(resp.choices[0].message.content)
    gen_title = (data.get("title") or "").strip()
    overview = data["overview"]
    sections = [Section(heading=s["heading"], bullets=s["bullets"]) for s in data["sections"]]
    actions = [
        ActionItem(owner=a["owner"], task=a["task"], description=a.get("description", ""))
        for a in data["action_items"]
    ]
    return gen_title, overview, sections, actions
