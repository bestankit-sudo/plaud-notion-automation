"""Worker-side Notion re-publish for relabeled meetings.

When the credential-free VIEWER relabels a speaker on a meeting that has
already been published to Notion, it drops a tiny JSON file in
``state/relabel_queue/{rid}.json``.  On its next scheduled run the WORKER
(this module) drains that queue: it reloads the meeting from the local
notes.db (already locally relabeled by the viewer), then re-publishes the
updated meeting to its existing Notion page via ``NotionWriter``.

The viewer never touches the Notion token — all Notion I/O is worker-only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .ledger import Ledger
from .notes_store import NotesStore


def re_render_for(
    rid: str,
    settings: object,
    writer: object,
    ledger: "Ledger",
) -> bool:
    """Load meeting *rid* from notes.db and re-publish it to its Notion page.

    Returns True if the page was re-published, False if either writer or the
    ledger page-id are absent (idempotent — never creates a duplicate page).
    """
    if writer is None:
        return False

    row = ledger.get(rid)
    if row is None or not row.notion_page_id:
        return False

    ns = NotesStore(settings.state_dir / "notes.db")
    try:
        meeting = ns.get(rid)
    finally:
        ns.close()

    if meeting is None:
        return False

    writer.replace_page_content(row.notion_page_id, meeting)
    return True


def drain_relabel_queue(
    settings: object,
    *,
    on_event: Callable[[str], None] = lambda m: None,
) -> int:
    """Drain ``state/relabel_queue/*.json`` files, re-publishing each to Notion.

    If ``settings.destination != "notion"`` or ``settings.notion_token`` is
    falsy, the queue files are deleted without publishing and 0 is returned.
    Otherwise, a single ``NotionWriter`` context-manager is opened, each
    recording is re-published, and the queue file is deleted after success.

    Returns the number of meetings actually re-published.
    """
    queue_dir: Path = settings.state_dir / "relabel_queue"
    queue_files = sorted(queue_dir.glob("*.json")) if queue_dir.exists() else []

    if not queue_files:
        return 0

    # Determine whether we should publish or just purge the queue.
    destination = getattr(settings, "destination", None)
    notion_token = getattr(settings, "notion_token", None)
    should_publish = (destination == "notion") and bool(notion_token)

    if not should_publish:
        on_event(
            f"relabel_queue: skipping {len(queue_files)} file(s) "
            f"(destination={destination!r}, token={'set' if notion_token else 'missing'})"
        )
        for qf in queue_files:
            qf.unlink(missing_ok=True)
        return 0

    # Import here so the viewer (which never imports this module) stays clean.
    from .notion import NotionWriter  # noqa: PLC0415

    count = 0
    with NotionWriter(notion_token) as writer:
        ledger = Ledger(settings.state_dir / "ledger.db")
        try:
            for qf in queue_files:
                try:
                    data = json.loads(qf.read_text())
                    rid = data["recording_id"]
                except Exception as exc:  # noqa: BLE001
                    on_event(f"relabel_queue: bad queue file {qf.name}: {exc}")
                    qf.unlink(missing_ok=True)
                    continue

                try:
                    published = re_render_for(rid, settings, writer, ledger)
                    if published:
                        count += 1
                        on_event(f"relabel_queue: re-published {rid}")
                    else:
                        on_event(f"relabel_queue: skipped {rid} (no page_id or meeting)")
                except Exception as exc:  # noqa: BLE001
                    on_event(f"relabel_queue: error re-publishing {rid}: {exc}")
                    # Do NOT delete the file — leave it for the next run.
                    continue

                qf.unlink(missing_ok=True)
        finally:
            ledger.close()

    return count
