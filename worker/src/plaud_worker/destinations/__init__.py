from __future__ import annotations

from .base import Destination
from .local import LocalDestination
from .notion import NotionDestination

__all__ = ["Destination", "LocalDestination", "NotionDestination", "build_destination"]


def build_destination(settings, *, parent_page_id: str | None = None) -> Destination:
    """Resolve the configured destination. Only the chosen one is constructed,
    so a local-only setup never needs Notion credentials."""
    if settings.destination == "local":
        return LocalDestination(settings.state_dir / "notes.db")
    return NotionDestination(
        settings.notion_token, parent_page_id or settings.notion_parent_page_id
    )
