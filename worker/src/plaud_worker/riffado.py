"""Read-only client for the Riffado public API (/api/v1).

Only the read surface we depend on: list recordings, fetch one, fetch its
transcript, and the audio URL. Auth is a Bearer `op_...` key with "read" scope.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterator

import httpx


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
