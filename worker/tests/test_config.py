import pytest

import plaud_worker.config as config_mod
from plaud_worker.appconfig import AppConfig
from plaud_worker.config import Settings


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """Neutralize dotenv loading and clear secret env vars so Settings.load()
    sees only what each test sets."""
    monkeypatch.setattr(config_mod, "SHARED_SECRETS", tmp_path / "nope-secrets.env")
    monkeypatch.setattr(config_mod, "WORKER_ENV", tmp_path / "nope.env")
    for var in [
        "NOTION_TOKEN", "NOTION_TEST_PARENT_PAGE_ID", "OTHER_MEETING_CENTRAL_PAGE_ID",
        "OPENAI_API_KEY_PERSONAL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    ]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("WORKER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("RIFFADO_BASE_URL", "http://127.0.0.1:3000")
    monkeypatch.setenv("RIFFADO_API_KEY", "op_test")
    return tmp_path


def _write_appconfig(tmp_path, **kw):
    AppConfig(**kw).save(tmp_path / "state")


def test_local_destination_needs_no_notion_creds(isolated_env, monkeypatch):
    _write_appconfig(isolated_env, destination="local",
                     summarizer_provider="openai", summarizer_model="gpt-5.5")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    s = Settings.load()
    assert s.destination == "local"
    assert s.notion_token is None
    assert s.summarizer_provider == "openai"
    assert s.openai_api_key == "sk-test"


def test_anthropic_provider_requires_anthropic_key(isolated_env):
    _write_appconfig(isolated_env, destination="local",
                     summarizer_provider="anthropic", summarizer_model="claude-opus-4-8")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        Settings.load()


def test_notion_destination_requires_token(isolated_env, monkeypatch):
    _write_appconfig(isolated_env, destination="notion",
                     summarizer_provider="openai", summarizer_model="gpt-5.5")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with pytest.raises(RuntimeError, match="NOTION_TOKEN"):
        Settings.load()


def test_notion_happy_path(isolated_env, monkeypatch):
    _write_appconfig(isolated_env, destination="notion",
                     summarizer_provider="anthropic", summarizer_model="claude-opus-4-8")
    monkeypatch.setenv("NOTION_TOKEN", "secret_tok")
    monkeypatch.setenv("OTHER_MEETING_CENTRAL_PAGE_ID", "page-xyz")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-test")
    s = Settings.load()
    assert s.notion_token == "secret_tok"
    assert s.notion_parent_page_id == "page-xyz"
    assert s.anthropic_api_key == "ak-test"
    assert s.summarizer_model == "claude-opus-4-8"
