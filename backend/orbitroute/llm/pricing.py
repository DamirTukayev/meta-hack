"""Price table (USD) used for budget accounting. Source: dev.meta.ai/docs/pricing-rate-limits."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenPrice:
    input_per_m: float
    output_per_m: float
    cached_input_per_m: float


SPARK_1_3 = TokenPrice(input_per_m=1.25, output_per_m=4.25, cached_input_per_m=0.15)

# Models without a published price are billed at the Spark 1.3 rate: a safe over-estimate.
TOKEN_PRICES: dict[str, TokenPrice] = {"muse-spark-1.3": SPARK_1_3}

SAM_PER_IMAGE_USD = 2.50 / 1000


def token_price(model: str) -> TokenPrice:
    return TOKEN_PRICES.get(model, SPARK_1_3)


def token_cost(model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    price = token_price(model)
    fresh = max(input_tokens - cached_tokens, 0)
    return (
        fresh * price.input_per_m
        + cached_tokens * price.cached_input_per_m
        + output_tokens * price.output_per_m
    ) / 1_000_000

ASR_PER_HOUR_USD = 0.18  # Muse Voice Transcribe, per hour of audio
