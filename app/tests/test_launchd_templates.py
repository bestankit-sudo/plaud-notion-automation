import plistlib
from pathlib import Path

from app.install import launchd


def test_worker_plist_points_at_venv_ml_and_has_brew_path():
    xml = launchd.render_worker_plist(Path("/r"), Path("/r/worker/.venv-ml/bin/python"), "/opt/homebrew")
    d = plistlib.loads(xml.encode())  # valid XML
    assert d["Label"] == "com.plaudautomation"
    assert d["ProgramArguments"][0] == "/r/worker/.venv-ml/bin/python"
    assert d["ProgramArguments"][1] == "scripts/sync_and_reconcile.py"
    assert d["WorkingDirectory"] == "/r/worker"
    assert d["EnvironmentVariables"]["PYTHONPATH"] == "src"
    assert "/opt/homebrew/bin" in d["EnvironmentVariables"]["PATH"]
    assert d["StartInterval"] == 1800
    assert d["RunAtLoad"] is True
    assert d["StandardOutPath"].endswith("worker/state/automation.log")
    assert d["ProcessType"] == "Background"


def test_web_plist_keepalive_dict_and_uvicorn():
    xml = launchd.render_web_plist(Path("/r"), Path("/r/worker/.venv/bin/python"), "/opt/homebrew", port=8787)
    d = plistlib.loads(xml.encode())
    assert d["Label"] == "com.plaudautomation.web"
    assert d["ProgramArguments"] == [
        "/r/worker/.venv/bin/python", "-m", "uvicorn", "server:app",
        "--host", "127.0.0.1", "--port", "8787",
    ]
    assert d["WorkingDirectory"] == "/r/app"
    assert d["EnvironmentVariables"]["PYTHONPATH"] == "/r:/r/worker/src"
    assert d["KeepAlive"] == {"SuccessfulExit": False, "Crashed": True}  # dict, not bare True
    assert d["ThrottleInterval"] == 10
    assert d["StandardOutPath"].endswith("worker/state/web.log")
    assert d["ProcessType"] == "Interactive"


def test_web_plist_respects_port():
    xml = launchd.render_web_plist(Path("/r"), Path("/p/python"), "/opt/homebrew", port=9001)
    d = plistlib.loads(xml.encode())
    assert "9001" in d["ProgramArguments"]


def test_install_argv_bootout_then_bootstrap():
    argv = launchd.install_argv("com.plaudautomation.web", Path("/u/Library/LaunchAgents/x.plist"), 501)
    assert argv == [
        ["launchctl", "bootout", "gui/501/com.plaudautomation.web"],
        ["launchctl", "bootstrap", "gui/501", "/u/Library/LaunchAgents/x.plist"],
    ]


def test_committed_web_template_is_valid_plist():
    p = Path(__file__).resolve().parents[2] / "deploy" / "launchd" / "com.plaudautomation.web.plist"
    d = plistlib.loads(p.read_bytes())  # parses as a plist
    assert d["Label"] == "com.plaudautomation.web"
    assert d["KeepAlive"] == {"SuccessfulExit": False, "Crashed": True}
