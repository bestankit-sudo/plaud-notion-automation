"""Create/refresh the Speaker Directory page in Notion (who's in which meeting).

    PYTHONPATH=src .venv/bin/python scripts/build_speaker_directory.py
"""

from __future__ import annotations

from plaud_worker.config import Settings
from plaud_worker.directory import build_and_upsert


def main() -> None:
    s = Settings.load()
    page_id = build_and_upsert(s)
    print("directory page:", f"https://www.notion.so/{page_id.replace('-', '')}")


if __name__ == "__main__":
    main()
