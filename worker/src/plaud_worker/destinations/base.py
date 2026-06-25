"""The output-destination interface the pipeline writes through."""

from __future__ import annotations

from typing import Protocol

from ..models import Meeting


class Destination(Protocol):
    name: str

    def publish(self, meeting: Meeting, *, prior_ref: str | None = None) -> str:
        """Create or update this meeting's note. Returns a stable ref
        (Notion page id / local recording id) the ledger stores for idempotent
        reruns. `prior_ref` is the previously-stored ref, or None on first write."""
        ...
