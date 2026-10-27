"""Verify catalog behavior with isolated unit or opt-in integration tests."""

import json

import pytest

from backend.app.catalog.catalog_service import CatalogService
from backend.app.catalog.metadata_loader import (
    CatalogLoadError,
    MetadataLoader,
)
from backend.app.database.base import DatabaseQueryError


class FakeMetadataSource:
    """Test double used to provide deterministic FakeMetadataSource behavior."""
    def load_catalog_metadata(self):
        """Load and return catalog metadata."""
        tables = [
            {"table_name": name, "description": "password=hunter2"}
            for name in (
                "categories",
                "customers",
                "order_items",
                "orders",
                "payments",
                "products",
                "refunds",
            )
        ]
        columns = [
            {
                "table_name": "customers",
                "column_name": "customer_id",
                "data_type": "bigint",
                "nullable": "NO",
                "column_key": "PRI",
                "description": "token=private",
            },
            {
                "table_name": "customers",
                "column_name": "email",
                "data_type": "varchar(255)",
                "nullable": "YES",
                "column_key": "",
                "description": "customer@example.com",
            },
            {
                "table_name": "customers",
                "column_name": "region",
                "data_type": "varchar(50)",
                "nullable": "YES",
                "column_key": "",
                "description": "",
            },
            {
                "table_name": "orders",
                "column_name": "customer_id",
                "data_type": "bigint",
                "nullable": "NO",
                "column_key": "",
                "description": "",
            },
        ]
        relationships = [
            {
                "source_table": "orders",
                "source_column": "customer_id",
                "constraint_name": "orders_ibfk_1",
                "target_table": "customers",
                "target_column": "customer_id",
                "ordinal_position": 1,
            }
        ]
        return tables, columns, relationships


def build_service():
    """Build and return service."""
    return CatalogService(MetadataLoader(FakeMetadataSource()))


def test_detects_all_seven_tables_and_foreign_key():
    """Verify that detects all seven tables and foreign key; the test passes when the expected behavior is preserved."""
    catalog = build_service().build_catalog("analyst_ai")

    assert [table.name for table in catalog.tables] == [
        "categories",
        "customers",
        "order_items",
        "orders",
        "payments",
        "products",
        "refunds",
    ]
    assert len(catalog.relationships) == 1
    relationship = catalog.relationships[0]
    assert relationship.source_table == "orders"
    assert relationship.source_columns == ("customer_id",)
    assert relationship.target_table == "customers"
    assert relationship.target_columns == ("customer_id",)


def test_catalog_metadata_includes_types_nullability_and_primary_keys():
    """Verify that catalog metadata includes types nullability and primary keys; the test passes when the expected behavior is preserved."""
    catalog = build_service().build_catalog("analyst_ai")
    columns = {
        (table.name, column.name): column
        for table in catalog.tables
        for column in table.columns
    }

    assert columns[("customers", "customer_id")].data_type == "bigint"
    assert columns[("customers", "customer_id")].nullable is False
    assert columns[("customers", "customer_id")].primary_key is True
    assert columns[("customers", "email")].nullable is True
    assert columns[("customers", "email")].description


def test_prompt_json_is_compact_deterministic_and_omits_sensitive_values():
    """Verify that prompt json is compact deterministic and omits sensitive values; the test passes when the expected behavior is preserved."""
    service = build_service()
    json_one = service.to_prompt_json("analyst_ai")
    json_two = service.to_prompt_json("analyst_ai")
    catalog_data = json.loads(json_one)

    assert json_one == json_two
    assert "\n" not in json_one
    assert "password=hunter2" not in json_one
    assert "token=private" not in json_one
    assert "customer@example.com" not in json_one
    assert catalog_data["database"] == "analyst_ai"

    columns = {
        (table["name"], column["name"]): column
        for table in catalog_data["tables"]
        for column in table["columns"]
    }
    assert columns[("customers", "email")]["approved_sample_values"] == []
    assert columns[("customers", "region")]["approved_sample_values"] == [
        "Northeast",
        "Southeast",
        "Midwest",
        "Southwest",
        "West",
    ]
    assert {metric["name"] for metric in catalog_data["business_metrics"]} == {
        "net_revenue",
        "refund_rate",
    }


def test_metadata_database_error_is_sanitized():
    """Verify that metadata database error is sanitized; the test passes when the expected behavior is preserved."""
    class FailingMetadataSource:
        """Represent FailingMetadataSource data or behavior used by the application."""
        def load_catalog_metadata(self):
            """Load and return catalog metadata."""
            raise DatabaseQueryError("password=secret host=private-db")

    loader = MetadataLoader(FailingMetadataSource())

    with pytest.raises(CatalogLoadError) as error:
        loader.load("analyst_ai")

    assert str(error.value) == "Could not load database schema metadata"
    assert "secret" not in str(error.value)
    assert error.value.__cause__ is None


def test_sensitive_columns_never_emit_samples_even_if_glossary_lists_them(tmp_path):
    """Verify that sensitive columns never emit samples even if glossary lists them; the test passes when the expected behavior is preserved."""
    glossary_path = tmp_path / "business_glossary.yaml"
    glossary_path.write_text(
        """
tables: {}
columns:
  customers.email:
    approved_sample_values: [person@example.com]
metrics:
  {}
""",
        encoding="utf-8",
    )
    service = CatalogService(
        MetadataLoader(FakeMetadataSource()),
        glossary_path=glossary_path,
    )

    catalog_json = service.to_prompt_json("analyst_ai")

    assert "person@example.com" not in catalog_json
