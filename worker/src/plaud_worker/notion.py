"""Notion writer — renders a Meeting into the exact Circleback note template and
creates/updates a child page under the configured parent.

Template (reverse-engineered from the real Circleback notes in the workspace):
    <source link>
    ### Overview                  -> bullets
    ### <Topic>                    -> bullets   (repeated)
    ### Action Items               -> to_do "Owner: **task**" + child description
    ---
    ### 📋 Meeting Metadata        -> Date / Time / Duration / Tags
    ### 👥 Attendees (N)           -> Name | Email table
    ### 🎙️ Full Transcript         -> "**Name:** text" per turn
"""

from __future__ import annotations

from datetime import timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import httpx

from .models import Meeting

IST = ZoneInfo("Asia/Kolkata")
NOTION_VERSION = "2022-06-28"
_MAX_RT = 2000          # chars per rich-text object
_MAX_CHILDREN = 100     # blocks per append request


# --------------------------------------------------------------------------- #
# rich-text + block builders
# --------------------------------------------------------------------------- #

def _chunks(s: str, n: int = _MAX_RT) -> list[str]:
    s = s or ""
    return [s[i : i + n] for i in range(0, len(s), n)] or [""]


def _rich(content: str, *, bold: bool = False, link: str | None = None) -> list[dict]:
    out = []
    for chunk in _chunks(content):
        text: dict[str, Any] = {"content": chunk}
        if link:
            text["link"] = {"url": link}
        out.append({"type": "text", "text": text, "annotations": {"bold": bold}})
    return out


def _h3(text: str) -> dict:
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": _rich(text)}}


def _bullet(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich(text)},
    }


def _paragraph(rich: list[dict]) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich}}


def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _audio_block(file_upload_id: str) -> dict:
    return {
        "object": "block",
        "type": "audio",
        "audio": {"type": "file_upload", "file_upload": {"id": file_upload_id}},
    }


def _todo(rich: list[dict], description: str = "") -> dict:
    block: dict[str, Any] = {
        "object": "block",
        "type": "to_do",
        "to_do": {"rich_text": rich, "checked": False},
    }
    if description:
        block["to_do"]["children"] = [_paragraph(_rich(description))]
    return block


def _table(headers: list[str], rows: list[list[str]]) -> dict:
    width = len(headers)

    def row(cells: list[str]) -> dict:
        cells = (cells + [""] * width)[:width]
        return {"type": "table_row", "table_row": {"cells": [_rich(c) for c in cells]}}

    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": True,
            "has_row_header": False,
            "children": [row(headers)] + [row(r) for r in rows],
        },
    }


# --------------------------------------------------------------------------- #
# Meeting -> blocks
# --------------------------------------------------------------------------- #

def meeting_title(meeting: Meeting) -> str:
    ist = meeting.recorded_at.astimezone(IST)
    return f"✅ - {meeting.title} | {ist:%d %b %y} | {ist:%H:%M} (IST)"


def build_blocks(meeting: Meeting, *, audio_file_upload_id: str | None = None) -> list[dict]:
    blocks: list[dict] = []

    if audio_file_upload_id:
        # playable recording embedded directly in the page (uploaded audio)
        blocks.append(_audio_block(audio_file_upload_id))
    elif meeting.source_url:
        blocks.append(_paragraph(_rich("View recording in Riffado", link=meeting.source_url)))

    if meeting.overview:
        blocks.append(_h3("Overview"))
        blocks += [_bullet(b) for b in meeting.overview]

    for section in meeting.sections:
        blocks.append(_h3(section.heading))
        blocks += [_bullet(b) for b in section.bullets]

    if meeting.action_items:
        blocks.append(_h3("Action Items"))
        for ai in meeting.action_items:
            if ai.owner:
                rich = _rich(f"{ai.owner}: ") + _rich(ai.task, bold=True)
            else:
                rich = _rich(ai.task, bold=True)
            blocks.append(_todo(rich, ai.description))

    blocks.append(_divider())

    # Metadata
    ist = meeting.recorded_at.astimezone(IST)
    meta = (
        f"Date: {ist:%d %B %Y}\n"
        f"Time: {ist:%H:%M} IST\n"
        f"Duration: {meeting.duration_label}\n"
        f"Tags: —"
    )
    blocks.append(_h3("📋 Meeting Metadata"))
    blocks.append(_paragraph(_rich(meta)))

    # Attendees
    blocks.append(_h3(f"👥 Attendees ({len(meeting.attendees)})"))
    if meeting.attendees:
        rows = [[a.name or "—", a.email or "—"] for a in meeting.attendees]
        blocks.append(_table(["Name", "Email"], rows))

    # Transcript
    blocks.append(_h3("🎙️ Full Transcript"))
    for turn in meeting.transcript:
        speaker = turn.speaker or "Speaker"
        blocks.append(_paragraph(_rich(f"{speaker}:", bold=True) + _rich(f" {turn.text}")))

    return blocks


# --------------------------------------------------------------------------- #
# Notion API client
# --------------------------------------------------------------------------- #

class NotionWriter:
    def __init__(self, token: str, timeout: float = 30.0):
        self._client = httpx.Client(
            base_url="https://api.notion.com/v1",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    def __enter__(self) -> "NotionWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self._client.close()

    def create_page(self, parent_page_id: str, title: str, emoji: str = "📁") -> str:
        """Create a bare child page (no body). Used for the scratch test parent."""
        resp = self._post(
            "/pages",
            {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "icon": {"type": "emoji", "emoji": emoji},
                "properties": {"title": {"title": _rich(title)}},
            },
        )
        return resp["id"]

    def page_url(self, page_id: str) -> str:
        return f"https://www.notion.so/{page_id.replace('-', '')}"

    def create_page_with_blocks(
        self, parent_page_id: str, title: str, blocks: list[dict], emoji: str = "📁"
    ) -> str:
        page_id = self.create_page(parent_page_id, title, emoji)
        self._append_all(page_id, blocks)
        return page_id

    def _upload_audio(self, path: str) -> str | None:
        """Upload a local audio file to Notion (single-part, <20MB) and return its
        file_upload id for embedding. Best-effort: on failure (size/plan limit)
        returns None so the page still renders (with the fallback link)."""
        import os

        name = os.path.basename(path)
        try:
            created = self._post(
                "/file_uploads", {"filename": name, "content_type": "audio/mpeg"}
            )
            with open(path, "rb") as fh:
                resp = httpx.post(
                    created["upload_url"],
                    headers={
                        "Authorization": self._client.headers["Authorization"],
                        "Notion-Version": NOTION_VERSION,
                    },
                    files={"file": (name, fh, "audio/mpeg")},
                    timeout=180.0,
                )
            resp.raise_for_status()
            return created["id"]
        except Exception as e:  # noqa: BLE001
            print(f"  audio upload failed for {name}: {e}")
            return None

    def create_meeting_page(self, parent_page_id: str, meeting: Meeting) -> str:
        """Create the child page (title only), then append the body in batches."""
        audio_id = self._upload_audio(meeting.audio_path) if meeting.audio_path else None
        resp = self._post(
            "/pages",
            {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "icon": {"type": "emoji", "emoji": "🎙️"},
                "properties": {"title": {"title": _rich(meeting_title(meeting))}},
            },
        )
        page_id = resp["id"]
        self._append_all(page_id, build_blocks(meeting, audio_file_upload_id=audio_id))
        return page_id

    def _append_all(self, block_id: str, blocks: list[dict]) -> None:
        for batch in _batched(blocks, _MAX_CHILDREN):
            self._patch(f"/blocks/{block_id}/children", {"children": batch})

    def replace_content(
        self, page_id: str, blocks: list[dict], *, title_text: str | None = None
    ) -> None:
        """Archive a page's current blocks and rewrite them (optionally retitle).
        Used for in-place updates (speaker-rename, directory refresh)."""
        cursor = None
        child_ids: list[str] = []
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            resp = self._client.get(f"/blocks/{page_id}/children", params=params)
            resp.raise_for_status()
            data = resp.json()
            child_ids += [b["id"] for b in data.get("results", [])]
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        for cid in child_ids:
            self._patch(f"/blocks/{cid}", {"archived": True})
        if title_text is not None:
            self._patch(
                f"/pages/{page_id}",
                {"properties": {"title": {"title": _rich(title_text)}}},
            )
        self._append_all(page_id, blocks)

    def replace_page_content(self, page_id: str, meeting: Meeting) -> None:
        """Rewrite a meeting page from `meeting` (rename propagation)."""
        audio_id = self._upload_audio(meeting.audio_path) if meeting.audio_path else None
        self.replace_content(
            page_id,
            build_blocks(meeting, audio_file_upload_id=audio_id),
            title_text=meeting_title(meeting),
        )

    def page_exists(self, page_id: str) -> bool:
        """True iff the page is live. Retries transient errors (429/5xx) and only
        reports False on a genuine 404 — a rate-limited GET must NOT be read as
        'missing', or the caller creates a duplicate page (idempotency bug)."""
        import time

        for _ in range(6):
            resp = self._client.get(f"/pages/{page_id}")
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(float(resp.headers.get("Retry-After", "1")))
                continue
            if resp.status_code == 404:
                return False
            resp.raise_for_status()
            j = resp.json()
            return not j.get("archived", False) and not j.get("in_trash", False)
        resp.raise_for_status()  # exhausted retries -> raise, never silently create
        return False

    # -- low-level with basic 429 handling --

    def _post(self, path: str, body: dict) -> dict:
        return self._request("POST", path, body)

    def _patch(self, path: str, body: dict) -> dict:
        return self._request("PATCH", path, body)

    def _request(self, method: str, path: str, body: dict) -> dict:
        for attempt in range(6):
            resp = self._client.request(method, path, json=body)
            if resp.status_code == 429:
                import time

                time.sleep(float(resp.headers.get("Retry-After", "1")))
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return resp.json()


def _batched(items: list[Any], n: int) -> Iterable[list[Any]]:
    for i in range(0, len(items), n):
        yield items[i : i + n]
