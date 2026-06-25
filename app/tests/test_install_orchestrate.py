import json
from pathlib import Path

from app.install.orchestrate import run_step, sse_format
from app.install.plan import Env
from app.install.runner import FakeRunner


def _frames(captured):
    """Parse captured SSE frame strings into (event, data) tuples."""
    out = []
    for f in captured:
        lines = f.strip().split("\n")
        ev = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        out.append((ev, data))
    return out


def _env(**kw):
    base = dict(repo_root=Path("/r"), brew="/b/brew", py312="/p/python3.12", brew_prefix="/opt/homebrew")
    base.update(kw)
    return Env(**base)


def test_sse_format():
    assert sse_format("log", {"a": 1}) == 'event: log\ndata: {"a": 1}\n\n'


def test_already_done_skips_without_running():
    cap = []
    fr = FakeRunner({})
    ok = run_step("ffmpeg", _env(), fr, already_done=True, emit=cap.append)
    assert ok is True
    evs = [e for e, _ in _frames(cap)]
    assert evs == ["skip", "done"]
    assert _frames(cap)[1][1]["skipped"] is True
    assert fr.calls == []  # nothing ran


def test_success_streams_logs_then_done():
    cap = []
    fr = FakeRunner({("/b/brew", "install", "ffmpeg"): (0, ["==> Installing ffmpeg", "ok"])})
    ok = run_step("ffmpeg", _env(), fr, already_done=False, emit=cap.append)
    assert ok is True
    frames = _frames(cap)
    assert frames[0] == ("log", {"step": "ffmpeg", "line": "$ /b/brew install ffmpeg"})
    assert ("log", {"step": "ffmpeg", "line": "==> Installing ffmpeg"}) in frames
    assert frames[-1][0] == "done" and frames[-1][1]["skipped"] is False


def test_nonzero_exit_emits_error_with_exact_cmd_and_stops():
    cap = []
    # ml plan: venv create fails -> error, pip steps must NOT run
    fr = FakeRunner({tuple(["/p/python3.12", "-m", "venv", "/r/worker/.venv-ml"]): (1, ["boom"])})
    ok = run_step("ml", _env(py312="/p/python3.12"), fr, already_done=False, emit=cap.append)
    assert ok is False
    err = [d for e, d in _frames(cap) if e == "error"][0]
    assert err["cmd"] == "/p/python3.12 -m venv /r/worker/.venv-ml"
    assert err["code"] == 1
    assert "env" not in err and "PATH" not in err  # no env/secret leak
    # only the failing command ran; pip install never started
    assert fr.calls == [["/p/python3.12", "-m", "venv", "/r/worker/.venv-ml"]]


def test_prerequisite_missing_emits_error():
    cap = []
    fr = FakeRunner({})
    ok = run_step("ml", _env(py312=None, brew=None), fr, already_done=False, emit=cap.append)
    assert ok is False
    err = [d for e, d in _frames(cap) if e == "error"][0]
    assert "prerequisite" in err["detail"].lower()
    assert fr.calls == []


def test_mid_sequence_failure_stops_at_right_index():
    cap = []
    venv = ["/p/python3.12", "-m", "venv", "/r/worker/.venv-ml"]
    upgrade = ["/r/worker/.venv-ml/bin/python", "-m", "pip", "install", "--upgrade", "pip"]
    # the ml plan is [venv-create, pip-upgrade, pip-install]; fail the 2nd command
    fr = FakeRunner({
        tuple(venv): (0, ["created venv"]),
        tuple(upgrade): (1, ["boom"]),
    })
    ok = run_step("ml", _env(py312="/p/python3.12"), fr, already_done=False, emit=cap.append)
    assert ok is False
    # commands 1 and 2 ran; pip-install (3) did NOT
    assert fr.calls == [venv, upgrade]
    frames = _frames(cap)
    log_lines = [d["line"] for e, d in frames if e == "log"]
    assert "boom" in log_lines  # failing command's output streamed before the error
    err = [d for e, d in frames if e == "error"][0]
    assert err["cmd"] == "/r/worker/.venv-ml/bin/python -m pip install --upgrade pip"
    assert err["code"] == 1
