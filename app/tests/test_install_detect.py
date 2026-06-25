from pathlib import Path

from app.install import detect


def fake(mapping):
    """run-callable: maps an argv tuple to (rc, output); default (127, '')."""
    return lambda argv: mapping.get(tuple(argv), (127, ""))


def test_is_py312():
    assert detect.is_py312("Python 3.12.13") is True
    assert detect.is_py312("Python 3.14.6") is False
    assert detect.is_py312("") is False


def test_parse_brew_prefix():
    assert detect.parse_brew_prefix("/opt/homebrew\n") == "/opt/homebrew"
    assert detect.parse_brew_prefix("not a path") is None
    assert detect.parse_brew_prefix("") is None


def test_parse_docker_info_and_ml_imports():
    assert detect.parse_docker_info(0) == "running"
    assert detect.parse_docker_info(1) == "down"
    assert detect.ml_imports_ok(0) is True
    assert detect.ml_imports_ok(1) is False


def test_find_brew_prefers_opt_homebrew():
    run = fake({("/opt/homebrew/bin/brew", "--version"): (0, "Homebrew 4.x")})
    assert detect.find_brew(run) == "/opt/homebrew/bin/brew"


def test_find_brew_falls_back_to_which():
    run = fake({
        ("/opt/homebrew/bin/brew", "--version"): (1, ""),
        ("which", "brew"): (0, "/usr/local/bin/brew\n"),
    })
    assert detect.find_brew(run) == "/usr/local/bin/brew"


def test_find_brew_absent():
    assert detect.find_brew(fake({})) is None


def test_find_python312_at_brew_path():
    run = fake({("/opt/homebrew/opt/python@3.12/bin/python3.12", "--version"): (0, "Python 3.12.13")})
    assert detect.find_python312(run) == "/opt/homebrew/opt/python@3.12/bin/python3.12"


def test_find_python312_rejects_314():
    # every candidate reports 3.14 -> must be None (never fall back to python3)
    run = fake({
        ("/opt/homebrew/opt/python@3.12/bin/python3.12", "--version"): (1, ""),
        ("python3.12", "--version"): (0, "Python 3.14.6"),
    })
    assert detect.find_python312(run) is None


def test_find_python312_via_path_resolves_absolute():
    run = fake({
        ("/opt/homebrew/opt/python@3.12/bin/python3.12", "--version"): (1, ""),
        ("python3.12", "--version"): (0, "Python 3.12.9"),
        ("which", "python3.12"): (0, "/usr/local/bin/python3.12\n"),
    })
    assert detect.find_python312(run) == "/usr/local/bin/python3.12"


def test_ml_installed(tmp_path):
    repo = tmp_path
    py = detect.ml_python(repo)
    assert detect.ml_installed(fake({}), repo) is False  # binary absent
    py.parent.mkdir(parents=True)
    py.write_text("")  # binary present
    run = fake({(str(py), "-c", "import mlx_whisper, torch, pyannote.audio"): (0, "")})
    assert detect.ml_installed(run, repo) is True
    assert detect.ml_installed(fake({}), repo) is False  # import fails -> not installed


def test_docker_running():
    assert detect.docker_running(fake({("docker", "info"): (0, "...")})) is True
    assert detect.docker_running(fake({})) is False


def test_ml_python_path():
    assert detect.ml_python(Path("/r")) == Path("/r/worker/.venv-ml/bin/python")
