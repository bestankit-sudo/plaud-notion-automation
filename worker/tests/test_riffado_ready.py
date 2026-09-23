"""Readiness gate: a run that starts while Riffado is booting must wait, not crash.

Regression for 2026-08-22 11:07 — Docker Desktop restarted, Riffado was down
11:05-11:09, launchd fired the worker at 11:07, and reconcile()'s first call
raised ConnectError one second in. The watchdog had it back by 11:09; the run
just started inside the hole.
"""

from __future__ import annotations

import httpx
import pytest

from plaud_worker import riffado
from plaud_worker.riffado import wait_until_ready


class _Clock:
    """Fake monotonic clock advanced only by the injected sleep."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def _probes(monkeypatch, results):
    """Make _probe return each of `results` in turn; record the call count."""
    calls = []

    def fake(base_url, timeout_s):
        calls.append(base_url)
        return results[min(len(calls) - 1, len(results) - 1)]

    monkeypatch.setattr(riffado, "_probe", fake)
    return calls


def test_ready_on_first_probe_does_not_sleep(monkeypatch):
    calls = _probes(monkeypatch, [True])
    clock = _Clock()
    assert wait_until_ready("http://x:3000", monotonic=clock, sleep=clock.sleep) is True
    assert len(calls) == 1
    assert clock.t == 0.0  # never slept


def test_waits_then_succeeds_when_service_comes_up(monkeypatch):
    calls = _probes(monkeypatch, [False, False, True])
    clock = _Clock()
    ok = wait_until_ready(
        "http://x:3000", timeout_s=600, interval_s=15,
        monotonic=clock, sleep=clock.sleep,
    )
    assert ok is True
    assert len(calls) == 3
    assert clock.t == 30.0  # slept twice


def test_gives_up_after_budget_and_terminates(monkeypatch):
    calls = _probes(monkeypatch, [False])
    clock = _Clock()
    ok = wait_until_ready(
        "http://x:3000", timeout_s=60, interval_s=15,
        monotonic=clock, sleep=clock.sleep,
    )
    assert ok is False
    assert clock.t <= 60.0        # never overruns the budget
    assert 2 <= len(calls) <= 6   # polled, but did not spin


def test_budget_covers_a_full_watchdog_cycle_by_default(monkeypatch):
    """The watchdog polls every 300s and can take ~150s to recover Docker.
    The default budget must outlast one full cycle or the gate is pointless."""
    calls = _probes(monkeypatch, [False])
    clock = _Clock()
    wait_until_ready("http://x:3000", monotonic=clock, sleep=clock.sleep)
    assert clock.t >= 450.0


@pytest.mark.parametrize("status", [200, 307, 500, 502])
def test_any_http_response_counts_as_up(monkeypatch, status):
    """Riffado's root 307-redirects and a booting app can 502 — same as the
    watchdog, any answer at all means the port is live."""
    monkeypatch.setattr(
        httpx, "get",
        lambda *a, **k: httpx.Response(status, request=httpx.Request("GET", "http://x:3000/")),
    )
    assert riffado._probe("http://x:3000", 5.0) is True


@pytest.mark.parametrize("exc", [
    httpx.ConnectError("[Errno 61] Connection refused"),
    httpx.ConnectTimeout("timed out"),
    httpx.ReadTimeout("timed out"),
])
def test_transport_failures_count_as_down(monkeypatch, exc):
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(httpx, "get", boom)
    assert riffado._probe("http://x:3000", 5.0) is False
