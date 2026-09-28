"""Single-writer lock over a state dir, so two pipelines never overlap.

The launchd agent fires on a 30-minute ``StartInterval``. Transcribing a
20-minute recording routinely takes longer than that under load, so a manual
``process_one.py`` run would still be inside MLX when the scheduled run started
a second pipeline on the same recording — both then fought over the GPU and
each took roughly twice as long.

The ledger cannot prevent this: ``reconcile`` skips only rows already marked
``processed``, and that row is written at the *end* of the pipeline, so an
in-flight recording still looks untouched.

An advisory ``flock`` is used rather than a status column because the kernel
drops it when the holder exits — including ``kill -9`` and a panic. A status
row would survive a crash and lock the recording out permanently.
"""

from __future__ import annotations

import errno
import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

LOCK_NAME = "pipeline.lock"


class AlreadyRunning(RuntimeError):
    """Another pipeline already holds the run lock for this state dir."""

    def __init__(self, holder: str) -> None:
        super().__init__(f"another pipeline is already running (holder: {holder})")
        self.holder = holder


@contextmanager
def run_lock(state_dir: Path, name: str = LOCK_NAME) -> Iterator[Path]:
    """Hold an exclusive, non-blocking lock on ``state_dir/name``.

    Raises :class:`AlreadyRunning` immediately if another process holds it —
    waiting would just queue up duplicate GPU work behind the current run.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / name
    handle = path.open("a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                raise
            handle.seek(0)
            holder = handle.read().strip() or "unknown"
            raise AlreadyRunning(holder) from exc

        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}")
        handle.flush()
        yield path
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()
