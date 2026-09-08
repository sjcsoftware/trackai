"""Model pricing and cost estimation (port of Pricing.swift)."""

from __future__ import annotations

from typing import NamedTuple


class ModelPricing(NamedTuple):
    """Pricing per million tokens (USD)."""

    input: float
    output: float
    cache_write: float
    cache_read: float


def pricing(model):
    # type: (str) -> ModelPricing
    """Pricing per million tokens. Cache write ~= 1.25x input, cache read ~= 0.1x input."""
    m = model.lower()
    if "fable" in m or "mythos" in m:
        return ModelPricing(input=10, output=50, cache_write=12.5, cache_read=1.0)
    if "opus" in m:
        # Opus 4.5+ dropped to $5/$25; older Opus tiers were $15/$75.
        if any(tag in m for tag in ("opus-4-5", "opus-4-6", "opus-4-7", "opus-4-8")):
            return ModelPricing(input=5, output=25, cache_write=6.25, cache_read=0.5)
        return ModelPricing(input=15, output=75, cache_write=18.75, cache_read=1.5)
    if "haiku" in m:
        if "haiku-3-5" in m:
            return ModelPricing(input=0.8, output=4, cache_write=1.0, cache_read=0.08)
        if "haiku-3" in m:
            return ModelPricing(input=0.25, output=1.25, cache_write=0.3, cache_read=0.03)
        return ModelPricing(input=1, output=5, cache_write=1.25, cache_read=0.1)
    # Sonnet and unknown models default to Sonnet-tier pricing.
    return ModelPricing(input=3, output=15, cache_write=3.75, cache_read=0.3)


def cost(model, input_tokens, output_tokens, cache_create, cache_read):
    # type: (str, int, int, int, int) -> float
    p = pricing(model)
    return (
        input_tokens * p.input
        + output_tokens * p.output
        + cache_create * p.cache_write
        + cache_read * p.cache_read
    ) / 1_000_000.0


def pretty_model_name(model):
    # type: (str) -> str
    """"claude-opus-4-5-20251101" -> "Opus 4.5"."""
    m = model
    if m.startswith("gpt-"):
        parts = m.split("-")
        return "GPT-" + parts[1] + (" " + " ".join(p.capitalize() for p in parts[2:]) if len(parts) > 2 else "")
    if m.startswith("claude-"):
        m = m[len("claude-"):]
    parts = [p for p in m.split("-") if p]
    # Drop a trailing date snapshot like 20251101.
    if parts and len(parts[-1]) == 8 and parts[-1].isdigit():
        parts.pop()
    if not parts:
        return model
    family = parts[0]
    version = ".".join(parts[1:])
    fam_name = family[:1].upper() + family[1:]
    return fam_name if not version else "{} {}".format(fam_name, version)
