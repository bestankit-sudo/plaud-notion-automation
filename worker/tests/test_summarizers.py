import json

import plaud_worker.summarizers.anthropic as anth_mod
import plaud_worker.summarizers.openai as oai_mod
from plaud_worker.models import ActionItem, Section
from plaud_worker.summarizers.anthropic import AnthropicSummarizer
from plaud_worker.summarizers.openai import OpenAISummarizer

_NOTES = {
    "title": "Patent Strategy",
    "overview": ["Filed the provisional"],
    "sections": [{"heading": "Next steps", "bullets": ["draft claims"]}],
    "action_items": [{"owner": "Sam", "task": "Send the spec", "description": "by Fri"}],
}


def test_openai_summarizer_delegates_to_structure(monkeypatch):
    captured = {}

    def fake_structure(transcript_text, *, title, api_key, model, participants=None):
        captured.update(api_key=api_key, model=model, participants=participants)
        return ("Patent Strategy", ["ov"], [Section("H", ["b"])], [ActionItem("Sam", "t", "d")])

    monkeypatch.setattr(oai_mod, "structure", fake_structure)
    title, overview, sections, actions = OpenAISummarizer("sk-xyz", "gpt-5.5").summarize(
        "Sam: hi", title="Untitled", participants=["Sam"]
    )
    assert captured == {"api_key": "sk-xyz", "model": "gpt-5.5", "participants": ["Sam"]}
    assert title == "Patent Strategy"
    assert sections[0].heading == "H"


def test_anthropic_summarizer_parses_structured_json(monkeypatch):
    class _Block:
        type = "text"
        text = json.dumps(_NOTES)

    class _Resp:
        content = [_Block()]

    class _Messages:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return _Resp()

    class _Client:
        def __init__(self, api_key):
            self.messages = _Messages()

    fake_anthropic = type("M", (), {"Anthropic": _Client})
    monkeypatch.setattr(anth_mod, "_import_anthropic", lambda: fake_anthropic)

    s = AnthropicSummarizer("ak-1", "claude-opus-4-8")
    title, overview, sections, actions = s.summarize(
        "Sam: hi", title="Untitled", participants=["Sam"]
    )
    assert title == "Patent Strategy"
    assert overview == ["Filed the provisional"]
    assert sections[0].bullets == ["draft claims"]
    assert actions[0].owner == "Sam"
    # model + structured-output format were passed through
    assert s._client.messages.kwargs["model"] == "claude-opus-4-8"
    assert s._client.messages.kwargs["output_config"]["format"]["type"] == "json_schema"
