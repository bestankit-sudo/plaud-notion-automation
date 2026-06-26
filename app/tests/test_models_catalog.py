from app import models_catalog as mc


def test_cost_for_range():
    c = mc.cost_for(5.0, 25.0)  # Opus 4.8
    # low: (5*5000 + 25*1000)/1e6 *100 = 0.05*100 = 5.00
    # high: (5*18000 + 25*2500)/1e6 *100 = 0.1525*100 = 15.25
    assert c["per_100_low"] == 5.0
    assert c["per_100_high"] == 15.25


def test_catalog_has_exactly_the_allowed_anthropic_models():
    anthro = {m["model"] for m in mc.CATALOG if m["provider"] == "anthropic"}
    assert anthro == {"claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"}


def test_default_is_opus_4_8():
    defaults = [m for m in mc.CATALOG if m.get("default")]
    assert len(defaults) == 1
    assert defaults[0]["model"] == "claude-opus-4-8"


def test_catalog_with_costs_attaches_cost():
    out = mc.catalog_with_costs()
    assert out["profiles"]["low"]["input_tokens"] == 5000
    assert out["profiles"]["high"]["input_tokens"] == 18000
    by_model = {m["model"]: m for m in out["models"]}
    assert by_model["claude-sonnet-4-6"]["cost"]["per_100_low"] == 3.0
    assert by_model["claude-sonnet-4-6"]["cost"]["per_100_high"] == 9.15
