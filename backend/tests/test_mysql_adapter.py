"""Verify mysql adapter behavior with isolated unit or opt-in integration tests."""

import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import mysql.connector
import pytest

from backend.app.database.base import (
    DatabaseQueryError,
    QueryTimeoutError,
    QueryValidationError,
)
from backend.app.database.mysql import MySQLReadOnlyAdapter


@pytest.fixture
def adapter():
    """Perform adapter and return the resulting application value."""
    pool = MagicMock()
    with patch(
        "backend.app.database.mysql.MySQLConnectionPool", return_value=pool
    ):
        instance = MySQLReadOnlyAdapter(
            SimpleNamespace(
                pool_size=2,
                host="localhost",
                port=3306,
                user="reader",
                password="",
                database="analyst_ai",
                max_row_limit=10,
            )
        )
    yield instance, pool
    instance.close()


def test_rejects_non_select_queries(adapter):
    """Verify that rejects non select queries; the test passes when the expected behavior is preserved."""
    instance, _ = adapter
    for sql in (
        "INSERT INTO customers VALUES (1)",
        "UPDATE customers SET customer_name = 'x'",
        "DELETE FROM customers",
        "SELECT 1; DELETE FROM customers",
        "SELECT * FROM customers INTO OUTFILE 'x'",
    ):
        with pytest.raises(QueryValidationError):
            instance.execute_query(sql)


def test_rejects_row_limit_above_configured_maximum(adapter):
    """Verify that rejects row limit above configured maximum; the test passes when the expected behavior is preserved."""
    instance, _ = adapter
    with pytest.raises(QueryValidationError, match="cannot exceed 10"):
        instance.execute_query("SELECT 1", row_limit=11)


def test_execute_query_returns_bounded_dictionary_rows(adapter):
    """Verify that execute query returns bounded dictionary rows; the test passes when the expected behavior is preserved."""
    instance, pool = adapter
    connection = MagicMock()
    cursor = MagicMock()
    cursor.description = [("id",), ("name",)]
    cursor.fetchall.return_value = [
        {"id": 1, "name": "A"},
        {"id": 2, "name": "B"},
        {"id": 3, "name": "C"},
    ]
    connection.cursor.return_value = cursor
    pool.get_connection.return_value = connection

    result = instance.execute_query(
        "SELECT id, name FROM customers WHERE id > %s",
        parameters=(0,),
        row_limit=2,
    )

    assert result.columns == ["id", "name"]
    assert result.rows == [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
    assert result.row_count == 2
    assert result.truncated is True
    connection.start_transaction.assert_called_once_with(readonly=True)
    cursor.execute.assert_called_once()
    sql, parameters = cursor.execute.call_args.args
    assert re.match(r"SELECT \* FROM \(SELECT id, name", sql)
    assert parameters == (0, 3)
    connection.rollback.assert_called()
    cursor.close.assert_called_once()
    connection.close.assert_called_once()


def test_connection_is_released_after_query_failure(adapter):
    """Verify that connection is released after query failure; the test passes when the expected behavior is preserved."""
    instance, pool = adapter
    connection = MagicMock()
    cursor = MagicMock()
    cursor.execute.side_effect = [
        None,
        mysql.connector.errors.OperationalError("private db connection details"),
    ]
    connection.cursor.return_value = cursor
    pool.get_connection.return_value = connection

    with pytest.raises(DatabaseQueryError):
        instance.execute_query(
            "SELECT customer_id FROM customers",
            row_limit=2,
            timeout_seconds=1,
        )

    connection.rollback.assert_called()
    cursor.close.assert_called_once()
    connection.close.assert_called_once()


def test_mysql_execution_timeout_is_reported(adapter):
    """Verify that mysql execution timeout is reported; the test passes when the expected behavior is preserved."""
    instance, pool = adapter
    connection = MagicMock()
    cursor = MagicMock()
    cursor.execute.side_effect = [
        None,
        mysql.connector.errors.DatabaseError(
            msg="server timeout",
            errno=3024,
        ),
    ]
    connection.cursor.return_value = cursor
    pool.get_connection.return_value = connection

    with pytest.raises(QueryTimeoutError, match="^Query timed out$"):
        instance.execute_query(
            "SELECT customer_id FROM customers",
            row_limit=2,
            timeout_seconds=1,
        )

    connection.rollback.assert_called()
    cursor.close.assert_called_once()
    connection.close.assert_called_once()


def test_health_check_returns_true(adapter):
    """Verify that health check returns true; the test passes when the expected behavior is preserved."""
    instance, pool = adapter
    connection = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)
    connection.cursor.return_value = cursor
    pool.get_connection.return_value = connection

    assert instance.health_check() is True
    cursor.execute.assert_called_once_with("SELECT 1")


def test_rejects_invalid_table_identifier_before_query(adapter):
    """Verify that rejects invalid table identifier before query; the test passes when the expected behavior is preserved."""
    instance, pool = adapter
    with pytest.raises(QueryValidationError, match="valid SQL identifier"):
        instance.get_table_schema("orders; DROP TABLE orders")
    pool.get_connection.assert_not_called()
