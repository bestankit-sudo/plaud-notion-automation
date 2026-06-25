"""Execution seam for installer steps. `Runner.run(argv, on_line) -> rc` is the
only place a subprocess lives. The orchestrator is tested against FakeRunner, so
no real process runs in tests. RealRunner (Popen) is exercised only on a real Mac."""

from __future__ import annotations

import subprocess
from typing import Callable, Protocol

OnLine = Callable[[str], None]


class Runner(Protocol):
    def run(self, argv: list[str], on_line: OnLine) -> int:
        """Run argv, call on_line(line) for each output line, return the exit code."""
        ...


class FakeRunner:
    """Replays scripted output per argv tuple — for tests. Unknown argv -> (0, [])."""

    def __init__(self, scripts: dict[tuple[str, ...], tuple[int, list[str]]]):
        self._scripts = scripts
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], on_line: OnLine) -> int:
        self.calls.append(list(argv))
        rc, lines = self._scripts.get(tuple(argv), (0, []))
        for line in lines:
            on_line(line)
        return rc


class RealRunner:
    """Real-Mac executor: streams a subprocess's combined output line-by-line.
    Not exercised in unit tests (the only impure surface in the installer)."""

    def run(self, argv: list[str], on_line: OnLine) -> int:  # pragma: no cover
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            on_line(line.rstrip("\n"))
        return proc.wait()
