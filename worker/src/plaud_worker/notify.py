"""Best-effort Telegram alerts for the headless automation.

The launchd job fails silently — a broken run just writes ``failed=N`` to a log
nobody watches, so a stuck recording can sit for days unnoticed (it has, twice:
an ffmpeg PATH gap, then an ffmpeg dylib break). This pings a Telegram chat when
recordings fail.

Dedup matters: the reconciler retries failed recordings every 30 min, so a naive
alert would ping on every run. We track which (rid, error) we've already alerted
in ``state/telegram_alerted.json`` and only ping on *new* failures; a recording
that later succeeds is cleared so it re-alerts if it breaks again.

Egress note: this is a deliberate, minimal addition to the approved surface —
only the recording id and a trimmed error string leave the machine (no audio,
transcript, or speaker names). See the project's egress rules.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

_API = "https://api.telegram.org"
# The launchd label for the kickstart hint in alerts. Defaults to the sanitized
# placeholder; set PLAUD_LAUNCHD_LABEL in worker/.env to your real label.
_DEFAULT_LABEL = "com.example.plaudautomation"


def send_telegram(
    text: str,
    *,
    token: str | None,
    chat_id: str | None,
    timeout: float = 10.0,
) -> bool:
    """POST one message to the bot. Returns True on success, False on any error.

    Best-effort by contract: a notification must never crash the automation, so
    every failure path (missing creds, network, non-200) returns False quietly.
    """
    if not token or not chat_id:
        return False
    try:
        resp = httpx.post(
            f"{_API}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=timeout,
        )
        return resp.status_code == 200
    except Exception:  # noqa: BLE001 - best-effort, swallow everything
        return False


def notify_failures(
    report,
    *,
    state_dir: Path,
    token: str | None,
    chat_id: str | None,
) -> None:
    """Alert on newly-failed recordings, deduped against prior runs.

    Call this on every run (not just failing ones): a run with no failures still
    needs to clear recovered recordings from the dedup state so a future failure
    re-alerts. No-op if Telegram isn't configured.
    """
    alerted_path = state_dir / "telegram_alerted.json"
    try:
        alerted: dict[str, str] = (
            json.loads(alerted_path.read_text()) if alerted_path.exists() else {}
        )
    except Exception:  # noqa: BLE001 - corrupt state shouldn't block alerts
        alerted = {}

    # Recovered recordings: drop them so a later failure pings again.
    for rid in report.processed:
        alerted.pop(rid, None)

    # New = never alerted, or the error message changed since last alert.
    new = [(rid, err) for rid, err in report.failed if alerted.get(rid) != err]

    if new:
        n = len(new)
        lines = [f"⚠️ Plaud automation: {n} recording{'' if n == 1 else 's'} failed"]
        for rid, err in new:
            lines.append(f"• {rid}: {err[:180]}")
        label = os.getenv("PLAUD_LAUNCHD_LABEL", _DEFAULT_LABEL)
        lines.append(
            f"\nFix, then re-run:\nlaunchctl kickstart -k gui/$(id -u)/{label}"
        )
        # Only mark as alerted if the send actually went through, so a Telegram
        # outage means we retry next run rather than swallow the alert.
        if send_telegram("\n".join(lines), token=token, chat_id=chat_id):
            for rid, err in new:
                alerted[rid] = err

    # Persist dedup state (also commits the recovered-recording drops above).
    try:
        alerted_path.write_text(json.dumps(alerted))
    except Exception:  # noqa: BLE001 - best-effort
        pass
