"""Verify llm factory behavior with isolated unit or opt-in integration tests."""

from unittest.mock import patch

import pytest
from pydantic import SecretStr

from backend.app.config import LLMSettings
from backend.app.llm.base import LLMConfigurationError
from backend.app.llm.factory import create_llm_provider


def settings(provider):
    """Perform settings and return the resulting application value."""
    return LLMSettings(
        provider=provider,
        gemini_api_key=SecretStr("test-key"),
        _env_file=None,
    )


def test_factory_selects_gemini_provider():
    """Verify that factory selects gemini provider; the test passes when the expected behavior is preserved."""
    with patch("backend.app.llm.factory.GeminiProvider") as provider_class:
        result = create_llm_provider(settings("gemini"))

    provider_class.assert_called_once()
    assert result is provider_class.return_value


@pytest.mark.parametrize("provider", ["openai", "claude"])
def test_future_providers_fail_explicitly(provider):
    """Verify that future providers fail explicitly; the test passes when the expected behavior is preserved."""
    with pytest.raises(
        LLMConfigurationError,
        match=f"^LLM provider '{provider}' is not implemented$",
    ):
        create_llm_provider(settings(provider))


def test_unknown_provider_is_rejected():
    """Verify that unknown provider is rejected; the test passes when the expected behavior is preserved."""
    with pytest.raises(LLMConfigurationError, match="^Unknown LLM provider 'local'$"):
        create_llm_provider(settings("local"))
