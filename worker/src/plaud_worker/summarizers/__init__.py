from __future__ import annotations

from .anthropic import AnthropicSummarizer
from .base import Summarizer
from .openai import OpenAISummarizer

__all__ = ["Summarizer", "OpenAISummarizer", "AnthropicSummarizer", "build_summarizer"]


def build_summarizer(settings) -> Summarizer:
    if settings.summarizer_provider == "anthropic":
        return AnthropicSummarizer(settings.anthropic_api_key, settings.summarizer_model)
    return OpenAISummarizer(settings.openai_api_key, settings.summarizer_model)
