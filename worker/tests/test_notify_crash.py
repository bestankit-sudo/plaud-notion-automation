import json

from plaud_worker import notify
from plaud_worker.notify import clear_crash, notify_crash


def _sent(monkeypatch, ok=True):
    calls = []
    def fake(text, *, token, chat_id, timeout=10.0):
        calls.append(text)
        return ok
    monkeypatch.setattr(notify, "send_telegram", fake)
    return calls


def test_first_crash_alerts_and_records(tmp_path, monkeypatch):
    calls = _sent(monkeypatch)
    notify_crash("ConnectError: refused", state_dir=tmp_path, token="t", chat_id="c")
    assert len(calls) == 1 and "CRASHED" in calls[0]
    state = json.loads((tmp_path / "telegram_alerted.json").read_text())
    assert state["_run_crash"] == "ConnectError: refused"


def test_same_crash_deduped_different_realerts(tmp_path, monkeypatch):
    calls = _sent(monkeypatch)
    notify_crash("ConnectError: refused", state_dir=tmp_path, token="t", chat_id="c")
    notify_crash("ConnectError: refused", state_dir=tmp_path, token="t", chat_id="c")
    assert len(calls) == 1
    notify_crash("TimeoutError: slow", state_dir=tmp_path, token="t", chat_id="c")
    assert len(calls) == 2


def test_clear_crash_allows_realert(tmp_path, monkeypatch):
    calls = _sent(monkeypatch)
    notify_crash("ConnectError: refused", state_dir=tmp_path, token="t", chat_id="c")
    clear_crash(state_dir=tmp_path)
    notify_crash("ConnectError: refused", state_dir=tmp_path, token="t", chat_id="c")
    assert len(calls) == 2


def test_failed_send_not_recorded(tmp_path, monkeypatch):
    _sent(monkeypatch, ok=False)
    notify_crash("ConnectError: refused", state_dir=tmp_path, token="t", chat_id="c")
    state_file = tmp_path / "telegram_alerted.json"
    assert not state_file.exists() or "_run_crash" not in json.loads(state_file.read_text())
