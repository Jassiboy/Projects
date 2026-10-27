"""Verify workflow behavior with isolated unit or opt-in integration tests."""

from types import SimpleNamespace

import pytest

from backend.app.analysis.answer_builder import AnswerBuilder, GroundedAnswer
from backend.app.analysis.models import (
    AnalysisResponse,
    ChartSuggestion,
    SQLPlan,
)
from backend.app.analysis.workflow import AnalysisWorkflow, AnalysisWorkflowError
from backend.app.catalog.models import (
    BusinessMetric,
    ColumnCatalogEntry,
    SchemaCatalog,
    TableCatalogEntry,
)
from backend.app.database.base import DatabaseQueryError
from backend.app.database.safe_query_runner import SafeQueryResult
from backend.app.database.sql_validator import SQLValidator


def make_catalog() -> SchemaCatalog:
    """Build and return catalog."""
    return SchemaCatalog(
        database="analyst_ai",
        tables=(
            TableCatalogEntry(
                name="customers",
                description="Customer records",
                columns=(
                    ColumnCatalogEntry(
                        name="customer_id",
                        data_type="int",
                        nullable=False,
                        primary_key=True,
                        description="Customer identifier",
                    ),
                    ColumnCatalogEntry(
                        name="region",
                        data_type="varchar",
                        nullable=False,
                        primary_key=False,
                        description="Customer region",
                    ),
                ),
            ),
        ),
        relationships=(),
        business_metrics=(
            BusinessMetric(
                name="customer_count",
                description="Number of customers",
                formula="COUNT(customer_id)",
                caveat="",
            ),
        ),
    )


class FakePlanner:
    """Test double used to provide deterministic FakePlanner behavior."""
    def __init__(self, plan=None, *, plan_error=None, repair_error=None) -> None:
        """Initialize the FakePlanner with its required collaborators and state."""
        self._plan = plan
        self._plan_error = plan_error
        self._repair_error = repair_error
        self.plan_calls = []
        self.repair_calls = []

    def plan(self, *args):
        """Perform plan and return the resulting application value."""
        self.plan_calls.append(args)
        if self._plan_error is not None:
            raise self._plan_error
        return self._plan

    def repair(self, *args):
        """Perform repair and return the resulting application value."""
        self.repair_calls.append(args)
        if self._repair_error is not None:
            raise self._repair_error
        raise AssertionError("Unexpected repair request")


class FakeLLM:
    """Test double used to provide deterministic FakeLLM behavior."""
    def __init__(self, *, error=None) -> None:
        """Initialize the FakeLLM with its required collaborators and state."""
        self.error = error
        self.calls = []

    def generate_structured(self, prompt, response_model):
        """Perform generate structured and return the resulting application value."""
        self.calls.append((prompt, response_model))
        if self.error is not None:
            raise self.error
        assert response_model is GroundedAnswer
        return SimpleNamespace(
            parsed_output=GroundedAnswer(
                explanation="The result is shown below.",
                evidence=["North"],
            )
        )


class FakeRunner:
    """Test double used to provide deterministic FakeRunner behavior."""
    def __init__(self, rows=(), *, columns=None, error=None, truncated=False) -> None:
        """Initialize the FakeRunner with its required collaborators and state."""
        self.rows = list(rows)
        self.columns = columns
        self.error = error
        self.truncated = truncated
        self.calls = []

    def run(self, sql, row_limit=None):
        """Perform run and return the resulting application value."""
        self.calls.append((sql, row_limit))
        if self.error is not None:
            raise self.error
        columns = self.columns or (list(self.rows[0]) if self.rows else [])
        return SafeQueryResult(
            executed_sql=sql,
            columns=columns,
            rows=self.rows,
            row_count=len(self.rows),
            truncated=self.truncated,
            execution_time=0.012,
        )


def make_workflow(
    plan=None,
    *,
    runner=None,
    planner_error=None,
    repair_error=None,
    llm_error=None,
):
    """Build and return workflow."""
    planner = FakePlanner(
        plan,
        plan_error=planner_error,
        repair_error=repair_error,
    )
    fake_runner = runner or FakeRunner()
    llm = FakeLLM(error=llm_error)
    workflow = AnalysisWorkflow(
        planner=planner,
        validator=SQLValidator(),
        query_runner=fake_runner,
        answer_builder=AnswerBuilder(llm),
    )
    return workflow, planner, fake_runner, llm


def test_simple_question_returns_direct_answer_without_sql_or_chart():
    """Verify that simple question returns direct answer without sql or chart; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(
        intent="Explain a concept",
        direct_answer="A customer is a person or organization that places orders.",
    )
    workflow, _, runner, _ = make_workflow(plan)

    response = workflow.analyze("What is a customer?", make_catalog())

    assert isinstance(response, AnalysisResponse)
    assert response.answer == plan.direct_answer
    assert response.sql is None
    assert response.chart is None
    assert runner.calls == []


def test_ambiguous_question_returns_clarification_without_execution():
    """Verify that ambiguous question returns clarification without execution; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(
        intent="Clarify metric",
        clarification_question="Do you mean gross or net revenue?",
    )
    workflow, _, runner, _ = make_workflow(plan)

    response = workflow.analyze("What was revenue?", make_catalog())

    assert response.needs_clarification is True
    assert response.clarification_question == "Do you mean gross or net revenue?"
    assert response.sql is None
    assert runner.calls == []


def test_data_question_is_validated_and_executed_with_sql_in_response():
    """Verify that data question is validated and executed with sql in response; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(
        intent="Customers by region",
        relevant_tables=["customers"],
        sql="SELECT region, COUNT(*) AS customer_count FROM customers GROUP BY region",
    )
    runner = FakeRunner(
        [{"region": "North", "customer_count": 7}],
        columns=["region", "customer_count"],
    )
    workflow, _, runner, _ = make_workflow(plan, runner=runner)

    response = workflow.analyze("Count customers by region", make_catalog())

    assert len(runner.calls) == 1
    assert runner.calls[0][0] == response.sql
    assert response.sql.endswith("LIMIT 100")
    assert response.columns == ["region", "customer_count"]
    assert response.rows == [{"region": "North", "customer_count": 7}]
    assert response.chart is not None


def test_unsafe_sql_is_rejected_before_query_runner():
    """Verify that unsafe sql is rejected before query runner; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(
        intent="Delete customers",
        relevant_tables=["customers"],
        sql="DELETE FROM customers",
    )
    workflow, _, runner, _ = make_workflow(plan)

    response = workflow.analyze("Delete customers", make_catalog())

    assert runner.calls == []
    assert response.sql is None
    assert response.warnings
    assert "safely" in response.answer


def test_empty_result_returns_helpful_answer_without_chart():
    """Verify that empty result returns helpful answer without chart; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(
        intent="Find a customer",
        relevant_tables=["customers"],
        sql="SELECT customer_id, region FROM customers WHERE customer_id = -1",
    )
    runner = FakeRunner(columns=["customer_id", "region"])
    workflow, _, _, llm = make_workflow(plan, runner=runner)

    response = workflow.analyze("Find this customer", make_catalog())

    assert response.answer == "No rows matched the question."
    assert response.rows == []
    assert response.chart is None
    assert llm.calls == []


def test_malformed_llm_response_becomes_controlled_error():
    """Verify that malformed llm response becomes controlled error; the test passes when the expected behavior is preserved."""
    workflow, _, runner, _ = make_workflow(
        planner_error=ValueError("malformed payload with api_key=secret-value"),
    )

    with pytest.raises(AnalysisWorkflowError) as error:
        workflow.analyze("Show customers", make_catalog())

    assert str(error.value) == "Analysis could not be planned. Please try again."
    assert "secret-value" not in str(error.value)
    assert runner.calls == []


def test_chart_policy_returns_only_a_valid_useful_chart_specification():
    """Verify that chart policy returns only a valid useful chart specification; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(
        intent="Customers by region",
        relevant_tables=["customers"],
        sql="SELECT region, COUNT(*) AS customer_count FROM customers GROUP BY region",
        chart_suggestion=ChartSuggestion(
            chart_type="line",
            title="Invalid suggestion for categories",
            x_field="region",
            y_field="customer_count",
        ),
    )
    runner = FakeRunner(
        [
            {"region": "North", "customer_count": 7},
            {"region": "South", "customer_count": 4},
        ],
        columns=["region", "customer_count"],
    )
    workflow, _, _, _ = make_workflow(plan, runner=runner)

    response = workflow.analyze("Count customers by region", make_catalog())

    assert response.chart is not None
    assert response.chart.chart_type == "bar"
    assert response.chart.x_field == "region"
    assert response.chart.y_field == "customer_count"


def test_executed_sql_is_always_reported():
    """Verify that executed sql is always reported; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(
        intent="List customers",
        relevant_tables=["customers"],
        sql="SELECT customer_id, region FROM customers",
    )
    runner = FakeRunner(
        [{"customer_id": 4, "region": "North"}],
        columns=["customer_id", "region"],
    )
    workflow, _, runner, _ = make_workflow(plan, runner=runner)

    response = workflow.analyze("List customers", make_catalog())

    assert response.sql == runner.calls[0][0]
    assert response.sql == "SELECT customer_id, region FROM customers LIMIT 100"


def test_edited_sql_is_revalidated_executed_and_reported():
    """Verify that edited sql is revalidated executed and reported; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(intent="Original query", direct_answer="Will be replaced.")
    runner = FakeRunner(
        [{"region": "North", "customer_count": 7}],
        columns=["region", "customer_count"],
    )
    workflow, planner, runner, _ = make_workflow(plan, runner=runner)
    edited_sql = (
        "SELECT region, COUNT(*) AS customer_count FROM customers GROUP BY region"
    )

    response = workflow.rerun_with_sql(
        "Count customers by region",
        make_catalog(),
        edited_sql,
    )

    assert planner.plan_calls == []
    assert len(runner.calls) == 1
    assert runner.calls[0][0] == response.sql
    assert response.sql.endswith("LIMIT 100")
    assert response.rows == [{"region": "North", "customer_count": 7}]


def test_edited_write_sql_is_rejected_before_query_runner():
    """Verify that edited write sql is rejected before query runner; the test passes when the expected behavior is preserved."""
    workflow, _, runner, _ = make_workflow(
        SQLPlan(intent="Original query", direct_answer="Will be replaced.")
    )

    response = workflow.rerun_with_sql(
        "Delete customers",
        make_catalog(),
        "DELETE FROM customers",
    )

    assert runner.calls == []
    assert response.sql is None
    assert response.warnings


@pytest.mark.parametrize(
    ("runner_error", "repair_error"),
    [
        (DatabaseQueryError("mysql://admin:password@internal-host"), RuntimeError("repair failed")),
        (None, None),
    ],
)
def test_database_or_answer_llm_failure_does_not_leak_internal_details(
    runner_error,
    repair_error,
):
    """Verify that database or answer llm failure does not leak internal details; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(
        intent="Customer count",
        relevant_tables=["customers"],
        sql="SELECT COUNT(*) AS customer_count FROM customers",
    )
    runner = FakeRunner(
        [{"customer_count": 5}] if runner_error is None else (),
        columns=["customer_count"],
        error=runner_error,
    )
    llm_error = RuntimeError("provider token=hidden-token") if runner_error is None else None
    workflow, _, runner, _ = make_workflow(
        plan,
        runner=runner,
        repair_error=repair_error,
        llm_error=llm_error,
    )

    if runner_error is None:
        with pytest.raises(AnalysisWorkflowError) as error:
            workflow.analyze("Count customers", make_catalog())
        message = str(error.value)
        assert "hidden-token" not in message
    else:
        response = workflow.analyze("Count customers", make_catalog())
        message = response.model_dump_json()

    assert "password" not in message
    assert "internal-host" not in message
