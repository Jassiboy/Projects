"""Define provider-neutral LLM response and token-usage records."""

from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel


StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)


@dataclass(frozen=True)
class TokenUsage:
    """Represent TokenUsage data or behavior used by the application."""
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class LLMResponse(Generic[StructuredOutput]):
    """Represent LLMResponse data or behavior used by the application."""
    parsed_output: StructuredOutput
    provider_name: str
    model_name: str
    latency_seconds: float
    token_usage: TokenUsage | None
    finish_status: str
