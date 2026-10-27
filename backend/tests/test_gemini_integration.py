"""Verify gemini integration behavior with isolated unit or opt-in integration tests."""

import os
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.config import LLMSettings
from backend.app.llm.factory import create_llm_provider


def _has_gemini_key() -> bool:
    """Return whether gemini key satisfies the required condition."""
    try:
        return LLMSettings().gemini_api_key is not None
    except ValidationError:
        return False


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_GEMINI_INTEGRATION") != "1" or not _has_gemini_key(),
    reason=(
        "Set RUN_GEMINI_INTEGRATION=1 and configure GEMINI_API_KEY "
        "to call the Gemini API"
    ),
)


class IntegrationGreeting(BaseModel):
    """Represent IntegrationGreeting data or behavior used by the application."""
    answer: str


def test_gemini_returns_structured_output_without_database_access():
    """Verify that gemini returns structured output without database access; the test passes when the expected behavior is preserved."""
    provider = create_llm_provider()

    result = provider.generate_structured(
        "Return a JSON object with answer set to exactly: ready",
        IntegrationGreeting,
    )

    assert result.provider_name == "gemini"
    assert result.parsed_output.answer.casefold() == "ready"
