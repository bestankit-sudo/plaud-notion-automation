from plaud_worker.ledger import Ledger


def test_get_ref_missing_returns_none(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    assert led.get_ref("rec-1", "local") is None
    led.close()


def test_set_then_get_ref(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    led.set_ref("rec-1", "notion", "page-abc")
    led.set_ref("rec-1", "local", "rec-1")
    assert led.get_ref("rec-1", "notion") == "page-abc"
    assert led.get_ref("rec-1", "local") == "rec-1"
    led.close()


def test_set_ref_is_upsert(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    led.set_ref("rec-1", "notion", "page-old")
    led.set_ref("rec-1", "notion", "page-new")
    assert led.get_ref("rec-1", "notion") == "page-new"
    led.close()
