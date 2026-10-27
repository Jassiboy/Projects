"""Validate SQL before execution and return sanitized, bounded query results."""

import time
from dataclasses import dataclass
from collections.abc import Sequence
from math import isfinite
from typing import Any, Protocol

from .base import (
    DatabaseError,
    DatabaseQueryError,
    QueryTimeoutError,
    QueryValidationError,
)
from .models import QueryResult
from .sql_validator import DEFAULT_ROW_LIMIT, MAXIMUM_ROW_LIMIT, SQLValidator


class QueryAdapter(Protocol):
    """Protocol for adapters that can execute a bounded query."""
    def execute_query(
        self,
        sql: str,
        parameters: Sequence[Any] | None = None,
        row_limit: int = 100,
        timeout_seconds: float | None = None,
    ) -> QueryResult:
        """Execute a query and return its bounded result."""

        ...


@dataclass(frozen=True)
class SafeQueryResult:
    """Represent SafeQueryResult data or behavior used by the application."""
    executed_sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    execution_time: float


class SafeQueryRunner:
    """Apply SQL policy before delegating execution to a database adapter."""
    def __init__(
        self,
        adapter: QueryAdapter,
        validator: SQLValidator | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        """Initialize the SafeQueryRunner with its required collaborators and state."""
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be greater than zero")
        self._adapter = adapter
        self._validator = validator or SQLValidator()
        self._timeout_seconds = timeout_seconds

    def run(
        self,
        sql: str,
        row_limit: int | None = None,
    ) -> SafeQueryResult:
        """Perform run and return the resulting application value."""
        validation = self._validator.validate(sql, row_limit=row_limit)
        if not validation.is_valid or validation.normalized_sql is None:
            raise QueryValidationError(
                validation.rejection_reason or "SQL query is not valid"
            )

        effective_limit = (
            DEFAULT_ROW_LIMIT
            if row_limit is None
            else min(row_limit, MAXIMUM_ROW_LIMIT)
        )
        started_at = time.perf_counter()
        try:
            result = self._adapter.execute_query(
                validation.normalized_sql,
                row_limit=effective_limit,
                timeout_seconds=self._timeout_seconds,
            )
        except QueryTimeoutError:
            raise QueryTimeoutError("Query timed out") from None
        except DatabaseError:
            raise DatabaseQueryError("Query execution failed") from None
        except Exception:
            raise DatabaseQueryError("Query execution failed") from None

        return SafeQueryResult(
            executed_sql=result.executed_sql or validation.normalized_sql,
            columns=result.columns,
            rows=result.rows,
            row_count=result.row_count,
            truncated=result.truncated,
            execution_time=max(result.execution_time, time.perf_counter() - started_at),
        )
