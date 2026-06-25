"""Live connection checks for the setup wizard — validate a credential against
its service with one cheap authenticated GET. Returns {ok, detail}; never echoes
the credential or a raw exception message."""

from __future__ import annotations

import httpx


def probe(method: str, url: str, headers: dict[str, str], *, timeout: float = 8.0) -> dict:
    try:
        resp = httpx.request(method, url, headers=headers, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - map any transport error to a clean message
        return {"ok": False, "detail": f"could not reach service: {type(exc).__name__}"}
    if 200 <= resp.status_code < 300:
        return {"ok": True, "detail": "ok"}
    if resp.status_code in (401, 403):
        return {"ok": False, "detail": "authentication failed (check the key/token)"}
    return {"ok": False, "detail": f"HTTP {resp.status_code}"}


def check_riffado(base_url: str, api_key: str) -> dict:
    return probe("GET", base_url.rstrip("/") + "/api/v1/recordings",
                 {"Authorization": f"Bearer {api_key}"})


def check_notion(token: str) -> dict:
    return probe("GET", "https://api.notion.com/v1/users/me",
                 {"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28"})


def check_openai(key: str) -> dict:
    return probe("GET", "https://api.openai.com/v1/models",
                 {"Authorization": f"Bearer {key}"})


def check_anthropic(key: str) -> dict:
    return probe("GET", "https://api.anthropic.com/v1/models",
                 {"x-api-key": key, "anthropic-version": "2023-06-01"})


def check_hf(token: str) -> dict:
    return probe("GET", "https://huggingface.co/api/whoami-v2",
                 {"Authorization": f"Bearer {token}"})
