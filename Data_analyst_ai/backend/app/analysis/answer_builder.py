"""Build evidence-grounded narrative answers from bounded SQL query results."""

import json
import re
from decimal import Decimal
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.app.llm.base import LLMProvider

from .models import AnalysisResult, ChartSpec, SQLPlan


class GroundedAnswer(BaseModel):
    """Structured narrative answer whose claims must be supported by supplied rows."""
    model_config = ConfigDict(extra="forbid")

    explanation: str = Field(min_length=1, max_length=4000)
    findings: list[str] = Field(default_factory=list, max_length=10)
    evidence: list[str] = Field(default_factory=list, max_length=30)


class AnswerBuilder:
    """Build grounded explanations from a question, plan, catalog, and query result."""
    def __init__(
        self,
        llm_provider: LLMProvider,
        max_rows_for_llm: int = 50,
    ) -> None:
        """Initialize the AnswerBuilder with its required collaborators and state."""
        if max_rows_for_llm < 1:
            raise ValueError("max_rows_for_llm must be greater than zero")
        self._llm_provider = llm_provider
        self._max_rows_for_llm = max_rows_for_llm

    def build(
        self,
        question: str,
        plan: SQLPlan,
        validated_sql: str,
        rows: list[dict[str, Any]],
        chart_spec: ChartSpec | None,
    ) -> AnalysisResult:
        """Perform build and return the resulting application value."""
        limited_rows = rows[: self._max_rows_for_llm]
        if not limited_rows:
            return AnalysisResult(
                explanation="No rows matched the question.",
                validated_sql=validated_sql,
                rows=rows,
                chart_spec=None,
                warnings=list(plan.assumptions),
            )
        prompt = (
            "Explain the query result for the user using only the supplied rows. "
            "Do not invent facts or calculate unstated metrics. Every numeric "
            "claim must exactly match a numeric value present in those rows. "
            "Put each factual finding in findings and list its supporting cell "
            "values verbatim in evidence. If there is insufficient evidence, say so. "
            "Return only the requested structured response.\n\n"
            f"Question:\n{question}\n\n"
            f"Assumptions:\n{json.dumps(plan.assumptions, ensure_ascii=True)}\n\n"
            f"Columns and result rows (bounded):\n"
            f"{json.dumps(_json_safe(limited_rows), ensure_ascii=True, separators=(',', ':'))}"
        )
        response = self._llm_provider.generate_structured(prompt, GroundedAnswer)
        answer = response.parsed_output
        allowed_values = {
            _cell_text(value)
            for row in limited_rows
            for value in row.values()
            if value is not None
        }
        if any(evidence not in allowed_values for evidence in answer.evidence):
            raise ValueError("Generated answer cites values absent from query results")
        allowed_numbers = {
            _canonical_number(token)
            for value in allowed_values
            for token in _NUMBER_PATTERN.findall(value)
        }
        answer_numbers = _NUMBER_PATTERN.findall(
            " ".join((answer.explanation, *answer.findings))
        )
        if any(_canonical_number(number) not in allowed_numbers for number in answer_numbers):
            raise ValueError("Generated answer contains unsupported numeric claims")
        explanation = answer.explanation
        if answer.findings:
            explanation = "\n".join(
                (explanation, *(f"- {finding}" for finding in answer.findings))
            )
        warnings = list(plan.assumptions)
        if len(rows) > len(limited_rows):
            warnings.append(
                f"Only the first {len(limited_rows)} rows were used to draft the explanation."
            )
        return AnalysisResult(
            explanation=explanation,
            validated_sql=validated_sql,
            rows=rows,
            chart_spec=chart_spec,
            warnings=warnings,
        )


_NUMBER_PATTERN = re.compile(r"(?<![\w.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?")


def _json_safe(value: Any) -> Any:
    """Internal helper that performs json safe and returns the normalized result."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError("Query results contain an unsupported value")


def _cell_text(value: Any) -> str:
    """Internal helper that performs cell text and returns the normalized result."""
    safe_value = _json_safe(value)
    return safe_value if isinstance(safe_value, str) else json.dumps(safe_value)


def _canonical_number(value: str) -> str:
    """Internal helper that performs canonical number and returns the normalized result."""
    return value.replace(",", "").removesuffix("%")
