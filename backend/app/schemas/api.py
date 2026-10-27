"""Define and validate public API request and response payloads."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from backend.app.analysis.models import AnalysisResponse


class AnalyzeRequest(BaseModel):
    """Represent AnalyzeRequest data or behavior used by the application."""
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        """Perform question must not be blank and return the resulting application value."""
        if not value.strip():
            raise ValueError("question must not be blank")
        return value.strip()


class SQLRunRequest(BaseModel):
    """Represent SQLRunRequest data or behavior used by the application."""
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    sql: str = Field(min_length=1, max_length=20_000)
    assumptions: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("question", "sql")
    @classmethod
    def values_must_not_be_blank(cls, value: str) -> str:
        """Perform values must not be blank and return the resulting application value."""
        if not value.strip():
            raise ValueError("value must not be blank")
        return value.strip()


class HealthResponse(BaseModel):
    """Represent HealthResponse data or behavior used by the application."""
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    database: Literal["connected", "unavailable"]


class DatabaseConnectRequest(BaseModel):
    """Represent DatabaseConnectRequest data or behavior used by the application."""
    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    user: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(default=SecretStr(""), max_length=1024)
    database: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_$-]+$")

    @field_validator("host", "user", "database")
    @classmethod
    def connection_values_must_not_be_blank(cls, value: str) -> str:
        """Perform connection values must not be blank and return the resulting application value."""
        if not value.strip():
            raise ValueError("connection value must not be blank")
        return value.strip()


class DatabaseConnectResponse(BaseModel):
    """Represent DatabaseConnectResponse data or behavior used by the application."""
    model_config = ConfigDict(extra="forbid")

    connection_id: str
    database: str
    table_count: int = Field(ge=0)


__all__ = [
    "AnalysisResponse",
    "AnalyzeRequest",
    "DatabaseConnectRequest",
    "DatabaseConnectResponse",
    "HealthResponse",
    "SQLRunRequest",
]
