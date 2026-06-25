import stat

from app import envfile, paths


def test_worker_env_honors_override(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_ENV_FILE", str(tmp_path / "x.env"))
    assert paths.worker_env() == tmp_path / "x.env"


def test_worker_env_default(monkeypatch):
    monkeypatch.delenv("WORKER_ENV_FILE", raising=False)
    p = paths.worker_env()
    assert p.name == ".env"
    assert p.parent.name == "worker"


def test_upsert_creates_file_0600(tmp_path):
    f = tmp_path / ".env"
    envfile.upsert(f, {"OPENAI_API_KEY": "sk-1"})
    assert "OPENAI_API_KEY=sk-1" in f.read_text()
    assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_upsert_updates_in_place_and_preserves_other_lines(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# comment\nNOTION_TOKEN=old\nRIFFADO_API_KEY=op_x\n")
    envfile.upsert(f, {"NOTION_TOKEN": "new"})
    text = f.read_text()
    assert "# comment" in text
    assert "RIFFADO_API_KEY=op_x" in text
    assert "NOTION_TOKEN=new" in text
    assert "NOTION_TOKEN=old" not in text
    # no duplicate NOTION_TOKEN lines
    assert text.count("NOTION_TOKEN=") == 1


def test_upsert_appends_new_keys(tmp_path):
    f = tmp_path / ".env"
    f.write_text("A=1\n")
    envfile.upsert(f, {"B": "2"})
    text = f.read_text()
    assert "A=1" in text and "B=2" in text


def test_upsert_no_prefix_collision(tmp_path):
    f = tmp_path / ".env"
    f.write_text("OPENAI_API_KEY_PERSONAL=keep\n")
    envfile.upsert(f, {"OPENAI_API_KEY": "new"})
    text = f.read_text()
    assert "OPENAI_API_KEY_PERSONAL=keep" in text
    assert "OPENAI_API_KEY=new" in text
    assert text.count("OPENAI_API_KEY_PERSONAL=") == 1
