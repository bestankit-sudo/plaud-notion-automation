from app import models_catalog as mc


def test_cost_for_matches_basis():
    c = mc.cost_for(5.0, 25.0)  # Opus 4.8
    # 8000/1e6*5 + 1500/1e6*25 = 0.04 + 0.0375 = 0.0775
    assert round(c["per_meeting"], 4) == 0.0775
    assert round(c["per_100"], 2) == 7.75


def test_catalog_has_exactly_the_allowed_anthropic_models():
    anthro = {m["model"] for m in mc.CATALOG if m["provider"] == "anthropic"}
    assert anthro == {"claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"}


def test_default_is_opus_4_8():
    defaults = [m for m in mc.CATALOG if m.get("default")]
    assert len(defaults) == 1
    assert defaults[0]["model"] == "claude-opus-4-8"


def test_catalog_with_costs_attaches_cost():
    out = mc.catalog_with_costs()
    assert out["token_profile"]["input_tokens"] == 8000
    by_model = {m["model"]: m for m in out["models"]}
    assert round(by_model["claude-sonnet-4-6"]["cost"]["per_100"], 2) == 4.65
    assert round(by_model["gpt-5.4-nano"]["cost"]["per_100"], 2) == 0.35
