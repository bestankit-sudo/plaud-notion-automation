from pathlib import Path

from app.install import status as S


def fake(mapping):
    return lambda argv: mapping.get(tuple(argv), (127, ""))


def test_resolve_env_from_probes():
    run = fake({
        ("/opt/homebrew/bin/brew", "--version"): (0, "Homebrew 4"),
        ("/opt/homebrew/bin/brew", "--prefix"): (0, "/opt/homebrew\n"),
        ("/opt/homebrew/opt/python@3.12/bin/python3.12", "--version"): (0, "Python 3.12.9"),
    })
    env = S.resolve_env(run, Path("/r"))
    assert env.brew == "/opt/homebrew/bin/brew"
    assert env.brew_prefix == "/opt/homebrew"
    assert env.py312 == "/opt/homebrew/opt/python@3.12/bin/python3.12"
    assert env.repo_root == Path("/r")


def test_step_done_brew_ffmpeg_docker():
    run = fake({
        ("/opt/homebrew/bin/brew", "--version"): (0, "Homebrew 4"),
        ("ffmpeg", "-version"): (0, "ffmpeg version 7"),
        ("docker", "info"): (1, "Cannot connect"),
    })
    assert S.step_done("brew", run, Path("/r"))[0] is True
    assert S.step_done("ffmpeg", run, Path("/r"))[0] is True
    assert S.step_done("docker", run, Path("/r"))[0] is False  # daemon down


def test_step_done_ml_absent():
    done, detail = S.step_done("ml", fake({}), Path("/r"))
    assert done is False  # no .venv-ml binary


def test_step_done_human_steps_are_false():
    assert S.step_done("riffado", fake({}), Path("/r"))[0] is False
    assert S.step_done("plaud_otp", fake({}), Path("/r"))[0] is False


def test_step_status_covers_all_steps():
    rows = S.step_status(fake({}), Path("/r"))
    assert [r["id"] for r in rows] == [
        "brew", "ffmpeg", "py312", "ml", "docker", "riffado", "plaud_otp", "launchd"
    ]
    for r in rows:
        assert set(r) == {"id", "title", "kind", "guide_url", "done", "detail"}
        assert isinstance(r["done"], bool)
    brew = next(r for r in rows if r["id"] == "brew")
    assert brew["guide_url"]  # guide steps carry their help URL
