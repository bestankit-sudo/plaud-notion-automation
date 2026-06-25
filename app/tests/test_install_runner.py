from app.install.runner import FakeRunner


def test_fake_runner_replays_lines_and_rc():
    fr = FakeRunner({("brew", "install", "ffmpeg"): (0, ["==> Installing", "done"])})
    seen = []
    rc = fr.run(["brew", "install", "ffmpeg"], seen.append)
    assert rc == 0
    assert seen == ["==> Installing", "done"]
    assert fr.calls == [["brew", "install", "ffmpeg"]]


def test_fake_runner_unknown_argv_is_noop_success():
    fr = FakeRunner({})
    seen = []
    rc = fr.run(["whatever"], seen.append)
    assert rc == 0 and seen == []


def test_fake_runner_nonzero_rc():
    fr = FakeRunner({("x",): (1, ["boom"])})
    seen = []
    assert fr.run(["x"], seen.append) == 1
    assert seen == ["boom"]
