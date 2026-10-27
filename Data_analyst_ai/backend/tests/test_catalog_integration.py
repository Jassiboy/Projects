"""Verify catalog integration behavior with isolated unit or opt-in integration tests."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.catalog.catalog_service import CatalogService
from backend.app.catalog.metadata_loader import MetadataLoader
from backend.app.database.mysql import MySQLReadOnlyAdapter


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_MYSQL_INTEGRATION") != "1",
    reason="Set RUN_MYSQL_INTEGRATION=1 to run against the configured MySQL database",
)


def test_loads_llm_catalog_from_mysql_information_schema():
    """Verify that loads llm catalog from mysql information schema; the test passes when the expected behavior is preserved."""
    adapter = MySQLReadOnlyAdapter()
    try:
        service = CatalogService(MetadataLoader(adapter))
        catalog = service.build_catalog("analyst_ai")
        prompt_json = service.to_prompt_json("analyst_ai")
    finally:
        adapter.close()

    assert {table.name for table in catalog.tables} == {
        "categories",
        "customers",
        "order_items",
        "orders",
        "payments",
        "products",
        "refunds",
    }
    relationship_pairs = {
        (relationship.source_table, relationship.target_table)
        for relationship in catalog.relationships
    }
    assert relationship_pairs == {
        ("products", "categories"),
        ("orders", "customers"),
        ("order_items", "orders"),
        ("order_items", "products"),
        ("payments", "orders"),
        ("refunds", "orders"),
        ("refunds", "order_items"),
    }
    assert "password" not in prompt_json.casefold()
    assert "email@example.com" not in prompt_json.casefold()
