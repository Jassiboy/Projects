"""Verify sql validator behavior with isolated unit or opt-in integration tests."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.database.sql_validator import SQLValidator


@pytest.fixture
def validator():
    """Perform validator and return the resulting application value."""
    return SQLValidator()


@pytest.mark.parametrize(
    ("sql", "tables"),
    [
        ("SELECT customer_id FROM customers", ("customers",)),
        (
            """
            SELECT c.region, COUNT(*) AS order_count
            FROM customers AS c
            JOIN orders AS o ON o.customer_id = c.customer_id
            GROUP BY c.region
            """,
            ("customers", "orders"),
        ),
        (
            """
            WITH yearly_orders AS (
                SELECT YEAR(order_date) AS order_year, COUNT(*) AS total
                FROM orders
                GROUP BY YEAR(order_date)
            )
            SELECT order_year, total FROM yearly_orders
            UNION
            SELECT 2020, 0
            """,
            ("orders",),
        ),
    ],
)
def test_accepts_read_queries_and_applies_default_limit(validator, sql, tables):
    """Verify that accepts read queries and applies default limit; the test passes when the expected behavior is preserved."""
    result = validator.validate(sql)

    assert result.is_valid is True
    assert result.normalized_sql is not None
    assert result.normalized_sql.endswith("LIMIT 100")
    assert result.referenced_tables == tables
    assert result.rejection_reason is None


def test_rejects_multiple_statements(validator):
    """Verify that rejects multiple statements; the test passes when the expected behavior is preserved."""
    result = validator.validate("SELECT 1; DELETE FROM customers")

    assert result.is_valid is False
    assert result.rejection_reason == "Exactly one SQL statement is allowed"


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO customers (customer_id) VALUES (1)",
        "UPDATE customers SET customer_name = 'x'",
        "DELETE FROM customers",
        "DROP TABLE customers",
        "ALTER TABLE customers ADD COLUMN extra INT",
        "CREATE TABLE scratch (id INT)",
        "TRUNCATE TABLE customers",
        "CALL refresh_data()",
        "USE analyst_ai",
    ],
)
def test_rejects_write_and_ddl_statements(validator, sql):
    """Verify that rejects write and ddl statements; the test passes when the expected behavior is preserved."""
    result = validator.validate(sql)

    assert result.is_valid is False
    assert result.normalized_sql is None
    assert result.rejection_reason


def test_rejects_nested_write_statement(validator):
    """Verify that rejects nested write statement; the test passes when the expected behavior is preserved."""
    result = validator.validate(
        "WITH changed AS (DELETE FROM customers RETURNING customer_id) "
        "SELECT customer_id FROM changed"
    )

    assert result.is_valid is False
    assert result.rejection_reason


@pytest.mark.parametrize(
    "schema",
    ["mysql", "sys", "information_schema", "performance_schema"],
)
def test_rejects_system_schema_access(validator, schema):
    """Verify that rejects system schema access; the test passes when the expected behavior is preserved."""
    result = validator.validate(f"SELECT * FROM {schema}.user")

    assert result.is_valid is False
    assert result.rejection_reason
    assert schema in result.rejection_reason


def test_rejects_tables_outside_approved_schema_or_table_list(validator):
    """Verify that rejects tables outside approved schema or table list; the test passes when the expected behavior is preserved."""
    for sql in (
        "SELECT * FROM other_db.customers",
        "SELECT * FROM server.analyst_ai.customers",
        "SELECT * FROM analyst_ai.audit_log",
    ):
        result = validator.validate(sql)
        assert result.is_valid is False
        assert result.rejection_reason


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))


def test_cte_alias_does_not_hide_qualified_physical_table(validator):
    """Verify that cte alias does not hide qualified physical table; the test passes when the expected behavior is preserved."""
    for sql in (
        "WITH customers AS (SELECT * FROM information_schema.tables) "
        "SELECT * FROM customers",
        "WITH audit_log AS (SELECT * FROM audit_log) "
        "SELECT * FROM audit_log",
    ):
        result = validator.validate(sql)

        assert result.is_valid is False
        assert result.rejection_reason


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SLEEP(1)",
        "SELECT BENCHMARK(1000000, MD5('x'))",
        "SELECT LOAD_FILE('/etc/passwd')",
    ],
)
def test_rejects_risky_functions(validator, sql):
    """Verify that rejects risky functions; the test passes when the expected behavior is preserved."""
    result = validator.validate(sql)

    assert result.is_valid is False
    assert result.rejection_reason == "Risky SQL functions are not allowed"


def test_caps_excessive_sql_limit_and_requested_row_limit(validator):
    """Verify that caps excessive sql limit and requested row limit; the test passes when the expected behavior is preserved."""
    sql_limit = validator.validate("SELECT * FROM orders LIMIT 50000")
    requested_limit = validator.validate("SELECT * FROM orders", row_limit=50000)

    assert sql_limit.is_valid is True
    assert sql_limit.normalized_sql.endswith("LIMIT 100")
    assert requested_limit.is_valid is True
    assert requested_limit.normalized_sql.endswith("LIMIT 1000")


def test_preserves_a_smaller_existing_limit(validator):
    """Verify that preserves a smaller existing limit; the test passes when the expected behavior is preserved."""
    result = validator.validate("SELECT * FROM orders LIMIT 20", row_limit=50)

    assert result.is_valid is True
    assert result.normalized_sql.endswith("LIMIT 20")


def test_rejects_invalid_requested_limit(validator):
    """Verify that rejects invalid requested limit; the test passes when the expected behavior is preserved."""
    for row_limit in (0, -1, 1.5, True):
        result = validator.validate("SELECT 1", row_limit=row_limit)
        assert result.is_valid is False
        assert result.rejection_reason == "row_limit must be a positive integer"


def test_rejects_select_into_and_locking_queries(validator):
    """Verify that rejects select into and locking queries; the test passes when the expected behavior is preserved."""
    for sql in (
        "SELECT * FROM customers INTO OUTFILE '/tmp/customers.csv'",
        "SELECT * FROM customers INTO DUMPFILE '/tmp/customer.bin'",
        "SELECT * FROM customers FOR UPDATE",
    ):
        result = validator.validate(sql)
        assert result.is_valid is False
        assert result.rejection_reason
