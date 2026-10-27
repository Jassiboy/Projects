"""Choose and validate a useful visualization for a structured analysis result."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .models import ChartSpec, SQLPlan


class ChartPolicy:
    """Select a chart only when returned fields and result shape support it."""
    def build_spec(
        self,
        plan: SQLPlan,
        columns: Sequence[str],
        rows: Sequence[Mapping[str, Any]],
    ) -> ChartSpec:
        """Build and return spec."""
        expected_type, x_field, y_field = self._infer_chart(columns, rows)
        suggestion = plan.chart_suggestion
        if (
            suggestion is not None
            and suggestion.chart_type == expected_type
            and self._valid_fields(suggestion, columns, expected_type)
        ):
            return ChartSpec(
                chart_type=expected_type,
                title=suggestion.title or plan.intent,
                x_field=suggestion.x_field,
                y_field=suggestion.y_field,
            )
        return ChartSpec(
            chart_type=expected_type,
            title=plan.intent,
            x_field=x_field,
            y_field=y_field,
        )

    @staticmethod
    def _infer_chart(
        columns: Sequence[str],
        rows: Sequence[Mapping[str, Any]],
    ) -> tuple[str, str | None, str | None]:
        """Internal helper that performs infer chart and returns the normalized result."""
        if not columns or not rows:
            return "table", None, None

        numeric_fields = [
            column
            for column in columns
            if any(
                isinstance(row.get(column), (int, float, Decimal))
                and not isinstance(row.get(column), bool)
                for row in rows
            )
        ]
        time_fields = [
            column
            for column in columns
            if any(
                isinstance(row.get(column), (date, datetime))
                or any(token in column.casefold() for token in ("date", "time", "year", "month"))
                for row in rows
            )
        ]
        if time_fields and numeric_fields:
            return "line", time_fields[0], numeric_fields[0]
        category_fields = [
            column
            for column in columns
            if column not in numeric_fields
        ]
        if category_fields and numeric_fields:
            return "bar", category_fields[0], numeric_fields[0]
        if len(rows) == 1 and len(numeric_fields) == 1:
            return "kpi", None, numeric_fields[0]
        return "table", None, None

    @staticmethod
    def _valid_fields(
        suggestion: Any,
        columns: Sequence[str],
        expected_type: str,
    ) -> bool:
        """Internal helper that performs valid fields and returns the normalized result."""
        available = set(columns)
        if expected_type == "kpi":
            return suggestion.x_field is None and (
                suggestion.y_field is None or suggestion.y_field in available
            )
        if expected_type == "table":
            return suggestion.x_field is None and suggestion.y_field is None
        return (
            suggestion.x_field in available
            and suggestion.y_field in available
            and suggestion.x_field != suggestion.y_field
        )
