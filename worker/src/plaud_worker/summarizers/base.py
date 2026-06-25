"""The summarizer interface the pipeline calls to turn a labelled transcript
into structured English notes (title / overview / sections / action items)."""

from __future__ import annotations

from typing import Protocol

from ..models import ActionItem, Section


class Summarizer(Protocol):
    def summarize(
        self,
        transcript_text: str,
        *,
        title: str,
        participants: list[str] | None = None,
    ) -> tuple[str, list[str], list[Section], list[ActionItem]]:
        ...
