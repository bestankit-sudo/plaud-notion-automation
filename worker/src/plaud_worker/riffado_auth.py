"""Headless Riffado sync trigger.

Riffado's sync logic is server-side at POST /api/plaud/sync but session-authed
(the read-only API key can't call it). We sign in via BetterAuth once to get a
session cookie, then POST the sync. Driven from launchd so it runs with no
browser open. All localhost — the credentials never leave the machine.
"""

from __future__ import annotations

import httpx


def make_session(base_url: str, email: str, password: str, timeout: float = 30.0) -> httpx.Client:
    """Sign in and return an httpx.Client carrying the session cookie."""
    client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
    resp = client.post("/api/auth/sign-in/email", json={"email": email, "password": password})
    resp.raise_for_status()
    return client


def trigger_sync(client: httpx.Client) -> dict:
    """POST /api/plaud/sync with the signed-in session; returns sync counts."""
    resp = client.post("/api/plaud/sync")
    resp.raise_for_status()
    return resp.json()
