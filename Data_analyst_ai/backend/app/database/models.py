"""Define typed database table, column, schema, and query-result records."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TableInfo:
    """Represent TableInfo data or behavior used by the application."""
    name: str
    table_type: str


@dataclass(frozen=True)
class ColumnInfo:
    """Represent ColumnInfo data or behavior used by the application."""
    name: str
    data_type: str
    nullable: bool
    key: str | None
    default: Any
    extra: str


@dataclass(frozen=True)
class TableSchema:
    """Represent TableSchema data or behavior used by the application."""
    name: str
    columns: list[ColumnInfo]


@dataclass(frozen=True)
class QueryResult:
    """Represent QueryResult data or behavior used by the application."""
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    execution_time: float
    truncated: bool
    executed_sql: str | None = None
