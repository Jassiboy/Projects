"""Combine database metadata with the business glossary into an LLM-safe schema catalog."""

from pathlib import Path
from typing import Any

import yaml

from .metadata_loader import CatalogLoadError, MetadataLoader
from .models import BusinessMetric, ColumnCatalogEntry, SchemaCatalog, TableCatalogEntry


DEFAULT_GLOSSARY_PATH = Path(__file__).with_name("business_glossary.yaml")
SENSITIVE_SAMPLE_COLUMNS = frozenset(
    {
        "customers.customer_name",
        "customers.email",
        "customers.city",
        "customers.state",
        "products.cost_price",
        "refunds.refund_reason",
    }
)


class CatalogService:
    """Build an enriched, deterministic catalog for prompts and validation."""
    def __init__(
        self,
        metadata_loader: MetadataLoader,
        glossary_path: Path = DEFAULT_GLOSSARY_PATH,
    ) -> None:
        """Initialize the CatalogService with its required collaborators and state."""
        self._metadata_loader = metadata_loader
        self._glossary_path = glossary_path

    def build_catalog(self, database: str) -> SchemaCatalog:
        """Build and return catalog."""
        catalog = self._metadata_loader.load(database)
        glossary = self._load_glossary()

        tables = tuple(
            TableCatalogEntry(
                name=table.name,
                description=self._description(
                    glossary.get("tables", {}).get(table.name, {}).get(
                        "description"
                    ),
                    "",
                ),
                columns=tuple(
                    self._enrich_column(
                        table.name,
                        column,
                        glossary.get("columns", {}).get(
                            f"{table.name}.{column.name}", {}
                        ),
                    )
                    for column in table.columns
                ),
            )
            for table in catalog.tables
        )
        metrics = tuple(
            BusinessMetric(
                name=name,
                description=self._required_glossary_text(value, "description"),
                formula=self._required_glossary_text(value, "formula"),
                caveat=self._required_glossary_text(value, "caveat"),
            )
            for name, value in sorted(
                glossary.get("metrics", {}).items(),
                key=lambda item: item[0].casefold(),
            )
        )
        return SchemaCatalog(
            database=catalog.database,
            tables=tables,
            relationships=catalog.relationships,
            business_metrics=metrics,
        )

    def to_prompt_json(self, database: str) -> str:
        """Perform to prompt json and return the resulting application value."""
        return self.build_catalog(database).to_json()

    def _load_glossary(self) -> dict[str, Any]:
        """Internal helper that performs load glossary and returns the normalized result."""
        try:
            with self._glossary_path.open("r", encoding="utf-8") as glossary_file:
                glossary = yaml.safe_load(glossary_file)
        except (OSError, yaml.YAMLError):
            raise CatalogLoadError("Could not load business glossary") from None
        if not isinstance(glossary, dict):
            raise CatalogLoadError("Business glossary must be a mapping")
        for section in ("tables", "columns", "metrics"):
            if not isinstance(glossary.get(section), dict):
                raise CatalogLoadError(f"Business glossary section '{section}' is invalid")
        return glossary

    @staticmethod
    def _enrich_column(
        table_name: str,
        column: ColumnCatalogEntry,
        glossary_entry: Any,
    ) -> ColumnCatalogEntry:
        """Internal helper that performs enrich column and returns the normalized result."""
        if not isinstance(glossary_entry, dict):
            glossary_entry = {}
        approved_values = glossary_entry.get("approved_sample_values", [])
        if not isinstance(approved_values, list) or not all(
            isinstance(value, str) for value in approved_values
        ):
            raise CatalogLoadError(
                f"Approved sample values for '{table_name}.{column.name}' are invalid"
            )
        if f"{table_name}.{column.name}" in SENSITIVE_SAMPLE_COLUMNS:
            approved_values = []
        return ColumnCatalogEntry(
            name=column.name,
            data_type=column.data_type,
            nullable=column.nullable,
            primary_key=column.primary_key,
            description=CatalogService._description(
                glossary_entry.get("description"),
                "",
            ),
            approved_sample_values=tuple(approved_values),
        )

    @staticmethod
    def _description(value: object, fallback: str) -> str:
        """Internal helper that performs description and returns the normalized result."""
        return value.strip() if isinstance(value, str) and value.strip() else fallback

    @staticmethod
    def _required_glossary_text(entry: Any, field: str) -> str:
        """Internal helper that performs required glossary text and returns the normalized result."""
        if not isinstance(entry, dict):
            raise CatalogLoadError(f"Business metric '{field}' is invalid")
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            raise CatalogLoadError(f"Business metric '{field}' is invalid")
        return value.strip()
