"""Read-only client for the Riffado public API (/api/v1).

Only the read surface we depend on: list recordings, fetch one, fetch its
transcript, and the audio URL. Auth is a Bearer `op_...` key with "read" scope.

Also holds the readiness gate the launchd run opens with -- see
``wait_until_ready``.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable, Iterator

import httpx

# How long a run will wait for Riffado before treating it as a real outage.
# The watchdog (net.bhangar.riffado-watchdog) polls every 300s and can spend
# ~150s more relaunching Docker Desktop, so anything under ~450s could give up
# while recovery is still in flight. 600s stays well clear of that and still
# finishes long before the next run 1800s later.
READY_TIMEOUT_S = 600.0
READY_INTERVAL_S = 15.0


def _probe(base_url: str, timeout_s: float) -> bool:
    """True if the host answers at all. Any HTTP status counts -- the app root
    307-redirects and returns 502 while booting; both mean the port is live.
    Same liveness test the watchdog shell script uses."""
    try:
        httpx.get(base_url.rstrip("/") + "/", timeout=timeout_s)
        return True
    except Exception:  # noqa: BLE001 - any transport failure means "not yet"
        return False


def wait_until_ready(
    base_url: str,
    *,
    timeout_s: float = READY_TIMEOUT_S,
    interval_s: float = READY_INTERVAL_S,
    on_event: Callable[[str], None] = lambda msg: None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Block until Riffado answers, or `timeout_s` elapses. Returns readiness.

    Docker Desktop restarts take Riffado down for a few minutes at a time; a run
    that launchd happens to fire inside that hole used to die on the first API
    call and page us, even though the watchdog had the service back before the
    alert was read (2026-08-22: down 11:05-11:09, run fired 11:07). Waiting here
    turns that into a slow run instead of a crash. A genuine outage still fails
    the run once the budget is spent -- silence would be worse than the page.
    """
    if _probe(base_url, min(interval_s, 10.0)):
        return True
    started = monotonic()
    on_event(f"riffado not answering — waiting up to {int(timeout_s)}s for it to come back")
    while monotonic() - started < timeout_s:
        remaining = timeout_s - (monotonic() - started)
        sleep(min(interval_s, remaining))
        if _probe(base_url, min(interval_s, 10.0)):
            waited = int(monotonic() - started)
            on_event(f"riffado answered after {waited}s — continuing")
            return True
    return False


class RiffadoClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def __enter__(self) -> "RiffadoClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def list_recordings(
        self,
        *,
        limit: int = 50,
        created_since: datetime | None = None,
        has_transcription: bool | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield recording objects across all pages (cursor pagination)."""
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            if created_since:
                params["created_since"] = created_since.isoformat()
            if has_transcription is not None:
                params["has_transcription"] = str(has_transcription).lower()
            data = self._get("/api/v1/recordings", params=params)
            # API returns recordings under "data" (cursor pagination).
            for rec in data.get("data", data.get("recordings", [])):
                yield rec
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break

    def get_recording(self, recording_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/recordings/{recording_id}")

    def get_transcript(self, recording_id: str) -> dict[str, Any] | None:
        """Returns {text, detectedLanguage, provider, model} or None if 404."""
        resp = self._client.get(f"/api/v1/recordings/{recording_id}/transcript")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def audio_url(self, recording_id: str) -> str:
        return f"{self._client.base_url}/api/v1/recordings/{recording_id}/audio"

    def download_audio(self, recording_id: str, dest: str) -> str:
        """Stream the recording's audio to `dest` (follows the 302 to storage)."""
        with self._client.stream(
            "GET", f"/api/v1/recordings/{recording_id}/audio", follow_redirects=True
        ) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
        return dest

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()
