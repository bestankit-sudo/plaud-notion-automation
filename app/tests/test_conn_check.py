import app.conn_check as cc


class _FakeResp:
    def __init__(self, status_code):
        self.status_code = status_code


class _FakeHttpx:
    """Records the last request and returns a configurable status/exception."""
    def __init__(self):
        self.last = None
        self.status = 200
        self.raise_exc = None

    def request(self, method, url, headers=None, timeout=None):
        self.last = {"method": method, "url": url, "headers": headers or {}, "timeout": timeout}
        if self.raise_exc:
            raise self.raise_exc
        return _FakeResp(self.status)


def _patch(monkeypatch):
    fake = _FakeHttpx()
    monkeypatch.setattr(cc, "httpx", fake)
    return fake


def test_probe_2xx_ok(monkeypatch):
    fake = _patch(monkeypatch); fake.status = 200
    assert cc.probe("GET", "https://x", {})["ok"] is True


def test_probe_401_auth_failed(monkeypatch):
    fake = _patch(monkeypatch); fake.status = 401
    r = cc.probe("GET", "https://x", {})
    assert r["ok"] is False and "auth" in r["detail"].lower()


def test_probe_other_status(monkeypatch):
    fake = _patch(monkeypatch); fake.status = 500
    r = cc.probe("GET", "https://x", {})
    assert r["ok"] is False and "500" in r["detail"]


def test_probe_network_error(monkeypatch):
    fake = _patch(monkeypatch); fake.raise_exc = ConnectionError("boom")
    r = cc.probe("GET", "https://x", {})
    assert r["ok"] is False and "reach" in r["detail"].lower()
    assert "boom" not in r["detail"]  # no exception message / secret leakage


def test_check_riffado_builds_request(monkeypatch):
    fake = _patch(monkeypatch); fake.status = 200
    assert cc.check_riffado("http://127.0.0.1:3000/", "op_k")["ok"] is True
    assert fake.last["url"] == "http://127.0.0.1:3000/api/v1/recordings"
    assert fake.last["headers"]["Authorization"] == "Bearer op_k"


def test_check_anthropic_uses_x_api_key(monkeypatch):
    fake = _patch(monkeypatch); fake.status = 200
    cc.check_anthropic("ak-1")
    assert fake.last["url"] == "https://api.anthropic.com/v1/models"
    assert fake.last["headers"]["x-api-key"] == "ak-1"
    assert fake.last["headers"]["anthropic-version"] == "2023-06-01"


def test_check_notion_and_openai_and_hf_targets(monkeypatch):
    fake = _patch(monkeypatch); fake.status = 200
    cc.check_notion("nt"); assert fake.last["url"] == "https://api.notion.com/v1/users/me"
    assert fake.last["headers"]["Notion-Version"] == "2022-06-28"
    cc.check_openai("sk"); assert fake.last["url"] == "https://api.openai.com/v1/models"
    cc.check_hf("hf"); assert fake.last["url"] == "https://huggingface.co/api/whoami-v2"
