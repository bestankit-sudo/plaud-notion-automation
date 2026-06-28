from plaud_worker.appconfig import AppConfig


def test_load_missing_returns_defaults(tmp_path):
    cfg = AppConfig.load(tmp_path)
    assert cfg.destination == "notion"
    assert cfg.summarizer_provider == "openai"
    assert cfg.summarizer_model == "gpt-5.5"
    assert cfg.whisper_model == ""  # "" = worker default (transcribe.DEFAULT_MODEL)
    assert cfg.speaker_naming_enabled is True
    assert cfg.notion_parent_page_id is None


def test_whisper_model_roundtrips(tmp_path):
    AppConfig(whisper_model="mlx-community/whisper-large-v3-turbo").save(tmp_path)
    assert AppConfig.load(tmp_path).whisper_model == "mlx-community/whisper-large-v3-turbo"


def test_save_then_load_roundtrips(tmp_path):
    AppConfig(
        destination="local",
        speaker_naming_enabled=False,
        summarizer_provider="anthropic",
        summarizer_model="claude-opus-4-8",
        notion_parent_page_id="page-123",
    ).save(tmp_path)
    cfg = AppConfig.load(tmp_path)
    assert cfg.destination == "local"
    assert cfg.speaker_naming_enabled is False
    assert cfg.summarizer_provider == "anthropic"
    assert cfg.summarizer_model == "claude-opus-4-8"
    assert cfg.notion_parent_page_id == "page-123"


def test_load_tolerates_unknown_keys(tmp_path):
    (tmp_path / "config.json").write_text('{"destination": "local", "future_key": 1}')
    cfg = AppConfig.load(tmp_path)
    assert cfg.destination == "local"
