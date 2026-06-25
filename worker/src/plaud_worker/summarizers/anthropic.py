"""Anthropic summarizer — same prompt/schema as the OpenAI path, via the
official anthropic SDK with structured outputs. Reuses structure._SYSTEM and
structure._SCHEMA so the two providers stay byte-identical in intent.

Valid models (structured-output support): claude-opus-4-8, claude-sonnet-4-6,
claude-haiku-4-5.
"""

from __future__ import annotations

import json

from ..models import ActionItem, Section
from ..structure import _SCHEMA, _SYSTEM


def _import_anthropic():
    # Lazy import so an OpenAI-only install never requires the anthropic package,
    # and so tests can monkeypatch this seam.
    import anthropic

    return anthropic


class AnthropicSummarizer:
    def __init__(self, api_key: str, model: str):
        anthropic = _import_anthropic()
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def summarize(
        self,
        transcript_text: str,
        *,
        title: str,
        participants: list[str] | None = None,
    ) -> tuple[str, list[str], list[Section], list[ActionItem]]:
        who = f"Known participants: {', '.join(participants)}.\n" if participants else ""
        user = f"Meeting title: {title}\n{who}\nTranscript:\n{transcript_text}"
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=8000,
            system=_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{"role": "user", "content": user}],
        )
        text = next(b.text for b in resp.content if b.type == "text")
        data = json.loads(text)
        gen_title = (data.get("title") or "").strip()
        sections = [Section(heading=s["heading"], bullets=s["bullets"]) for s in data["sections"]]
        actions = [
            ActionItem(owner=a["owner"], task=a["task"], description=a.get("description", ""))
            for a in data["action_items"]
        ]
        return gen_title, data["overview"], sections, actions
