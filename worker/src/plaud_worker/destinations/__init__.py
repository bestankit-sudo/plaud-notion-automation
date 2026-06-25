from __future__ import annotations

from .base import Destination
from .local import LocalDestination

__all__ = ["Destination", "LocalDestination", "build_destination"]


def build_destination(settings, *, parent_page_id: str | None = None) -> Destination:
    """Resolve the configured destination. Only the chosen one is constructed,
    and the Notion module is imported lazily so a local-only setup never loads
    the Notion client stack."""
    if settings.destination == "local":
        return LocalDestination(settings.state_dir / "notes.db")
    from .notion import NotionDestination
    return NotionDestination(
        settings.notion_token, parent_page_id or settings.notion_parent_page_id
    )
