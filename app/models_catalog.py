"""Provider/model catalog + per-meeting cost estimate shown in the setup wizard.

Cost basis: a ~30-min meeting is approximated as 8000 input + 1500 output tokens
(title/overview/sections/action-items is light output). Prices are $/1M tokens.
Anthropic models are restricted to those with structured-output support
(see the worker AnthropicSummarizer): opus-4-8 / sonnet-4-6 / haiku-4-5.
"""

from __future__ import annotations

TOKEN_PROFILE = {"input_tokens": 8000, "output_tokens": 1500}

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


def cost_for(in_per_1m: float, out_per_1m: float) -> dict:
    per_meeting = (
        in_per_1m * TOKEN_PROFILE["input_tokens"] / 1_000_000
        + out_per_1m * TOKEN_PROFILE["output_tokens"] / 1_000_000
    )
    return {"per_meeting": round(per_meeting, 4), "per_100": round(per_meeting * 100, 2)}


def catalog_with_costs() -> dict:
    models = [
        {**m, "cost": cost_for(m["in_per_1m"], m["out_per_1m"])} for m in CATALOG
    ]
    return {"token_profile": TOKEN_PROFILE, "models": models}
