"""Predictor session variants (US morning vs London+US)."""

from __future__ import annotations

from dataclasses import dataclass

VALID_PREDICTORS = frozenset({"us_morning", "london_us"})


@dataclass(frozen=True)
class PredictorSpec:
    id: str
    label: str
    prefix: str = "predictor"


def get_predictor_spec(variant: str, cfg: dict) -> PredictorSpec:
    if variant not in VALID_PREDICTORS:
        raise ValueError(f"Unknown predictor {variant!r}; choose from {sorted(VALID_PREDICTORS)}")
    labels = {
        "us_morning": "US morning (09:30–12:00 NYC)",
        "london_us": "London+US (07:00 UTC–12:00 NYC)",
    }
    return PredictorSpec(id=variant, label=labels[variant])


def resolve_predictor(cfg: dict, cli_variant: str | None) -> str:
    if cli_variant:
        return cli_variant
    return cfg.get("predictor", {}).get("default", "us_morning")
