import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_STATE_DIR", str(tmp_path / "state"))
    from app.server import app
    return TestClient(app)


def test_wizard_html_has_credential_help_links(client):
    html = client.get("/static/wizard.html").text
    assert "huggingface.co/settings/tokens" in html
    assert "pyannote/speaker-diarization-3.1" in html
    assert "notion.so/my-integrations" in html


def test_wizard_js_groups_by_provider_with_key_links(client):
    js = client.get("/static/wizard.js").text
    assert "console.anthropic.com" in js
    assert "platform.openai.com" in js
    assert "Claude (Anthropic)" in js
    assert '"OpenAI"' in js
