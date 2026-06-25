"""launchd entry point: trigger a Riffado sync, then process new recordings.

Runs periodically and on load (boot/login). On a sleeping Mac, launchd defers the
interval and fires it on wake — so this doubles as the boot/wake catch-up: it
pulls anything Plaud synced while away, then reconciles it into Notion.

    PYTHONPATH=src .venv/bin/python scripts/sync_and_reconcile.py
"""

from __future__ import annotations

import sys
import time

from plaud_worker.config import Settings
from plaud_worker.notify import notify_failures
from plaud_worker.reconcile import reconcile
from plaud_worker.relabel import drain_relabel_queue
from plaud_worker.riffado_auth import make_session, trigger_sync


def _log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def main() -> None:
    s = Settings.load()

    if s.riffado_admin_email and s.riffado_admin_password:
        try:
            client = make_session(s.riffado_base_url, s.riffado_admin_email, s.riffado_admin_password)
            result = trigger_sync(client)
            _log(f"sync triggered: {result}")
            time.sleep(20)  # let downloads settle before reconciling
        except Exception as e:  # noqa: BLE001
            _log(f"sync trigger failed (continuing to reconcile): {e}")
    else:
        _log("no RIFFADO_ADMIN_* creds set — skipping sync trigger, reconciling existing")

    drained = drain_relabel_queue(s, on_event=_log)
    if drained:
        _log(f"relabel_queue: drained {drained} re-publish(es)")

    report = reconcile(s, on_event=_log)
    _log(f"reconcile done: {report.summary()}")
    # Ping Telegram on new failures (deduped); also clears recovered recordings.
    notify_failures(
        report,
        state_dir=s.state_dir,
        token=s.telegram_bot_token,
        chat_id=s.telegram_chat_id,
    )
    if report.failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
