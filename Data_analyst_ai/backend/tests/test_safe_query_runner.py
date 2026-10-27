"""Verify safe query runner behavior with isolated unit or opt-in integration tests."""

from unittest.mock import MagicMock

import pytest

from backend.app.database.base import DatabaseQueryError, QueryTimeoutError, QueryValidationError
from backend.app.database.models import QueryResult
from backend.app.database.safe_query_runner import SafeQueryRunner


@pytest.fixture
def adapter():
    """Perform adapter and return the resulting application value."""
    mock_adapter = MagicMock()
    mock_adapter.execute_query.return_value = QueryResult(
        columns=["value"],
        rows=[{"value": 1}],
        row_count=1,
        execution_time=0.01,
        truncated=False,
        executed_sql="SELECT 1 LIMIT 101",
    )
    return mock_adapter


def test_valid_select_executes_normalized_sql_and_returns_structured_result(adapter):
    """Verify that valid select executes normalized sql and returns structured result; the test passes when the expected behavior is preserved."""
    runner = SafeQueryRunner(adapter)

    result = runner.run("SELECT 1 AS value")

    assert result.executed_sql == "SELECT 1 LIMIT 101"
    assert result.columns == ["value"]
    assert result.rows == [{"value": 1}]
    assert result.row_count == 1
    assert result.truncated is False
    assert result.execution_time >= 0.01
    adapter.execute_query.assert_called_once()
    sql = adapter.execute_query.call_args.args[0]
    assert sql == "SELECT 1 AS value LIMIT 100"
    assert adapter.execute_query.call_args.kwargs == {
        "row_limit": 100,
        "timeout_seconds": 5.0,
    }


def test_invalid_query_never_reaches_adapter(adapter):
    """Verify that invalid query never reaches adapter; the test passes when the expected behavior is preserved."""
    runner = SafeQueryRunner(adapter)

    with pytest.raises(QueryValidationError):
        runner.run("SELECT * FROM private_table")

    adapter.execute_query.assert_not_called()


def test_write_query_stays_blocked_end_to_end(adapter):
    """Verify that write query stays blocked end to end; the test passes when the expected behavior is preserved."""
    runner = SafeQueryRunner(adapter)

    with pytest.raises(QueryValidationError):
        runner.run("WITH changed AS (DELETE FROM customers) SELECT 1")

    adapter.execute_query.assert_not_called()


def test_default_limit_is_applied(adapter):
    """Verify that default limit is applied; the test passes when the expected behavior is preserved."""
    SafeQueryRunner(adapter).run("SELECT 1")

    assert adapter.execute_query.call_args.args[0].endswith("LIMIT 100")
    assert adapter.execute_query.call_args.kwargs["row_limit"] == 100


def test_smaller_user_limit_is_preserved(adapter):
    """Verify that smaller user limit is preserved; the test passes when the expected behavior is preserved."""
    SafeQueryRunner(adapter).run("SELECT 1", row_limit=25)

    assert adapter.execute_query.call_args.args[0].endswith("LIMIT 25")
    assert adapter.execute_query.call_args.kwargs["row_limit"] == 25


def test_excessive_limit_is_restricted(adapter):
    """Verify that excessive limit is restricted; the test passes when the expected behavior is preserved."""
    SafeQueryRunner(adapter).run("SELECT 1", row_limit=50000)

    assert adapter.execute_query.call_args.args[0].endswith("LIMIT 1000")
    assert adapter.execute_query.call_args.kwargs["row_limit"] == 1000


def test_truncation_is_returned(adapter):
    """Verify that truncation is returned; the test passes when the expected behavior is preserved."""
    adapter.execute_query.return_value = QueryResult(
        columns=["value"],
        rows=[{"value": 1}, {"value": 2}],
        row_count=2,
        execution_time=0.01,
        truncated=True,
    )

    result = SafeQueryRunner(adapter).run("SELECT 1", row_limit=2)

    assert result.truncated is True
    assert result.row_count == 2


def test_query_timeout_is_reported_without_database_details(adapter):
    """Verify that query timeout is reported without database details; the test passes when the expected behavior is preserved."""
    adapter.execute_query.side_effect = QueryTimeoutError(
        "Internal server message containing private host details"
    )

    with pytest.raises(QueryTimeoutError, match="^Query timed out$") as error:
        SafeQueryRunner(adapter).run("SELECT 1")

    assert error.value.__cause__ is None


def test_database_error_is_sanitized(adapter):
    """Verify that database error is sanitized; the test passes when the expected behavior is preserved."""
    adapter.execute_query.side_effect = DatabaseQueryError(
        "connection password=secret at db.internal.example failed"
    )

    with pytest.raises(DatabaseQueryError, match="^Query execution failed$") as error:
        SafeQueryRunner(adapter).run("SELECT 1")

    assert "secret" not in str(error.value)
    assert error.value.__cause__ is None


def test_adapter_unexpected_error_is_sanitized(adapter):
    """Verify that adapter unexpected error is sanitized; the test passes when the expected behavior is preserved."""
    adapter.execute_query.side_effect = RuntimeError(
        "connection password=secret at db.internal.example failed"
    )

    with pytest.raises(DatabaseQueryError, match="^Query execution failed$") as error:
        SafeQueryRunner(adapter).run("SELECT 1")

    assert "secret" not in str(error.value)


def test_rejects_invalid_timeout_configuration(adapter):
    """Verify that rejects invalid timeout configuration; the test passes when the expected behavior is preserved."""
    for timeout in (0, -1, float("inf"), float("nan"), True):
        with pytest.raises(ValueError):
            SafeQueryRunner(adapter, timeout_seconds=timeout)
