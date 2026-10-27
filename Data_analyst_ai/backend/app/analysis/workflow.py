"""Orchestrate planning, validation, execution, repair, grounding, and response construction."""

from dataclasses import dataclass

from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import Scope, traverse_scope

from backend.app.catalog.models import SchemaCatalog
from backend.app.database.base import DatabaseError, QueryValidationError
from backend.app.database.safe_query_runner import SafeQueryResult, SafeQueryRunner
from backend.app.database.sql_validator import SQLValidator, parse_mysql_sql
from backend.app.llm.base import LLMRateLimitError, LLMTimeoutError

from .answer_builder import AnswerBuilder
from .chart_policy import ChartPolicy
from .models import (
    AnalysisResponse,
    AnalysisResult,
    ExecutionMetadata,
    SQLPlan,
)
from .planner import AnalysisPlanner


class AnalysisWorkflowError(RuntimeError):
    """A sanitized failure while producing an analysis response."""


class AnalysisWorkflowTimeoutError(AnalysisWorkflowError):
    """An upstream analysis dependency exceeded its timeout."""


class AnalysisWorkflowRateLimitError(AnalysisWorkflowError):
    """An upstream analysis provider rate limit was reached."""


@dataclass(frozen=True)
class PlanValidation:
    """Represent PlanValidation data or behavior used by the application."""
    normalized_sql: str | None
    rejection_reason: str | None


class AnalysisWorkflow:
    """Coordinate the complete question-to-verified-analysis lifecycle."""
    def __init__(
        self,
        planner: AnalysisPlanner,
        validator: SQLValidator,
        query_runner: SafeQueryRunner,
        answer_builder: AnswerBuilder,
        chart_policy: ChartPolicy | None = None,
        row_limit: int = 100,
    ) -> None:
        """Initialize the AnalysisWorkflow with its required collaborators and state."""
        if row_limit < 1:
            raise ValueError("row_limit must be greater than zero")
        self._planner = planner
        self._validator = validator
        self._query_runner = query_runner
        self._answer_builder = answer_builder
        self._chart_policy = chart_policy or ChartPolicy()
        self._row_limit = row_limit

    def analyze(
        self,
        question: str,
        catalog: SchemaCatalog,
        business_glossary: str = "",
    ) -> AnalysisResponse:
        """Process a natural-language question and return a validated analysis response."""
        schema_json = catalog.to_json()
        try:
            plan = self._planner.plan(question, schema_json, business_glossary)
        except LLMTimeoutError:
            raise AnalysisWorkflowTimeoutError(
                "The analysis provider timed out. Please try again."
            ) from None
        except LLMRateLimitError:
            raise AnalysisWorkflowRateLimitError(
                "The analysis provider is temporarily rate limited."
            ) from None
        except Exception:
            raise AnalysisWorkflowError(
                "Analysis could not be planned. Please try again."
            ) from None
        if not isinstance(plan, SQLPlan):
            raise AnalysisWorkflowError(
                "Analysis could not be planned. Please try again."
            )

        if plan.clarification_question:
            return self._clarification_response(plan)
        if plan.direct_answer is not None and not plan.sql.strip():
            return AnalysisResponse(
                answer=plan.direct_answer,
                assumptions=list(plan.assumptions),
            )
        return self._execute_plan(
            question,
            catalog,
            plan,
            schema_json,
            business_glossary,
            allow_repair=True,
        )

    def rerun_with_sql(
        self,
        question: str,
        catalog: SchemaCatalog,
        edited_sql: str,
        assumptions: list[str] | None = None,
    ) -> AnalysisResponse:
        """Perform rerun with sql and return the resulting application value."""
        validation_result = self._validator.validate(
            edited_sql,
            row_limit=self._row_limit,
        )
        if not validation_result.is_valid:
            return self._rejected_response(
                assumptions or [],
                "Edited SQL was rejected by the read-only validator.",
            )
        referenced_tables = tuple(
            table.rsplit(".", 1)[-1]
            for table in validation_result.referenced_tables
        )
        plan = SQLPlan(
            intent=question[:500] or "User-edited query",
            relevant_tables=list(referenced_tables),
            sql=edited_sql,
            assumptions=assumptions or [],
        )
        validation = self._validate_plan(plan, catalog)
        if validation.rejection_reason:
            return self._rejected_response(
                plan.assumptions,
                validation.rejection_reason,
            )
        return self._execute_validated_plan(
            question,
            plan,
            validation.normalized_sql or "",
        )

    def _execute_plan(
        self,
        question: str,
        catalog: SchemaCatalog,
        plan: SQLPlan,
        schema_json: str,
        business_glossary: str,
        allow_repair: bool,
    ) -> AnalysisResponse:
        """Execute plan and return its bounded result."""
        validation = self._validate_plan(plan, catalog)
        if validation.rejection_reason:
            return self._rejected_response(plan.assumptions, validation.rejection_reason)

        try:
            return self._execute_validated_plan(
                question,
                plan,
                validation.normalized_sql or "",
            )
        except (DatabaseError, QueryValidationError):
            if not allow_repair:
                return self._rejected_response(
                    plan.assumptions,
                    "Query could not be safely executed.",
                )

        try:
            repaired_plan = self._planner.repair(
                question,
                schema_json,
                plan,
                "The read-only query execution failed.",
                business_glossary,
            )
        except LLMTimeoutError:
            raise AnalysisWorkflowTimeoutError(
                "The analysis provider timed out. Please try again."
            ) from None
        except LLMRateLimitError:
            raise AnalysisWorkflowRateLimitError(
                "The analysis provider is temporarily rate limited."
            ) from None
        except Exception:
            return self._rejected_response(
                plan.assumptions,
                "The query failed and could not be safely repaired.",
            )
        if not isinstance(repaired_plan, SQLPlan):
            return self._rejected_response(
                plan.assumptions,
                "The query failed and could not be safely repaired.",
            )
        if repaired_plan.clarification_question:
            return self._clarification_response(repaired_plan)

        repaired_validation = self._validate_plan(repaired_plan, catalog)
        if repaired_validation.rejection_reason:
            return self._rejected_response(
                repaired_plan.assumptions,
                repaired_validation.rejection_reason,
                attempts=2,
            )
        try:
            return self._execute_validated_plan(
                question,
                repaired_plan,
                repaired_validation.normalized_sql or "",
                attempts=2,
            )
        except (DatabaseError, QueryValidationError):
            return self._rejected_response(
                repaired_plan.assumptions,
                "Query could not be safely executed after one repair attempt.",
                attempts=2,
            )

    def _execute_validated_plan(
        self,
        question: str,
        plan: SQLPlan,
        validated_sql: str,
        attempts: int = 1,
    ) -> AnalysisResponse:
        """Execute validated plan and return its bounded result."""
        query_result = self._query_runner.run(
            validated_sql,
            row_limit=self._row_limit,
        )
        chart_spec = self._chart_policy.build_spec(
            plan,
            query_result.columns,
            query_result.rows,
        )
        try:
            answer_result = self._answer_builder.build(
                question,
                plan,
                query_result.executed_sql,
                query_result.rows,
                chart_spec,
            )
        except LLMTimeoutError:
            raise AnalysisWorkflowTimeoutError(
                "The analysis provider timed out. Please try again."
            ) from None
        except LLMRateLimitError:
            raise AnalysisWorkflowRateLimitError(
                "The analysis provider is temporarily rate limited."
            ) from None
        except Exception:
            raise AnalysisWorkflowError(
                "The query completed, but its result could not be summarized safely."
            ) from None

        warnings = list(dict.fromkeys((*answer_result.warnings, *plan.assumptions)))
        if query_result.truncated:
            warnings.append("The query result was truncated to the requested row limit.")
        return self._response_from_result(
            answer_result,
            query_result,
            warnings,
            attempts,
        )

    def _validate_plan(self, plan: SQLPlan, catalog: SchemaCatalog) -> PlanValidation:
        """Validate plan and return the policy result."""
        if not plan.sql.strip():
            return PlanValidation(None, "Planner did not provide SQL.")
        table_names = {table.name.casefold() for table in catalog.tables}
        unknown_tables = sorted(
            {name.casefold() for name in plan.relevant_tables} - table_names
        )
        if unknown_tables:
            return PlanValidation(
                None,
                "Planner referenced tables absent from the schema catalog.",
            )

        validation = self._validator.validate(plan.sql, row_limit=self._row_limit)
        if not validation.is_valid or validation.normalized_sql is None:
            return PlanValidation(None, "SQL was rejected by the read-only validator.")
        try:
            statements, _ = parse_mysql_sql(validation.normalized_sql)
        except ParseError:
            return PlanValidation(None, "SQL was rejected by the schema validator.")
        if (
            len(statements) != 1
            or not self._tables_exist(statements[0], catalog)
            or not self._columns_exist(statements[0], catalog)
        ):
            return PlanValidation(
                None,
                "SQL referenced a table or column absent from the schema catalog.",
            )
        return PlanValidation(validation.normalized_sql, None)

    @staticmethod
    def _tables_exist(statement: exp.Expression, catalog: SchemaCatalog) -> bool:
        """Return whether tables exist satisfies the required condition."""
        known_tables = {table.name.casefold() for table in catalog.tables}
        referenced_tables = {
            source.name.casefold()
            for scope in traverse_scope(statement)
            for _, source in scope.sources.items()
            if isinstance(source, exp.Table)
        }
        return referenced_tables.issubset(known_tables)

    @staticmethod
    def _columns_exist(statement: exp.Expression, catalog: SchemaCatalog) -> bool:
        """Return whether columns exist satisfies the required condition."""
        columns_by_table = {
            table.name.casefold(): {column.name.casefold() for column in table.columns}
            for table in catalog.tables
        }
        all_columns = set().union(*columns_by_table.values()) if columns_by_table else set()
        for scope in traverse_scope(statement):
            output_aliases = {
                projection.alias.casefold()
                for projection in scope.expression.selects
                if isinstance(projection, exp.Alias)
            }
            sources = scope.selected_sources
            for column in scope.columns:
                if column.is_star:
                    continue
                name = column.name.casefold()
                if name in output_aliases:
                    continue
                if column.table:
                    selected_source = sources.get(column.table.casefold())
                    source = selected_source[1] if selected_source else None
                    if selected_source is None:
                        source = next(
                            (
                                candidate
                                for _, (_, candidate) in sources.items()
                                if isinstance(candidate, exp.Table)
                                and candidate.name.casefold() == column.table.casefold()
                            ),
                            None,
                        )
                    if isinstance(source, exp.Table):
                        source_columns = columns_by_table.get(source.name.casefold())
                        if source_columns is not None and name not in source_columns:
                            return False
                        if source_columns is None and name not in all_columns:
                            return False
                    elif isinstance(source, Scope):
                        source_outputs = {
                            output_name
                            for projection in source.expression.selects
                            if (
                                output_name
                                := AnalysisWorkflow._projection_output_name(projection)
                            )
                        }
                        if name not in source_outputs and name not in all_columns:
                            return False
                    elif name not in all_columns:
                        return False
                elif name not in all_columns:
                    return False
        return True

    @staticmethod
    def _projection_output_name(projection: exp.Expression) -> str | None:
        """Internal helper that performs projection output name and returns the normalized result."""
        if isinstance(projection, exp.Alias):
            return projection.alias.casefold()
        if isinstance(projection, exp.Column):
            return projection.name.casefold()
        return None

    @staticmethod
    def _response_from_result(
        result: AnalysisResult,
        query_result: SafeQueryResult,
        warnings: list[str],
        attempts: int,
    ) -> AnalysisResponse:
        """Internal helper that performs rejected response and returns the normalized result."""
        return AnalysisResponse(
            answer=result.explanation,
            sql=query_result.executed_sql,
            columns=query_result.columns,
            rows=query_result.rows,
            chart=result.chart_spec,
            assumptions=list(result.warnings),
            warnings=warnings,
            execution_metadata=ExecutionMetadata(
                row_count=query_result.row_count,
                execution_time_seconds=query_result.execution_time,
                truncated=query_result.truncated,
                attempts=attempts,
            ),
        )

    @staticmethod
    def _clarification_response(plan: SQLPlan) -> AnalysisResponse:
        """Internal helper that performs clarification response and returns the normalized result."""
        return AnalysisResponse(
            answer=plan.clarification_question or "Please clarify your question.",
            needs_clarification=True,
            clarification_question=plan.clarification_question,
            assumptions=list(plan.assumptions),
        )

    @staticmethod
    def _rejected_response(
        assumptions: list[str],
        warning: str,
        attempts: int = 1,
    ) -> AnalysisResponse:
        """Internal helper that performs response from result and returns the normalized result."""
        return AnalysisResponse(
            answer="The request could not be safely completed.",
            assumptions=list(assumptions),
            warnings=[warning],
            execution_metadata=ExecutionMetadata(
                row_count=0,
                execution_time_seconds=0,
                truncated=False,
                attempts=attempts,
            ),
        )
