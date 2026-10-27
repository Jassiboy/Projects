"""Parse MySQL SQL and enforce the application's read-only query policy."""

from dataclasses import dataclass
from uuid import uuid4

from sqlglot import exp, parse
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import Scope, traverse_scope


APPROVED_TABLES = frozenset(
    {
        "categories",
        "customers",
        "order_items",
        "orders",
        "payments",
        "products",
        "refunds",
    }
)
DEFAULT_ROW_LIMIT = 100
MAXIMUM_ROW_LIMIT = 1000
BLOCKED_SCHEMAS = frozenset(
    {"mysql", "sys", "information_schema", "performance_schema"}
)
RISKY_FUNCTIONS = frozenset({"sleep", "benchmark", "load_file"})
BLOCKED_STATEMENTS = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.TruncateTable,
    exp.Command,
    exp.Use,
)


def parse_mysql_sql(sql: str) -> tuple[list[exp.Expression], str]:
    """Parse MySQL text and return statements plus the placeholder representation used."""
    placeholder_marker = f"__safequery_{uuid4().hex}"
    parser_sql = sql.replace("%s", f":{placeholder_marker}")
    return (
        [statement for statement in parse(parser_sql, read="mysql") if statement],
        placeholder_marker,
    )


def render_mysql_sql(statement: exp.Expression, placeholder_marker: str) -> str:
    """Render a parsed SQL expression back to normalized MySQL text."""
    return statement.sql(dialect="mysql", pretty=False).replace(
        f":{placeholder_marker}",
        "%s",
    )


@dataclass(frozen=True)
class SQLValidationResult:
    """Represent SQLValidationResult data or behavior used by the application."""
    is_valid: bool
    normalized_sql: str | None
    referenced_tables: tuple[str, ...]
    rejection_reason: str | None


class SQLValidator:
    """Enforce single-statement, read-only, approved-schema SQL rules."""
    def validate(
        self,
        sql: str,
        row_limit: int | None = None,
    ) -> SQLValidationResult:
        """Validate validate and return the policy result."""
        if not isinstance(sql, str) or not sql.strip():
            return self._rejected("SQL query must not be empty")

        try:
            statements, placeholder_marker = parse_mysql_sql(sql)
        except ParseError as error:
            return self._rejected(f"SQL could not be parsed: {error}")

        if len(statements) != 1:
            return self._rejected("Exactly one SQL statement is allowed")

        statement = statements[0]
        cte_references = self._cte_references(statement)
        referenced_tables = self._referenced_tables(statement, cte_references)

        if not isinstance(statement, (exp.Select, exp.Union)):
            return self._rejected(
                "Only SELECT, WITH...SELECT, and UNION queries are allowed",
                referenced_tables,
            )

        if any(statement.find_all(BLOCKED_STATEMENTS)):
            return self._rejected(
                "Write and DDL operations are not allowed",
                referenced_tables,
            )

        if any(statement.find_all(exp.Into)):
            return self._rejected(
                "SELECT INTO is not allowed",
                referenced_tables,
            )

        if any(statement.find_all(exp.Lock)):
            return self._rejected(
                "Locking SELECT queries are not allowed",
                referenced_tables,
            )

        if self._contains_risky_function(statement):
            return self._rejected(
                "Risky SQL functions are not allowed",
                referenced_tables,
            )

        table_error = self._table_rejection_reason(statement, cte_references)
        if table_error is not None:
            return self._rejected(table_error, referenced_tables)

        effective_limit = self._effective_limit(row_limit)
        if effective_limit is None:
            return self._rejected(
                "row_limit must be a positive integer",
                referenced_tables,
            )

        self._apply_row_limit(statement, effective_limit)
        return SQLValidationResult(
            is_valid=True,
            normalized_sql=render_mysql_sql(statement, placeholder_marker),
            referenced_tables=referenced_tables,
            rejection_reason=None,
        )

    def _effective_limit(self, row_limit: int | None) -> int | None:
        """Internal helper that performs effective limit and returns the normalized result."""
        if row_limit is None:
            return DEFAULT_ROW_LIMIT
        if isinstance(row_limit, bool) or not isinstance(row_limit, int):
            return None
        if row_limit < 1:
            return None
        return min(row_limit, MAXIMUM_ROW_LIMIT)

    @staticmethod
    def _cte_references(statement: exp.Expression) -> set[int]:
        """Internal helper that performs cte references and returns the normalized result."""
        return {
            id(node)
            for scope in traverse_scope(statement)
            for node, source in scope.selected_sources.values()
            if isinstance(node, exp.Table) and isinstance(source, Scope)
        }

    @staticmethod
    def _referenced_tables(
        statement: exp.Expression,
        cte_references: set[int],
    ) -> tuple[str, ...]:
        """Internal helper that performs referenced tables and returns the normalized result."""
        table_names: set[str] = set()
        for table in statement.find_all(exp.Table):
            if id(table) in cte_references:
                continue
            qualifiers = [part for part in (table.catalog, table.db) if part]
            table_names.add(".".join((*qualifiers, table.name)))
        return tuple(sorted(table_names, key=str.casefold))

    def _table_rejection_reason(
        self,
        statement: exp.Expression,
        cte_references: set[int],
    ) -> str | None:
        """Internal helper that performs table rejection reason and returns the normalized result."""
        for table in statement.find_all(exp.Table):
            if id(table) in cte_references:
                continue
            if table.catalog:
                return "Catalog-qualified table references are not allowed"
            schema = table.db or table.catalog
            if schema:
                normalized_schema = schema.casefold()
                if normalized_schema in BLOCKED_SCHEMAS:
                    return f"Access to system schema '{schema}' is not allowed"
                if normalized_schema != "analyst_ai":
                    return "Only tables in schema 'analyst_ai' are allowed"
            if table.name.casefold() not in APPROVED_TABLES:
                return f"Table '{table.name}' is not approved"
        return None

    @staticmethod
    def _contains_risky_function(statement: exp.Expression) -> bool:
        """Return whether risky function satisfies the required condition."""
        for function in statement.find_all(exp.Func):
            function_names = {function.sql_name().casefold()}
            if isinstance(function, exp.Anonymous):
                function_names.add(function.name.casefold())
            if function_names & RISKY_FUNCTIONS:
                return True
        return False

    @staticmethod
    def _apply_row_limit(statement: exp.Expression, row_limit: int) -> None:
        """Internal helper that performs apply row limit and returns the normalized result."""
        current_limit = statement.args.get("limit")
        if current_limit is None:
            statement.limit(row_limit, copy=False)
            return

        limit_expression = current_limit.expression
        if isinstance(limit_expression, exp.Literal) and not limit_expression.is_string:
            try:
                if int(limit_expression.this) <= row_limit:
                    return
            except ValueError:
                pass
        statement.set(
            "limit",
            exp.Limit(expression=exp.Literal.number(row_limit)),
        )

    @staticmethod
    def _rejected(
        reason: str,
        referenced_tables: tuple[str, ...] = (),
    ) -> SQLValidationResult:
        """Internal helper that performs rejected and returns the normalized result."""
        return SQLValidationResult(
            is_valid=False,
            normalized_sql=None,
            referenced_tables=referenced_tables,
            rejection_reason=reason,
        )
