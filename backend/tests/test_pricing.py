from app.services.pricing import calculate_cost_micros, resolve_model_pricing


def test_catalog_pricing_calculates_recorded_gpt_5_4_mini_cost() -> None:
    pricing = resolve_model_pricing("gpt-5.4-mini")

    assert pricing.input_per_million == 0.75
    assert pricing.output_per_million == 4.50
    assert pricing.source == "openai_catalog_2026-10-22"
    assert calculate_cost_micros(14_750, 7_083, pricing) == 42_936


def test_scoped_pricing_overrides_catalog_and_unknown_models_are_unpriced() -> None:
    custom = resolve_model_pricing(
        "gpt-5.4-mini",
        {"input_per_million": 1.25, "output_per_million": 6.0},
    )
    unknown = resolve_model_pricing("private-model")

    assert custom.source == "scoped_configuration"
    assert calculate_cost_micros(1_000, 500, custom) == 4_250
    assert unknown.source == "unpriced"
    assert calculate_cost_micros(1_000, 500, unknown) == 0
