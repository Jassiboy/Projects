"""Run manual end-to-end checks against the configured read-only MySQL adapter."""

import sys
from pathlib import Path

import mysql.connector

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.config import DatabaseSettings
from backend.app.database.mysql import MySQLReadOnlyAdapter


EXPECTED_TABLES = {
    "categories",
    "customers",
    "order_items",
    "orders",
    "payments",
    "products",
    "refunds",
}


def main() -> int:
    """Run the script workflow and print its verification result for the operator."""
    adapter = MySQLReadOnlyAdapter()
    try:
        if adapter.health_check():
            print("PASS: health check")

        tables = adapter.list_tables()
        table_names = {table.name for table in tables}
        if not EXPECTED_TABLES.issubset(table_names):
            raise RuntimeError(
                "Expected tables missing: "
                + ", ".join(sorted(EXPECTED_TABLES - table_names))
            )
        print("PASS: seven expected tables listed")
        for table in tables:
            print(f"  {table.name} ({table.table_type})")

        orders_schema = adapter.get_table_schema("orders")
        print("PASS: orders schema")
        for column in orders_schema.columns:
            print(
                f"  {column.name}: {column.data_type}, "
                f"nullable={column.nullable}, key={column.key or '-'}"
            )

        result = adapter.execute_query(
            "SELECT order_id, order_date FROM orders ORDER BY order_id",
            row_limit=5,
        )
        if result.row_count > 5 or result.truncated and result.row_count != 5:
            raise RuntimeError("Bounded SELECT did not respect its row limit")
        print(
            f"PASS: bounded SELECT ({result.row_count} rows, "
            f"truncated={result.truncated})"
        )
        for row in result.rows:
            print(f"  {row}")
    finally:
        adapter.close()

    settings = DatabaseSettings()
    connection = mysql.connector.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
    )
    write_denied = False
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO customers (customer_name, signup_date)
                SELECT 'readonly_permission_probe', '2000-01-01'
                WHERE 1 = 0
                """
            )
        except mysql.connector.Error as error:
            if error.errno in {1142, 1143}:
                write_denied = True
                print("PASS: database user cannot INSERT (permission denied)")
            else:
                print(
                    "FAIL: INSERT probe failed for an unexpected reason "
                    f"(MySQL error {error.errno})"
                )
        else:
            connection.rollback()
        finally:
            cursor.close()
    finally:
        connection.close()

    if not write_denied:
        print(
            "FAIL: configured database user can INSERT or the probe did not "
            "reach a permission denial; use a read-only MySQL account"
        )
        return 1

    print("All five MySQL adapter checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
