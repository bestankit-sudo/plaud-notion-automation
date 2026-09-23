"""replace_content must leave human-authored sub-pages alone.

Notion rejects archiving a child_page through the blocks endpoint (400
"Updating a page via the blocks endpoint unsupported"). The archive loop runs
BEFORE the rewrite, so a single un-archivable block empties the page and then
raises — losing the meeting body. Sub-pages must be skipped, not archived.
"""

from __future__ import annotations

import httpx
import pytest

from plaud_worker.notion import NotionWriter

PAGE = "page-1"
_CHILDREN = [
    {"id": "para-1", "type": "paragraph"},
    {"id": "sub-1", "type": "child_page"},
    {"id": "para-2", "type": "paragraph"},
    {"id": "db-1", "type": "child_database"},
]


def _writer(archived: list[str], appended: list[dict]) -> NotionWriter:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1")
        if request.method == "GET" and path == f"/blocks/{PAGE}/children":
            return httpx.Response(200, json={"results": _CHILDREN, "has_more": False})
        if request.method == "PATCH" and path == f"/blocks/{PAGE}/children":
            import json

            appended.extend(json.loads(request.content)["children"])
            return httpx.Response(200, json={})
        if request.method == "PATCH" and path.startswith("/blocks/"):
            bid = path.rsplit("/", 1)[-1]
            kind = next(b["type"] for b in _CHILDREN if b["id"] == bid)
            if kind in ("child_page", "child_database"):
                # exactly what the real API returns
                return httpx.Response(
                    400,
                    json={
                        "object": "error",
                        "status": 400,
                        "code": "validation_error",
                        "message": "Updating a page via the blocks endpoint unsupported.",
                    },
                )
            archived.append(bid)
            return httpx.Response(200, json={})
        if request.method == "PATCH" and path == f"/pages/{PAGE}":
            return httpx.Response(200, json={})
        raise AssertionError(f"unexpected {request.method} {path}")

    w = NotionWriter.__new__(NotionWriter)
    w._client = httpx.Client(
        base_url="https://api.notion.com/v1", transport=httpx.MockTransport(handler)
    )
    return w


def test_replace_content_skips_subpages_and_still_rewrites() -> None:
    archived: list[str] = []
    appended: list[dict] = []
    w = _writer(archived, appended)
    w.replace_content(PAGE, [{"object": "block", "type": "paragraph"}], title_text="T")

    assert archived == ["para-1", "para-2"], "sub-pages must never be archived"
    assert len(appended) == 1, "the page body must still be rewritten"


def test_replace_content_keeps_raising_on_real_archive_failures() -> None:
    """Only child_page/child_database are exempt — a genuine failure must surface."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1")
        if request.method == "GET":
            return httpx.Response(
                200, json={"results": [{"id": "para-1", "type": "paragraph"}], "has_more": False}
            )
        return httpx.Response(403, json={"code": "restricted_resource"})

    w = NotionWriter.__new__(NotionWriter)
    w._client = httpx.Client(
        base_url="https://api.notion.com/v1", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(httpx.HTTPStatusError):
        w.replace_content(PAGE, [{"object": "block", "type": "paragraph"}])


def test_replace_content_appends_before_archiving_and_keeps_subpage_order() -> None:
    """New content must land *above* retained sub-pages, and be written before the
    old blocks are archived — so a failure mid-rewrite leaves a duplicated page,
    never an empty one."""
    order: list[str] = []
    children = [
        {"id": "para-1", "type": "paragraph"},
        {"id": "para-2", "type": "paragraph"},
        {"id": "sub-1", "type": "child_page"},
    ]
    seen_after: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        path = request.url.path.removeprefix("/v1")
        if request.method == "GET":
            return httpx.Response(200, json={"results": children, "has_more": False})
        if path == f"/blocks/{PAGE}/children":
            body = json.loads(request.content)
            seen_after.append(body.get("after"))
            order.append("append")
            return httpx.Response(200, json={"results": [{"id": "new-1"}]})
        if path.startswith("/blocks/"):
            order.append("archive:" + path.rsplit("/", 1)[-1])
            return httpx.Response(200, json={})
        return httpx.Response(200, json={})

    w = NotionWriter.__new__(NotionWriter)
    w._client = httpx.Client(
        base_url="https://api.notion.com/v1", transport=httpx.MockTransport(handler)
    )
    w.replace_content(PAGE, [{"object": "block", "type": "paragraph"}])

    assert order[0] == "append", "content must be written before anything is archived"
    assert order[1:] == ["archive:para-1", "archive:para-2"]
    assert seen_after == ["para-2"], "new blocks anchor just above the retained sub-page"
