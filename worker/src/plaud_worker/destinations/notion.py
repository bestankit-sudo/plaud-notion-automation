"""Notion destination — thin wrapper over the existing NotionWriter.

Adds idempotent in-place updates: if the previously-written page still exists,
rewrite it instead of creating a duplicate.
"""

from __future__ import annotations

from ..models import Meeting
from ..notion import NotionWriter


class NotionDestination:
    name = "notion"

    def __init__(self, token: str, parent_page_id: str):
        self._token = token
        self._parent = parent_page_id

    def publish(self, meeting: Meeting, *, prior_ref: str | None = None) -> str:
        with NotionWriter(self._token) as w:
            if prior_ref and w.page_exists(prior_ref):
                w.replace_page_content(prior_ref, meeting)
                return prior_ref
            return w.create_meeting_page(self._parent, meeting)
