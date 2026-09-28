"""The run lock is what stops a launchd tick from starting a second pipeline
on top of a manual run that is still inside MLX."""

import os
import subprocess
import sys
import textwrap

import pytest

from plaud_worker.runlock import AlreadyRunning, run_lock


def test_lock_is_acquired_and_released(tmp_path):
    with run_lock(tmp_path) as path:
        assert path.exists()
    # released — a second acquisition in the same process must succeed
    with run_lock(tmp_path):
        pass


def test_creates_the_state_dir_if_missing(tmp_path):
    state = tmp_path / "state"
    with run_lock(state) as path:
        assert path.parent == state


def test_lock_records_the_holder_pid(tmp_path):
    with run_lock(tmp_path) as path:
        assert path.read_text().strip() == f"pid={os.getpid()}"


def _holder_script(state_dir, ready, release):
    return textwrap.dedent(f"""
        import sys, pathlib, time
        sys.path.insert(0, {str(_SRC)!r})
        from plaud_worker.runlock import run_lock
        with run_lock(pathlib.Path({str(state_dir)!r})):
            pathlib.Path({str(ready)!r}).write_text("up")
            while not pathlib.Path({str(release)!r}).exists():
                time.sleep(0.02)
    """)


_SRC = __import__("pathlib").Path(__file__).resolve().parents[1] / "src"


def test_second_process_is_refused_while_the_first_holds_it(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    ready, release = tmp_path / "ready", tmp_path / "release"

    holder = subprocess.Popen(
        [sys.executable, "-c", _holder_script(state, ready, release)]
    )
    try:
        for _ in range(500):  # wait for the holder to actually take the lock
            if ready.exists():
                break
            __import__("time").sleep(0.02)
        assert ready.exists(), "holder never acquired the lock"

        with pytest.raises(AlreadyRunning):
            with run_lock(state):
                pass
    finally:
        release.write_text("go")
        holder.wait(timeout=10)

    # once the holder exits the lock is free again
    with run_lock(state):
        pass


def test_lock_survives_a_killed_holder(tmp_path):
    """kill -9 must not leave the recording locked out forever — the whole
    reason this is an flock and not a 'pending' row in the ledger."""
    state = tmp_path / "state"
    state.mkdir()
    ready, release = tmp_path / "ready", tmp_path / "release"

    holder = subprocess.Popen(
        [sys.executable, "-c", _holder_script(state, ready, release)]
    )
    for _ in range(500):
        if ready.exists():
            break
        __import__("time").sleep(0.02)
    assert ready.exists()

    holder.kill()
    holder.wait(timeout=10)

    with run_lock(state):  # kernel dropped the flock on process death
        pass


def test_alreadyrunning_names_the_holder(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    ready, release = tmp_path / "ready", tmp_path / "release"

    holder = subprocess.Popen(
        [sys.executable, "-c", _holder_script(state, ready, release)]
    )
    try:
        for _ in range(500):
            if ready.exists():
                break
            __import__("time").sleep(0.02)
        with pytest.raises(AlreadyRunning) as exc:
            with run_lock(state):
                pass
        assert str(holder.pid) in exc.value.holder
    finally:
        release.write_text("go")
        holder.wait(timeout=10)
