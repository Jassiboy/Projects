"""Define typed plans, results, chart specifications, and API response models for analysis."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ChartType = Literal["line", "bar", "kpi", "table"]


class ChartSuggestion(BaseModel):
    """Represent ChartSuggestion data or behavior used by the application."""
    model_config = ConfigDict(extra="forbid")

    chart_type: ChartType
    title: str = Field(default="", max_length=160)
    x_field: str | None = None
    y_field: str | None = None


class SQLPlan(BaseModel):
    """Represent SQLPlan data or behavior used by the application."""
    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, max_length=500)
    direct_answer: str | None = Field(default=None, max_length=4000)
    relevant_tables: list[str] = Field(default_factory=list, max_length=20)
    sql: str = Field(default="", max_length=20_000)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    clarification_question: str | None = Field(default=None, max_length=1000)
    chart_suggestion: ChartSuggestion | None = None

    @model_validator(mode="after")
    def normalize_clarification(self) -> "SQLPlan":
        """Normalize an optional clarification string and return a clean value or null."""
        if self.clarification_question is not None:
            self.clarification_question = self.clarification_question.strip() or None
        return self


class ChartSpec(BaseModel):
    """Represent ChartSpec data or behavior used by the application."""
    model_config = ConfigDict(extra="forbid")

    chart_type: ChartType
    title: str = Field(default="", max_length=160)
    x_field: str | None = None
    y_field: str | None = None


class ExecutionMetadata(BaseModel):
    """Represent ExecutionMetadata data or behavior used by the application."""
    model_config = ConfigDict(extra="forbid")

    row_count: int = Field(ge=0)
    execution_time_seconds: float = Field(ge=0)
    truncated: bool
    attempts: int = Field(ge=1, le=2)


class AnalysisResult(BaseModel):
    """Represent AnalysisResult data or behavior used by the application."""
    model_config = ConfigDict(extra="forbid")

    explanation: str
    validated_sql: str | None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    chart_spec: ChartSpec | None
    warnings: list[str] = Field(default_factory=list)
    execution_metadata: ExecutionMetadata | None = None
    clarification_question: str | None = None


class AnalysisResponse(BaseModel):
    """Represent AnalysisResponse data or behavior used by the application."""
    model_config = ConfigDict(extra="forbid")

    answer: str
    sql: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    chart: ChartSpec | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    execution_metadata: ExecutionMetadata | None = None

    @property
    def explanation(self) -> str:
        """Perform explanation and return the resulting application value."""
        return self.answer

    @property
    def validated_sql(self) -> str | None:
        """Validate validated sql and return the policy result."""
        return self.sql

    @property
    def chart_spec(self) -> ChartSpec | None:
        """Perform chart spec and return the resulting application value."""
        return self.chart
