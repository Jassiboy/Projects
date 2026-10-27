"""Define database error types and the adapter contract used by higher layers."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from .models import QueryResult, TableInfo, TableSchema


class DatabaseError(Exception):
    """Base error for database adapter failures."""


class DatabaseConfigurationError(DatabaseError):
    """Database configuration is missing or invalid."""


class DatabaseConnectionError(DatabaseError):
    """The database connection could not be established or used."""


class DatabaseQueryError(DatabaseError):
    """A database query failed."""


class QueryTimeoutError(DatabaseQueryError):
    """A database query exceeded its execution timeout."""


class QueryValidationError(DatabaseError):
    """A query does not meet the adapter's read-only query requirements."""


class DatabaseAdapter(ABC):
    """Abstract interface implemented by supported database backends."""

    @abstractmethod
    def health_check(self) -> bool:
        """Return true when the database responds to a simple read query."""

    @abstractmethod
    def list_tables(self) -> list[TableInfo]:
        """Return table names and types for the configured database."""

    @abstractmethod
    def get_table_schema(self, table_name: str) -> TableSchema:
        """Return column metadata for a table."""

    @abstractmethod
    def execute_query(
        self,
        sql: str,
        parameters: Sequence[Any] | None = None,
        row_limit: int = 100,
        timeout_seconds: float | None = None,
    ) -> QueryResult:
        """Execute one bounded read query."""

    @abstractmethod
    def close(self) -> None:
        """Release adapter resources."""
