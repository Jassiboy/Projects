"""Define provider-neutral LLM errors and the structured-generation interface."""

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

from .models import LLMResponse


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class LLMError(RuntimeError):
    """Base exception for provider-neutral LLM failures."""


class LLMConfigurationError(LLMError):
    """LLM provider configuration is missing or invalid."""


class LLMAuthenticationError(LLMError):
    """The configured LLM credentials were rejected."""


class LLMRateLimitError(LLMError):
    """The LLM provider rate limit was reached."""


class LLMTimeoutError(LLMError):
    """The LLM request exceeded its configured timeout."""


class LLMResponseError(LLMError):
    """The provider returned an empty or invalid structured response."""


class LLMProviderError(LLMError):
    """The provider request failed for a non-recoverable reason."""


class LLMProviderUnavailableError(LLMProviderError):
    """The configured model is temporarily unavailable."""


class LLMProvider(ABC):
    """Abstract interface implemented by structured-output LLM providers."""

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        response_model: type[ResponseModel],
    ) -> LLMResponse[ResponseModel]:
        """Generate and validate a structured response for a prompt."""
