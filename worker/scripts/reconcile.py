"""Process all unprocessed recordings into Notion (back-catalog or catch-up).

    PYTHONPATH=src .venv/bin/python scripts/reconcile.py [--limit N] [--min-dur 60]

By default writes under the configured parent page (the TEST page until you set
OTHER_MEETING_CENTRAL_PAGE_ID for production).
"""

from __future__ import annotations

import argparse
import time

from plaud_worker.config import Settings
from plaud_worker.reconcile import reconcile


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--min-dur", type=int, default=60)
    ap.add_argument("--parent", default=None, help="Notion parent page id override")
    args = ap.parse_args()

    s = Settings.load()
    t0 = time.time()
    report = reconcile(
        s, parent_page_id=args.parent, min_dur_s=args.min_dur,
        limit=args.limit, on_event=print,
    )
    print(f"\n{report.summary()}  in {time.time()-t0:.0f}s")
    if report.failed:
        print("failures:")
        for rid, err in report.failed:
            print(f"  {rid}: {err[:120]}")


if __name__ == "__main__":
    main()
