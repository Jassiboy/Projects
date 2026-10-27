"""Load and validate database and language-model configuration from environment variables."""

from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class DatabaseSettings(BaseSettings):
    """Validated settings used to establish and bound database connections."""
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(validation_alias="DB_HOST")
    port: int = Field(default=3306, validation_alias="DB_PORT")
    user: str = Field(validation_alias="DB_USER")
    password: str = Field(default="", validation_alias="DB_PASSWORD")
    database: str = Field(validation_alias="DB_NAME")
    pool_size: int = Field(default=5, validation_alias="DB_POOL_SIZE", ge=1)
    max_row_limit: int = Field(default=1000, validation_alias="DB_MAX_ROW_LIMIT", ge=1)


class LLMSettings(BaseSettings):
    """Validated settings used to select and call the configured LLM provider."""
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    provider: str = Field(default="gemini", validation_alias="LLM_PROVIDER")
    gemini_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    )
    gemini_model: str = Field(
        default="gemini-flash-lite-latest",
        validation_alias="GEMINI_MODEL",
        min_length=1,
    )
    gemini_fallback_model: str | None = Field(
        default="gemini-3.1-flash-lite",
        validation_alias="GEMINI_FALLBACK_MODEL",
        min_length=1,
    )
    timeout_seconds: float = Field(
        default=30.0,
        validation_alias="LLM_TIMEOUT_SECONDS",
        gt=0,
        allow_inf_nan=False,
    )
    max_retries: int = Field(
        default=2,
        validation_alias="LLM_MAX_RETRIES",
        ge=0,
        le=5,
    )
