"""Implement pooled, bounded, read-only MySQL metadata and query operations."""

import re
import time
from collections.abc import Sequence
from math import isfinite
from typing import Any
from uuid import uuid4

import mysql.connector
from mysql.connector.pooling import MySQLConnectionPool
from pydantic import ValidationError
from sqlglot import exp

from ..config import DatabaseSettings
from .base import (
    DatabaseAdapter,
    DatabaseConfigurationError,
    DatabaseError,
    DatabaseConnectionError,
    DatabaseQueryError,
    QueryTimeoutError,
    QueryValidationError,
)
from .models import ColumnInfo, QueryResult, TableInfo, TableSchema
from .sql_validator import SQLValidator, parse_mysql_sql, render_mysql_sql


class MySQLReadOnlyAdapter(DatabaseAdapter):
    """Provide pooled MySQL access that is restricted to bounded reads."""
    def __init__(self, settings: DatabaseSettings | None = None) -> None:
        """Initialize the MySQLReadOnlyAdapter with its required collaborators and state."""
        try:
            self._settings = settings or DatabaseSettings()
        except ValidationError as error:
            raise DatabaseConfigurationError(
                "Database settings are missing or invalid"
            ) from error
        self._closed = False
        try:
            self._pool: MySQLConnectionPool | None = MySQLConnectionPool(
                pool_name=f"readonly_{uuid4().hex[:12]}",
                pool_size=self._settings.pool_size,
                pool_reset_session=True,
                host=self._settings.host,
                port=self._settings.port,
                user=self._settings.user,
                password=self._settings.password,
                database=self._settings.database,
                autocommit=True,
            )
        except mysql.connector.Error as error:
            raise DatabaseConnectionError(
                f"Could not create MySQL connection pool: {error}"
            ) from error

    def _get_connection(self) -> mysql.connector.MySQLConnection:
        """Internal helper that performs get connection and returns the normalized result."""
        pool = self._pool
        if self._closed or pool is None:
            raise DatabaseConnectionError("MySQL adapter is closed")
        try:
            return pool.get_connection()
        except mysql.connector.Error as error:
            raise DatabaseConnectionError(
                f"Could not get a MySQL connection: {error}"
            ) from error

    def health_check(self) -> bool:
        """Perform health check and return the resulting application value."""
        with self._cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
        if row is None or row[0] != 1:
            raise DatabaseQueryError("MySQL health check returned an unexpected result")
        return True

    def list_tables(self) -> list[TableInfo]:
        """Return the available tables records."""
        sql = """
            SELECT TABLE_NAME, TABLE_TYPE
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME
        """
        with self._cursor(dictionary=True) as cursor:
            cursor.execute(sql, (self._settings.database,))
            rows = cursor.fetchall()
        return [
            TableInfo(name=row["TABLE_NAME"], table_type=row["TABLE_TYPE"])
            for row in rows
        ]

    def get_table_schema(self, table_name: str) -> TableSchema:
        """Return table schema for the requested context."""
        if not table_name or not re.fullmatch(r"[A-Za-z0-9_]+", table_name):
            raise QueryValidationError("Table name must be a valid SQL identifier")

        sql = """
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_KEY,
                COLUMN_DEFAULT, EXTRA
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """
        with self._cursor(dictionary=True) as cursor:
            cursor.execute(sql, (self._settings.database, table_name))
            rows = cursor.fetchall()
        if not rows:
            raise DatabaseQueryError(f"Table '{table_name}' was not found")

        return TableSchema(
            name=table_name,
            columns=[
                ColumnInfo(
                    name=row["COLUMN_NAME"],
                    data_type=row["DATA_TYPE"],
                    nullable=row["IS_NULLABLE"] == "YES",
                    key=row["COLUMN_KEY"] or None,
                    default=row["COLUMN_DEFAULT"],
                    extra=row["EXTRA"],
                )
                for row in rows
            ],
        )

    def load_catalog_metadata(
        self,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """Load and return catalog metadata."""
        tables_sql = """
            SELECT TABLE_NAME AS table_name, TABLE_COMMENT AS description
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """
        columns_sql = """
            SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name,
                COLUMN_TYPE AS data_type, IS_NULLABLE AS nullable,
                COLUMN_KEY AS column_key, COLUMN_COMMENT AS description,
                ORDINAL_POSITION AS ordinal_position
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """
        relationships_sql = """
            SELECT TABLE_NAME AS source_table, COLUMN_NAME AS source_column,
                CONSTRAINT_NAME AS constraint_name,
                REFERENCED_TABLE_NAME AS target_table,
                REFERENCED_COLUMN_NAME AS target_column,
                ORDINAL_POSITION AS ordinal_position
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = %s
                AND REFERENCED_TABLE_NAME IS NOT NULL
            ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION
        """
        try:
            with self._read_only_cursor(dictionary=True) as cursor:
                cursor.execute(tables_sql, (self._settings.database,))
                tables = cursor.fetchall()
                cursor.execute(columns_sql, (self._settings.database,))
                columns = cursor.fetchall()
                cursor.execute(relationships_sql, (self._settings.database,))
                relationships = cursor.fetchall()
        except DatabaseError:
            raise DatabaseQueryError(
                "Could not read schema metadata from MySQL"
            ) from None
        return tables, columns, relationships

    def execute_query(
        self,
        sql: str,
        parameters: Sequence[Any] | None = None,
        row_limit: int = 100,
        timeout_seconds: float | None = None,
    ) -> QueryResult:
        """Execute query and return its bounded result."""
        if row_limit < 1:
            raise QueryValidationError("row_limit must be greater than zero")
        if row_limit > self._settings.max_row_limit:
            raise QueryValidationError(
                f"row_limit cannot exceed {self._settings.max_row_limit}"
            )
        if timeout_seconds is not None and (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise QueryValidationError("timeout_seconds must be greater than zero")
        query = self._normalize_select(sql, row_limit)
        statements, placeholder_marker = parse_mysql_sql(query)
        query_tree = statements[0]
        query_limit = query_tree.args.get("limit")
        if query_limit is not None:
            limit_expression = query_limit.expression
            if (
                isinstance(limit_expression, exp.Literal)
                and not limit_expression.is_string
                and int(limit_expression.this) == row_limit
            ):
                query_tree.set("limit", None)
                query = render_mysql_sql(query_tree, placeholder_marker)

        bounded_query = f"SELECT * FROM ({query}) AS _bounded_result LIMIT %s"
        bound_parameters = tuple(parameters or ()) + (row_limit + 1,)
        started_at = time.perf_counter()
        with self._read_only_cursor(dictionary=True) as cursor:
            if timeout_seconds is not None:
                timeout_ms = max(1, int(timeout_seconds * 1000))
                cursor.execute(
                    "SET SESSION max_execution_time = %s",
                    (timeout_ms,),
                )
            cursor.execute(bounded_query, bound_parameters)
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description or ()]

        truncated = len(rows) > row_limit
        limited_rows = rows[:row_limit]
        return QueryResult(
            columns=columns,
            rows=limited_rows,
            row_count=len(limited_rows),
            execution_time=time.perf_counter() - started_at,
            truncated=truncated,
            executed_sql=bounded_query,
        )

    @staticmethod
    def _normalize_select(sql: str, row_limit: int) -> str:
        """Internal helper that performs normalize select and returns the normalized result."""
        validation = SQLValidator().validate(sql, row_limit=row_limit)
        if not validation.is_valid or validation.normalized_sql is None:
            raise QueryValidationError(
                validation.rejection_reason or "SQL query is not valid"
            )
        return validation.normalized_sql

    def _cursor(self, dictionary: bool = False) -> "_CursorContext":
        """Internal helper that performs cursor and returns the normalized result."""
        return _CursorContext(self._get_connection(), dictionary=dictionary)

    def _read_only_cursor(self, dictionary: bool = False) -> "_ReadOnlyCursorContext":
        """Internal helper that performs read only cursor and returns the normalized result."""
        return _ReadOnlyCursorContext(
            self._get_connection(), dictionary=dictionary
        )

    def close(self) -> None:
        """Perform close and return the resulting application value."""
        self._closed = True
        self._pool = None


class _CursorContext:
    """Manage a MySQL cursor and always release its connection."""
    def __init__(
        self,
        connection: mysql.connector.MySQLConnection,
        dictionary: bool,
    ) -> None:
        """Initialize the _CursorContext with its required collaborators and state."""
        self._connection = connection
        self._dictionary = dictionary
        self._cursor: Any = None

    def __enter__(self) -> Any:
        """Acquire and return the managed database cursor resource."""
        try:
            self._cursor = self._connection.cursor(dictionary=self._dictionary)
            return self._cursor
        except mysql.connector.Error as error:
            self._connection.close()
            raise DatabaseQueryError(f"MySQL operation failed: {error}") from error

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        """Release the managed cursor and connection, translating any database failure."""
        release_error: mysql.connector.Error | None = None
        try:
            if self._cursor is not None:
                self._cursor.close()
        except mysql.connector.Error as error:
            release_error = error
        try:
            self._connection.close()
        except mysql.connector.Error as error:
            release_error = release_error or error

        if isinstance(exc_value, mysql.connector.Error):
            if exc_value.errno == 3024:
                raise QueryTimeoutError("Query timed out") from exc_value
            raise DatabaseQueryError(f"MySQL query failed: {exc_value}") from exc_value
        if exc_type is None and release_error is not None:
            raise DatabaseConnectionError(
                f"Could not release MySQL connection: {release_error}"
            ) from release_error


class _ReadOnlyCursorContext(_CursorContext):
    """Manage a MySQL cursor inside an explicitly read-only transaction."""
    def __enter__(self) -> Any:
        """Acquire and return the managed database cursor resource."""
        cursor = super().__enter__()
        try:
            self._connection.rollback()
            self._connection.start_transaction(readonly=True)
        except mysql.connector.Error as error:
            cursor.close()
            self._connection.close()
            raise DatabaseConnectionError(
                f"Could not start a read-only transaction: {error}"
            ) from error
        return cursor

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        """Release the managed cursor and connection, translating any database failure."""
        try:
            self._connection.rollback()
        except mysql.connector.Error as error:
            if exc_type is None:
                super().__exit__(None, None, None)
                raise DatabaseQueryError(
                    f"Could not finish read-only transaction: {error}"
                ) from error
        super().__exit__(exc_type, exc_value, traceback)
