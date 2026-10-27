"""Create the configured provider-neutral LLM implementation."""

from backend.app.config import LLMSettings

from .base import LLMConfigurationError, LLMProvider
from .gemini import GeminiProvider


def create_llm_provider(settings: LLMSettings | None = None) -> LLMProvider:
    """Create and return the LLM provider selected by configuration."""
    configuration = settings or LLMSettings()
    provider_name = configuration.provider.strip().casefold()
    if provider_name == "gemini":
        return GeminiProvider(configuration)
    if provider_name in {"openai", "claude"}:
        raise LLMConfigurationError(
            f"LLM provider '{provider_name}' is not implemented"
        )
    raise LLMConfigurationError(
        f"Unknown LLM provider '{provider_name or '<empty>'}'"
    )
