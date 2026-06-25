from pathlib import Path

import pytest

from app.install import commands as cmd
from app.install.plan import Env, PrerequisiteMissing, ml_venv_python, plan_for


def test_argv_builders():
    assert cmd.brew_install("/b/brew", "ffmpeg") == ["/b/brew", "install", "ffmpeg"]
    assert cmd.make_ml_venv("py312", Path("/r")) == ["py312", "-m", "venv", "/r/worker/.venv-ml"]
    vp = ml_venv_python(Path("/r"))
    assert cmd.pip_upgrade(vp) == [str(vp), "-m", "pip", "install", "--upgrade", "pip"]
    assert cmd.pip_install_ml(vp, Path("/r")) == [
        str(vp), "-m", "pip", "install", "-r", "/r/worker/requirements-ml.txt"
    ]
    assert cmd.compose_up(Path("/c/docker-compose.yml")) == [
        "docker", "compose", "-f", "/c/docker-compose.yml", "up", "-d", "--wait"
    ]


def _env(**kw):
    base = dict(repo_root=Path("/r"), brew="/b/brew", py312="/p/python3.12", brew_prefix="/opt/homebrew")
    base.update(kw)
    return Env(**base)


def test_plan_ffmpeg_and_py312():
    assert plan_for("ffmpeg", _env()) == [["/b/brew", "install", "ffmpeg"]]
    assert plan_for("py312", _env()) == [["/b/brew", "install", "python@3.12"]]


def test_plan_ml_with_py312_present():
    cmds = plan_for("ml", _env(py312="/p/python3.12"))
    # venv create -> pip upgrade -> pip install ml  (no brew prepend)
    assert cmds[0] == ["/p/python3.12", "-m", "venv", "/r/worker/.venv-ml"]
    assert cmds[-1][-1] == "/r/worker/requirements-ml.txt"
    assert len(cmds) == 3


def test_plan_ml_prepends_py312_when_absent():
    cmds = plan_for("ml", _env(py312=None))
    assert cmds[0] == ["/b/brew", "install", "python@3.12"]  # prerequisite first
    assert cmds[1] == ["/opt/homebrew/opt/python@3.12/bin/python3.12", "-m", "venv", "/r/worker/.venv-ml"]
    assert len(cmds) == 4


def test_plan_ml_without_brew_or_py312_raises():
    with pytest.raises(PrerequisiteMissing):
        plan_for("ml", _env(py312=None, brew=None))


def test_plan_riffado():
    assert plan_for("riffado", _env()) == [
        ["docker", "compose", "-f", "/r/deploy/riffado/docker-compose.yml", "up", "-d", "--wait"]
    ]


def test_plan_unknown_step_raises():
    with pytest.raises(ValueError):
        plan_for("nope", _env())
