"""Create a contained scratch TEST page under 'Other Meeting Central' (writable by
the integration), and record its id in worker/.env as NOTION_TEST_PARENT_PAGE_ID.

Run once:  PYTHONPATH=src .venv/bin/python scripts/setup_test_page.py
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from plaud_worker.notion import NotionWriter

SHARED = Path(
    os.getenv("PLAUD_SECRETS_FILE", str(Path.home() / ".config/env-variables/secrets.env"))
)
WORKER_ENV = Path(__file__).resolve().parents[1] / ".env"


def main() -> None:
    load_dotenv(SHARED)
    token = os.environ["NOTION_TOKEN"]
    other = os.environ["OTHER_MEETING_CENTRAL_PAGE_ID"]

    with NotionWriter(token) as w:
        page_id = w.create_page(other, "🧪 Plaud Worker — TEST (safe to delete)", emoji="🧪")
        url = w.page_url(page_id)

    # Persist for the worker config (idempotent-ish: append if absent).
    existing = WORKER_ENV.read_text() if WORKER_ENV.exists() else ""
    if "NOTION_TEST_PARENT_PAGE_ID" not in existing:
        with WORKER_ENV.open("a") as fh:
            fh.write(f"\nNOTION_TEST_PARENT_PAGE_ID={page_id}\n")
        print(f"wrote NOTION_TEST_PARENT_PAGE_ID to {WORKER_ENV}")
    else:
        print(f"NOTION_TEST_PARENT_PAGE_ID already in {WORKER_ENV} — leaving as-is")
    print(f"test parent page: {page_id}")
    print(f"open: {url}")


if __name__ == "__main__":
    main()
