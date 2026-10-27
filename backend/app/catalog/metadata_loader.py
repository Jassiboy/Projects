"""Convert raw database metadata into typed tables, columns, and relationships."""

from collections.abc import Mapping
from typing import Any, Protocol

from backend.app.database.base import DatabaseError

from .models import (
    ColumnCatalogEntry,
    SchemaCatalog,
    TableCatalogEntry,
    TableRelationship,
)


class CatalogMetadataSource(Protocol):
    """Protocol for adapters that can return raw catalog metadata."""
    def load_catalog_metadata(
        self,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """Load and return raw table, column, and relationship metadata."""

        ...


class CatalogLoadError(RuntimeError):
    """Raised when catalog metadata cannot be safely loaded."""


class MetadataLoader:
    """Load raw schema metadata and convert it into typed catalog entries."""
    def __init__(self, metadata_source: CatalogMetadataSource) -> None:
        """Initialize the MetadataLoader with its required collaborators and state."""
        self._metadata_source = metadata_source

    def load(self, database: str) -> SchemaCatalog:
        """Load and return load."""
        try:
            table_rows, column_rows, relationship_rows = (
                self._metadata_source.load_catalog_metadata()
            )
        except DatabaseError:
            raise CatalogLoadError("Could not load database schema metadata") from None

        tables_by_name: dict[str, dict[str, Any]] = {}
        for row in table_rows:
            name = self._required_text(row, "table_name")
            tables_by_name[name] = {
                "description": self._text(row.get("description")),
                "columns": [],
            }

        for row in column_rows:
            table_name = self._required_text(row, "table_name")
            table = tables_by_name.get(table_name)
            if table is None:
                continue
            table["columns"].append(
                ColumnCatalogEntry(
                    name=self._required_text(row, "column_name"),
                    data_type=self._required_text(row, "data_type"),
                    nullable=self._text(row.get("nullable")).upper() == "YES",
                    primary_key=self._text(row.get("column_key")).upper() == "PRI",
                    description=self._text(row.get("description")),
                )
            )

        relationships = self._relationships(relationship_rows, tables_by_name)
        tables = tuple(
            TableCatalogEntry(
                name=name,
                description=table["description"],
                columns=tuple(
                    sorted(table["columns"], key=lambda column: column.name.casefold())
                ),
            )
            for name, table in sorted(
                tables_by_name.items(), key=lambda item: item[0].casefold()
            )
        )

        return SchemaCatalog(
            database=database,
            tables=tables,
            relationships=relationships,
            business_metrics=(),
        )

    @staticmethod
    def _relationships(
        rows: list[dict[str, Any]],
        tables_by_name: Mapping[str, object],
    ) -> tuple[TableRelationship, ...]:
        """Internal helper that performs relationships and returns the normalized result."""
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            source_table = MetadataLoader._required_text(row, "source_table")
            target_table = MetadataLoader._required_text(row, "target_table")
            if source_table not in tables_by_name or target_table not in tables_by_name:
                continue
            constraint_name = MetadataLoader._required_text(row, "constraint_name")
            group_key = f"{source_table}.{constraint_name}"
            relationship = grouped.setdefault(
                group_key,
                {
                    "name": constraint_name,
                    "source_table": source_table,
                    "target_table": target_table,
                    "columns": [],
                },
            )
            relationship["columns"].append(
                (
                    int(row.get("ordinal_position", 1)),
                    MetadataLoader._required_text(row, "source_column"),
                    MetadataLoader._required_text(row, "target_column"),
                )
            )

        return tuple(
            TableRelationship(
                name=relationship["name"],
                source_table=relationship["source_table"],
                source_columns=tuple(
                    source_column
                    for _, source_column, _ in sorted(relationship["columns"])
                ),
                target_table=relationship["target_table"],
                target_columns=tuple(
                    target_column
                    for _, _, target_column in sorted(relationship["columns"])
                ),
            )
            for _, relationship in sorted(
                grouped.items(), key=lambda item: item[0].casefold()
            )
        )

    @staticmethod
    def _required_text(row: Mapping[str, Any], key: str) -> str:
        """Internal helper that performs required text and returns the normalized result."""
        value = row.get(key)
        if not isinstance(value, str) or not value:
            raise CatalogLoadError(f"Invalid schema metadata field: {key}")
        return value

    @staticmethod
    def _text(value: object) -> str:
        """Internal helper that performs text and returns the normalized result."""
        return value if isinstance(value, str) else ""
