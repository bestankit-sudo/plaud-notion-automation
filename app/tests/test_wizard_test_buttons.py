import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_STATE_DIR", str(tmp_path / "state"))
    from app.server import app
    return TestClient(app)


def test_wizard_html_has_test_buttons(client):
    html = client.get("/static/wizard.html").text
    assert html.count('class="test-btn"') >= 3  # provider key, HF, riffado (+ notion)


def test_wizard_js_calls_test_endpoints(client):
    js = client.get("/static/wizard.js").text
    assert "/api/setup/test/" in js
