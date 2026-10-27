"""Verify gemini provider behavior with isolated unit or opt-in integration tests."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from google.genai.errors import ClientError
from pydantic import BaseModel, SecretStr, ValidationError

from backend.app.analysis.models import SQLPlan
from backend.app.config import LLMSettings
from backend.app.llm.base import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)
from backend.app.llm.gemini import GeminiProvider


class Greeting(BaseModel):
    """Represent Greeting data or behavior used by the application."""
    answer: str


def make_settings(
    *,
    max_retries=2,
    api_key="test-api-key",
    fallback_model="backup-model",
):
    """Build and return settings."""
    return LLMSettings(
        provider="gemini",
        gemini_api_key=SecretStr(api_key) if api_key is not None else None,
        gemini_model="test-model",
        gemini_fallback_model=fallback_model,
        timeout_seconds=3.5,
        max_retries=max_retries,
        _env_file=None,
    )


@pytest.fixture
def client():
    """Perform client and return the resulting application value."""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = SimpleNamespace(
        parsed=Greeting(answer="Hello"),
        text='{"answer":"Hello"}',
        usage_metadata=SimpleNamespace(
            prompt_token_count=5,
            candidates_token_count=2,
            total_token_count=7,
        ),
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))],
    )
    return mock_client


def test_valid_structured_response_parses_with_common_metadata(client):
    """Verify that valid structured response parses with common metadata; the test passes when the expected behavior is preserved."""
    provider = GeminiProvider(make_settings(), client=client)

    result = provider.generate_structured("Say hello", Greeting)

    assert result.parsed_output == Greeting(answer="Hello")
    assert result.provider_name == "gemini"
    assert result.model_name == "test-model"
    assert result.latency_seconds >= 0
    assert result.token_usage.input_tokens == 5
    assert result.token_usage.output_tokens == 2
    assert result.token_usage.total_tokens == 7
    assert result.finish_status == "STOP"
    client.models.generate_content.assert_called_once()
    kwargs = client.models.generate_content.call_args.kwargs
    assert kwargs["contents"] == "Say hello"
    assert kwargs["config"].response_mime_type == "application/json"
    assert kwargs["config"].response_schema == Greeting.model_json_schema()


def test_gemini_response_schema_omits_unsupported_additional_properties(client):
    """Verify that gemini response schema omits unsupported additional properties; the test passes when the expected behavior is preserved."""
    client.models.generate_content.return_value = SimpleNamespace(
        parsed=SQLPlan(intent="Plan a query"),
        text='{"intent":"Plan a query"}',
        usage_metadata=None,
        candidates=[],
    )
    provider = GeminiProvider(make_settings(), client=client)

    provider.generate_structured("Plan a query", SQLPlan)

    schema = client.models.generate_content.call_args.kwargs[
        "config"
    ].response_schema
    assert isinstance(schema, dict)
    assert "additionalProperties" not in schema
    assert (
        "additionalProperties"
        not in schema["$defs"]["ChartSuggestion"]
    )


def test_response_model_still_rejects_extra_fields(client):
    """Verify that response model still rejects extra fields; the test passes when the expected behavior is preserved."""
    client.models.generate_content.return_value = SimpleNamespace(
        parsed={"intent": "Plan a query", "unexpected": "field"},
        text='{"intent":"Plan a query","unexpected":"field"}',
    )

    with pytest.raises(LLMResponseError):
        GeminiProvider(make_settings(), client=client).generate_structured(
            "Plan a query", SQLPlan
        )


@pytest.mark.parametrize(
    ("parsed", "text"),
    [
        (None, "{not valid json"),
        ({"answer": 42}, None),
    ],
)
def test_malformed_response_fails_safely(client, parsed, text):
    """Verify that malformed response fails safely; the test passes when the expected behavior is preserved."""
    client.models.generate_content.return_value = SimpleNamespace(
        parsed=parsed,
        text=text,
        candidates=[],
        usage_metadata=None,
    )

    with pytest.raises(
        LLMResponseError,
        match="^Gemini returned an invalid structured response$",
    ):
        GeminiProvider(make_settings(), client=client).generate_structured(
            "prompt must not leak", Greeting
        )


def test_empty_response_is_handled(client):
    """Verify that empty response is handled; the test passes when the expected behavior is preserved."""
    client.models.generate_content.return_value = SimpleNamespace(
        parsed=None,
        text="  ",
        candidates=[],
        usage_metadata=None,
    )

    with pytest.raises(LLMResponseError, match="^Gemini returned an empty response$"):
        GeminiProvider(make_settings(), client=client).generate_structured(
            "prompt", Greeting
        )


def test_authentication_error_is_mapped_without_exposing_sdk_message(client):
    """Verify that authentication error is mapped without exposing sdk message; the test passes when the expected behavior is preserved."""
    client.models.generate_content.side_effect = ClientError(
        401,
        {"error": {"message": "key=super-secret prompt=private"}},
    )

    with pytest.raises(LLMAuthenticationError) as error:
        GeminiProvider(make_settings(), client=client).generate_structured(
            "private prompt", Greeting
        )

    assert "super-secret" not in str(error.value)
    assert "private" not in str(error.value)
    assert error.value.__cause__ is None
    client.models.generate_content.assert_called_once()


def test_rate_limit_is_retried_then_mapped(client):
    """Verify that rate limit is retried then mapped; the test passes when the expected behavior is preserved."""
    client.models.generate_content.side_effect = ClientError(
        429,
        {"error": {"message": "rate limit"}},
    )

    with patch("backend.app.llm.gemini.time.sleep") as sleep:
        with pytest.raises(LLMRateLimitError, match="^Gemini rate limit exceeded$"):
            GeminiProvider(make_settings(max_retries=2), client=client).generate_structured(
                "prompt", Greeting
            )

    assert client.models.generate_content.call_count == 3
    assert sleep.call_count == 2
    assert {
        call.kwargs["model"]
        for call in client.models.generate_content.call_args_list
    } == {"test-model"}


def test_unavailable_model_fails_over_to_configured_fallback(client, caplog):
    """Verify that unavailable model fails over to configured fallback; the test passes when the expected behavior is preserved."""
    client.models.generate_content.side_effect = [
        ClientError(503, {"error": {"message": "temporarily unavailable"}}),
        ClientError(503, {"error": {"message": "temporarily unavailable"}}),
        ClientError(503, {"error": {"message": "temporarily unavailable"}}),
        client.models.generate_content.return_value,
    ]

    with patch("backend.app.llm.gemini.time.sleep"):
        result = GeminiProvider(make_settings(), client=client).generate_structured(
            "Say hello", Greeting
        )

    assert result.parsed_output == Greeting(answer="Hello")
    assert result.model_name == "backup-model"
    assert [
        call.kwargs["model"]
        for call in client.models.generate_content.call_args_list
    ] == ["test-model", "test-model", "test-model", "backup-model"]
    assert "configured fallback model backup-model" in caplog.text


def test_unavailable_model_without_fallback_raises_sanitized_error(client):
    """Verify that unavailable model without fallback raises sanitized error; the test passes when the expected behavior is preserved."""
    client.models.generate_content.side_effect = ClientError(
        503,
        {"error": {"message": "private provider detail"}},
    )

    with patch("backend.app.llm.gemini.time.sleep"):
        with pytest.raises(
            LLMProviderUnavailableError,
            match="^Gemini model is temporarily unavailable$",
        ) as error:
            GeminiProvider(
                make_settings(fallback_model=None),
                client=client,
            ).generate_structured("private prompt", Greeting)

    assert client.models.generate_content.call_count == 3
    assert "private provider detail" not in str(error.value)


def test_timeout_is_retried_with_bounded_attempts(client):
    """Verify that timeout is retried with bounded attempts; the test passes when the expected behavior is preserved."""
    client.models.generate_content.side_effect = httpx.ReadTimeout(
        "prompt and API key must not appear"
    )

    with patch("backend.app.llm.gemini.time.sleep"):
        with pytest.raises(LLMTimeoutError, match="^Gemini request timed out$"):
            GeminiProvider(make_settings(max_retries=1), client=client).generate_structured(
                "prompt", Greeting
            )

    assert client.models.generate_content.call_count == 2


def test_gateway_timeout_is_retried_then_mapped_to_timeout(client):
    """Verify that gateway timeout is retried then mapped to timeout; the test passes when the expected behavior is preserved."""
    client.models.generate_content.side_effect = ClientError(
        504,
        {"error": {"message": "sensitive provider diagnostics"}},
    )

    with patch("backend.app.llm.gemini.time.sleep"):
        with pytest.raises(LLMTimeoutError, match="^Gemini request timed out$") as error:
            GeminiProvider(make_settings(max_retries=1), client=client).generate_structured(
                "prompt", Greeting
            )

    assert error.value.__cause__ is None
    assert "sensitive provider diagnostics" not in str(error.value)
    assert client.models.generate_content.call_count == 2


def test_retries_disabled_means_single_attempt(client):
    """Verify that retries disabled means single attempt; the test passes when the expected behavior is preserved."""
    client.models.generate_content.side_effect = ClientError(
        429,
        {"error": {"message": "rate limit"}},
    )

    with pytest.raises(LLMRateLimitError):
        GeminiProvider(make_settings(max_retries=0), client=client).generate_structured(
            "prompt", Greeting
        )

    client.models.generate_content.assert_called_once()


def test_client_uses_configured_api_key_model_and_timeout():
    """Verify that client uses configured api key model and timeout; the test passes when the expected behavior is preserved."""
    settings = make_settings(api_key="do-not-log-this")

    with patch("backend.app.llm.gemini.genai.Client") as client_factory:
        GeminiProvider(settings)

    assert client_factory.call_args.kwargs["api_key"] == "do-not-log-this"
    assert client_factory.call_args.kwargs["http_options"].timeout == 3500
    assert (
        client_factory.call_args.kwargs["http_options"].retry_options.attempts == 1
    )


def test_api_key_is_read_from_environment_without_exposing_repr(monkeypatch):
    """Verify that api key is read from environment without exposing repr; the test passes when the expected behavior is preserved."""
    monkeypatch.setenv("GEMINI_API_KEY", "environment-secret")
    settings = LLMSettings(_env_file=None)

    assert settings.gemini_api_key.get_secret_value() == "environment-secret"
    assert "environment-secret" not in repr(settings)


def test_retry_configuration_has_a_hard_upper_bound():
    """Verify that retry configuration has a hard upper bound; the test passes when the expected behavior is preserved."""
    with pytest.raises(ValidationError):
        LLMSettings(max_retries=6, _env_file=None)


def test_missing_api_key_fails_without_constructing_client():
    """Verify that missing api key fails without constructing client; the test passes when the expected behavior is preserved."""
    with patch("backend.app.llm.gemini.genai.Client") as client_factory:
        with pytest.raises(
            LLMConfigurationError,
            match="^Gemini API key is not configured$",
        ):
            GeminiProvider(make_settings(api_key=None))

    client_factory.assert_not_called()


def test_secrets_and_prompt_are_not_written_to_logs(client, caplog):
    """Verify that secrets and prompt are not written to logs; the test passes when the expected behavior is preserved."""
    caplog.set_level(logging.DEBUG)
    client.models.generate_content.side_effect = ClientError(
        401,
        {"error": {"message": "key=secret-value prompt=private-prompt"}},
    )

    with pytest.raises(LLMAuthenticationError):
        GeminiProvider(make_settings(), client=client).generate_structured(
            "private-prompt", Greeting
        )

    assert "secret-value" not in caplog.text
    assert "private-prompt" not in caplog.text
