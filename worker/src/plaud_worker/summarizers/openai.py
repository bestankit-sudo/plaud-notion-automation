"""OpenAI summarizer — wraps the existing structure() call."""

from __future__ import annotations

from ..models import ActionItem, Section
from ..structure import structure


class OpenAISummarizer:
    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model

    def summarize(
        self,
        transcript_text: str,
        *,
        title: str,
        participants: list[str] | None = None,
    ) -> tuple[str, list[str], list[Section], list[ActionItem]]:
        return structure(
            transcript_text,
            title=title,
            api_key=self._api_key,
            model=self._model,
            participants=participants,
        )
