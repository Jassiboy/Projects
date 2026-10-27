"""Call Gemini for structured output with retries, fallback, and sanitized failures."""

import json
import logging
import time
from typing import Any, TypeVar

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from backend.app.config import LLMSettings

from .base import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMProvider,
    LLMProviderError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
    ResponseModel,
)
from .models import LLMResponse, TokenUsage


ResponseSchema = TypeVar("ResponseSchema", bound=BaseModel)
RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """Implement structured LLM generation through the Gemini API."""
    def __init__(
        self,
        settings: LLMSettings | None = None,
        client: Any | None = None,
    ) -> None:
        """Initialize the GeminiProvider with its required collaborators and state."""
        self._settings = settings or LLMSettings()
        if not self._settings.gemini_model.strip():
            raise LLMConfigurationError("Gemini model is not configured")
        if client is None:
            api_key = self._settings.gemini_api_key
            if api_key is None or not api_key.get_secret_value():
                raise LLMConfigurationError("Gemini API key is not configured")
            try:
                client = genai.Client(
                    api_key=api_key.get_secret_value(),
                    http_options=types.HttpOptions(
                        timeout=int(self._settings.timeout_seconds * 1000),
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                )
            except (TypeError, ValueError, httpx.HTTPError):
                raise LLMConfigurationError(
                    "Could not initialize Gemini provider"
                ) from None
        self._client = client

    def generate_structured(
        self,
        prompt: str,
        response_model: type[ResponseModel],
    ) -> LLMResponse[ResponseModel]:
        """Perform generate structured and return the resulting application value."""
        if not isinstance(prompt, str) or not prompt.strip():
            raise LLMResponseError("Prompt must not be empty")
        if not isinstance(response_model, type) or not issubclass(
            response_model, BaseModel
        ):
            raise LLMResponseError("A Pydantic response model is required")

        started_at = time.perf_counter()
        model_name = self._settings.gemini_model
        try:
            response = self._generate_with_retries(
                prompt,
                response_model,
                model_name,
            )
        except LLMProviderUnavailableError:
            fallback_model = self._settings.gemini_fallback_model
            if fallback_model is None or fallback_model.strip() == model_name:
                raise
            model_name = fallback_model.strip()
            logger.warning(
                "Gemini model is unavailable; retrying with configured fallback model %s",
                model_name,
            )
            response = self._generate_with_retries(
                prompt,
                response_model,
                model_name,
            )
        latency_seconds = time.perf_counter() - started_at

        try:
            parsed = self._parse_response(response, response_model)
        except (ValidationError, json.JSONDecodeError, TypeError, ValueError):
            raise LLMResponseError(
                "Gemini returned an invalid structured response"
            ) from None

        return LLMResponse(
            parsed_output=parsed,
            provider_name="gemini",
            model_name=model_name,
            latency_seconds=latency_seconds,
            token_usage=self._token_usage(response),
            finish_status=self._finish_status(response),
        )

    def _generate_with_retries(
        self,
        prompt: str,
        response_model: type[ResponseSchema],
        model_name: str,
    ) -> Any:
        """Internal helper that performs generate with retries and returns the normalized result."""
        for attempt in range(self._settings.max_retries + 1):
            try:
                return self._client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=_gemini_response_schema(response_model),
                    ),
                )
            except errors.APIError as error:
                status_code = error.code
                if status_code in {401, 403}:
                    raise LLMAuthenticationError(
                        "Gemini authentication failed"
                    ) from None
                if status_code not in RETRYABLE_STATUS_CODES:
                    raise LLMProviderError("Gemini request failed") from None
                if attempt < self._settings.max_retries:
                    self._wait_before_retry(attempt)
                    continue
                if status_code in {408, 504}:
                    raise LLMTimeoutError("Gemini request timed out") from None
                if status_code == 429:
                    raise LLMRateLimitError(
                        "Gemini rate limit exceeded"
                    ) from None
                if status_code == 503:
                    raise LLMProviderUnavailableError(
                        "Gemini model is temporarily unavailable"
                    ) from None
                raise LLMProviderError("Gemini request failed") from None
            except (httpx.TimeoutException, TimeoutError):
                if attempt < self._settings.max_retries:
                    self._wait_before_retry(attempt)
                    continue
                raise LLMTimeoutError("Gemini request timed out") from None
            except httpx.HTTPError:
                raise LLMProviderError("Gemini request failed") from None

        raise LLMProviderError("Gemini request failed")

    @staticmethod
    def _parse_response(
        response: Any,
        response_model: type[ResponseSchema],
    ) -> ResponseSchema:
        """Internal helper that performs parse response and returns the normalized result."""
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, response_model):
            return parsed
        if isinstance(parsed, BaseModel):
            parsed = parsed.model_dump()
        if parsed is not None:
            return response_model.model_validate(parsed)

        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise LLMResponseError("Gemini returned an empty response")
        return response_model.model_validate_json(text)

    @staticmethod
    def _token_usage(response: Any) -> TokenUsage | None:
        """Internal helper that performs token usage and returns the normalized result."""
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return None
        return TokenUsage(
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
            total_tokens=getattr(usage, "total_token_count", None),
        )

    @staticmethod
    def _finish_status(response: Any) -> str:
        """Internal helper that performs finish status and returns the normalized result."""
        candidates = getattr(response, "candidates", None) or ()
        if not candidates:
            return "UNKNOWN"
        finish_reason = getattr(candidates[0], "finish_reason", None)
        if finish_reason is None:
            return "UNKNOWN"
        return getattr(finish_reason, "name", str(finish_reason))

    @staticmethod
    def _wait_before_retry(attempt: int) -> None:
        # Give provider-side throttling time to clear, but keep retries bounded.
        """Internal helper that performs wait before retry and returns the normalized result."""
        time.sleep(min(1.0 * (2**attempt), 8.0))


def _gemini_response_schema(response_model: type[BaseModel]) -> dict[str, Any]:
    """Internal helper that performs gemini response schema and returns the normalized result."""
    return _remove_additional_properties(response_model.model_json_schema())


def _remove_additional_properties(value: Any) -> Any:
    """Internal helper that performs remove additional properties and returns the normalized result."""
    if isinstance(value, dict):
        return {
            key: _remove_additional_properties(item)
            for key, item in value.items()
            if key != "additionalProperties"
        }
    if isinstance(value, list):
        return [_remove_additional_properties(item) for item in value]
    return value
