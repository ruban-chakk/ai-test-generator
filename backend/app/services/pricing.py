from __future__ import annotations

from dataclasses import dataclass


# USD per million text tokens. Catalog entries are fallbacks only; scoped
# administrator pricing overrides them. Last verified against the official
# OpenAI model page on 2026-10-22.
MODEL_PRICING_USD_PER_MILLION: dict[str, tuple[float, float]] = {
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4": (2.50, 15.00),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
}


@dataclass(frozen=True)
class ResolvedPricing:
    input_per_million: float
    output_per_million: float
    source: str


def resolve_model_pricing(model: str, configured: dict | None = None) -> ResolvedPricing:
    configured = configured if isinstance(configured, dict) else {}
    normalized_model = model.strip().lower()
    # New configuration format: {"model-id": {"input_per_million": ..., "output_per_million": ...}}
    # Accept both exact and case-insensitive model keys so model aliases can be changed safely.
    model_config = next(
        (value for key, value in configured.items() if str(key).strip().lower() == normalized_model and isinstance(value, dict)),
        None,
    )
    if model_config is not None:
        configured = model_config
    try:
        configured_input = float(configured.get("input_per_million", 0) or 0)
        configured_output = float(configured.get("output_per_million", 0) or 0)
    except (TypeError, ValueError):
        configured_input = configured_output = 0
    if configured_input > 0 or configured_output > 0:
        return ResolvedPricing(max(0, configured_input), max(0, configured_output), "scoped_configuration")

    catalog = MODEL_PRICING_USD_PER_MILLION.get(normalized_model)
    if catalog:
        return ResolvedPricing(catalog[0], catalog[1], "openai_catalog_2026-10-22")
    return ResolvedPricing(0, 0, "unpriced")


def calculate_cost_micros(input_tokens: int, output_tokens: int, pricing: ResolvedPricing) -> int:
    # A USD-per-million rate multiplied by tokens is numerically equal to
    # micro-dollars: tokens * (USD / 1M tokens) * (1M micro-USD / USD).
    return max(0, round(input_tokens * pricing.input_per_million + output_tokens * pricing.output_per_million))
