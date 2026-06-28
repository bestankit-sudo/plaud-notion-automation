"""Provider/model catalog + per-100-meetings cost estimate shown in the setup wizard.

The paid model ONLY writes the structured summary (title / overview / sections /
action-items). Transcription is done locally and FREE by MLX Whisper, so this
estimate is summary-only. Input ≈ the meeting transcript, output ≈ the summary;
both scale with transcript length (meeting duration). Two profiles bracket the
typical range — LOW ≈ a short (~20-min) English meeting; HIGH ≈ a long (~70-min),
dense, or non-English meeting (non-Latin scripts tokenize to noticeably more).
Speaker count barely changes it. Prices are $/1M tokens. Anthropic models are
restricted to those with structured-output support (see the worker
AnthropicSummarizer): opus-4-8 / sonnet-4-6 / haiku-4-5.
"""

from __future__ import annotations

PROFILE_LOW = {"input_tokens": 5000, "output_tokens": 1000}    # ~20-min English meeting
PROFILE_HIGH = {"input_tokens": 18000, "output_tokens": 2500}  # ~70-min / dense / non-English

CATALOG: list[dict] = [
    {"provider": "anthropic", "model": "claude-opus-4-8", "label": "Claude Opus 4.8",
     "in_per_1m": 5.0, "out_per_1m": 25.0, "tier": "top quality", "recommended": True, "default": True},
    {"provider": "anthropic", "model": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6",
     "in_per_1m": 3.0, "out_per_1m": 15.0, "tier": "best value", "recommended": True},
    {"provider": "anthropic", "model": "claude-haiku-4-5", "label": "Claude Haiku 4.5",
     "in_per_1m": 1.0, "out_per_1m": 5.0, "tier": "budget"},
    {"provider": "openai", "model": "gpt-5.5", "label": "GPT-5.5",
     "in_per_1m": 5.0, "out_per_1m": 30.0, "tier": "flagship"},
    {"provider": "openai", "model": "gpt-5.5-pro", "label": "GPT-5.5 Pro",
     "in_per_1m": 30.0, "out_per_1m": 180.0, "tier": "premium"},
    {"provider": "openai", "model": "gpt-5.4", "label": "GPT-5.4",
     "in_per_1m": 2.5, "out_per_1m": 15.0, "tier": "balanced"},
    {"provider": "openai", "model": "gpt-5.4-mini", "label": "GPT-5.4 mini",
     "in_per_1m": 0.75, "out_per_1m": 4.5, "tier": "budget"},
    {"provider": "openai", "model": "gpt-5.4-nano", "label": "GPT-5.4 nano",
     "in_per_1m": 0.20, "out_per_1m": 1.25, "tier": "ultra-budget (lowest quality)"},
    {"provider": "openai", "model": "gpt-5", "label": "GPT-5",
     "in_per_1m": 1.25, "out_per_1m": 10.0, "tier": "balanced"},
    {"provider": "openai", "model": "gpt-5-mini", "label": "GPT-5 mini",
     "in_per_1m": 0.25, "out_per_1m": 2.0, "tier": "budget"},
    {"provider": "openai", "model": "gpt-5-nano", "label": "GPT-5 nano",
     "in_per_1m": 0.05, "out_per_1m": 0.40, "tier": "ultra-budget (lowest quality)"},
]


# Local transcription models (MLX Whisper). Both run free on the Mac — audio
# never leaves the device — so the trade-off is speed vs. accuracy, not cost.
# `value` is the HuggingFace MLX repo id passed straight to mlx_whisper; it must
# match what the worker downloads. Keep `default` in sync with the worker's
# transcribe.DEFAULT_MODEL.
WHISPER_CATALOG: list[dict] = [
    {"value": "mlx-community/whisper-large-v3-mlx", "label": "Whisper large-v3",
     "tier": "most accurate", "default": True,
     "note": "Best accuracy, especially for non-English speech. Slower; ~3 GB first download."},
    {"value": "mlx-community/whisper-large-v3-turbo", "label": "Whisper large-v3 turbo",
     "tier": "fastest",
     "note": "~4–8× faster on Apple Silicon; ~1.5 GB first download. Slightly lower accuracy."},
]


def whisper_models() -> list[dict]:
    return WHISPER_CATALOG


def _per_100(in_per_1m: float, out_per_1m: float, profile: dict) -> float:
    per_meeting = (
        in_per_1m * profile["input_tokens"] / 1_000_000
        + out_per_1m * profile["output_tokens"] / 1_000_000
    )
    return round(per_meeting * 100, 2)


def cost_for(in_per_1m: float, out_per_1m: float) -> dict:
    """Estimated $ for 100 meetings' summaries (transcription is free/local).
    Returns a low–high range across the LOW and HIGH meeting profiles."""
    return {
        "per_100_low": _per_100(in_per_1m, out_per_1m, PROFILE_LOW),
        "per_100_high": _per_100(in_per_1m, out_per_1m, PROFILE_HIGH),
    }


def catalog_with_costs() -> dict:
    models = [
        {**m, "cost": cost_for(m["in_per_1m"], m["out_per_1m"])} for m in CATALOG
    ]
    return {"profiles": {"low": PROFILE_LOW, "high": PROFILE_HIGH}, "models": models}
