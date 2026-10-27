"""Define immutable schema-catalog and business-metric value objects."""

from dataclasses import asdict, dataclass
import json
from typing import Any


@dataclass(frozen=True)
class ColumnCatalogEntry:
    """Represent ColumnCatalogEntry data or behavior used by the application."""
    name: str
    data_type: str
    nullable: bool
    primary_key: bool
    description: str
    approved_sample_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableCatalogEntry:
    """Represent TableCatalogEntry data or behavior used by the application."""
    name: str
    description: str
    columns: tuple[ColumnCatalogEntry, ...]


@dataclass(frozen=True)
class TableRelationship:
    """Represent TableRelationship data or behavior used by the application."""
    name: str
    source_table: str
    source_columns: tuple[str, ...]
    target_table: str
    target_columns: tuple[str, ...]


@dataclass(frozen=True)
class BusinessMetric:
    """Represent BusinessMetric data or behavior used by the application."""
    name: str
    description: str
    formula: str
    caveat: str


@dataclass(frozen=True)
class SchemaCatalog:
    """Represent SchemaCatalog data or behavior used by the application."""
    database: str
    tables: tuple[TableCatalogEntry, ...]
    relationships: tuple[TableRelationship, ...]
    business_metrics: tuple[BusinessMetric, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return the catalog as a serializable dictionary."""
        return asdict(self)

    def to_json(self) -> str:
        """Return a compact deterministic JSON representation of the catalog."""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
