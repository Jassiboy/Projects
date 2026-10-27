"""Verify analysis workflow behavior with isolated unit or opt-in integration tests."""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.app.analysis.answer_builder import (
    AnswerBuilder,
    GroundedAnswer,
)
from backend.app.analysis.chart_policy import ChartPolicy
from backend.app.analysis.models import ChartSuggestion, SQLPlan
from backend.app.analysis.workflow import AnalysisWorkflow
from backend.app.catalog.models import (
    BusinessMetric,
    ColumnCatalogEntry,
    SchemaCatalog,
    TableCatalogEntry,
    TableRelationship,
)
from backend.app.database.base import DatabaseQueryError
from backend.app.database.safe_query_runner import SafeQueryResult
from backend.app.database.sql_validator import SQLValidator
from backend.app.llm.models import LLMResponse


def make_catalog():
    """Build and return catalog."""
    table_columns = {
        "categories": ("category_id", "category_name"),
        "customers": ("customer_id", "region"),
        "products": ("product_id", "product_name", "category_id", "unit_price"),
        "orders": (
            "order_id",
            "customer_id",
            "order_date",
            "order_status",
            "sales_channel",
            "discount_amount",
            "shipping_amount",
        ),
        "order_items": (
            "order_item_id",
            "order_id",
            "product_id",
            "quantity",
            "unit_price",
            "discount_amount",
        ),
        "payments": ("payment_id", "order_id", "payment_date", "payment_status", "amount"),
        "refunds": (
            "refund_id",
            "order_id",
            "order_item_id",
            "refund_date",
            "refund_amount",
        ),
    }
    tables = tuple(
        TableCatalogEntry(
            name=table_name,
            description=table_name,
            columns=tuple(
                ColumnCatalogEntry(
                    name=column_name,
                    data_type="varchar" if column_name in {"region", "product_name"} else "decimal",
                    nullable=False,
                    primary_key=column_name.endswith("_id") and column_name in {
                        "category_id", "customer_id", "product_id", "order_id",
                        "order_item_id", "payment_id", "refund_id",
                    },
                    description=column_name,
                )
                for column_name in columns
            ),
        )
        for table_name, columns in table_columns.items()
    )
    relationships = (
        TableRelationship(
            name="orders_customer_fk",
            source_table="orders",
            source_columns=("customer_id",),
            target_table="customers",
            target_columns=("customer_id",),
        ),
    )
    return SchemaCatalog(
        database="analyst_ai",
        tables=tables,
        relationships=relationships,
        business_metrics=(
            BusinessMetric(
                name="net_revenue",
                description="Payments less refunds.",
                formula="payments - refunds",
                caveat="Aggregate facts independently.",
            ),
        ),
    )


class FakePlanner:
    """Test double used to provide deterministic FakePlanner behavior."""
    def __init__(self, plans, repaired_plans=()):
        """Initialize the FakePlanner with its required collaborators and state."""
        self.plans = iter(plans)
        self.repaired_plans = iter(repaired_plans)
        self.plan_calls = []
        self.repair_calls = []

    def plan(self, *args):
        """Perform plan and return the resulting application value."""
        self.plan_calls.append(args)
        return next(self.plans)

    def repair(self, *args):
        """Perform repair and return the resulting application value."""
        self.repair_calls.append(args)
        return next(self.repaired_plans)


class FakeLLM:
    """Test double used to provide deterministic FakeLLM behavior."""
    def __init__(self):
        """Initialize the FakeLLM with its required collaborators and state."""
        self.prompts = []

    def generate_structured(self, prompt, response_model):
        """Perform generate structured and return the resulting application value."""
        self.prompts.append((prompt, response_model))
        if response_model is GroundedAnswer:
            marker = "Columns and result rows (bounded):\n"
            rows = json.loads(prompt.split(marker, 1)[1])
            evidence = [
                str(value)
                for row in rows[:1]
                for value in row.values()
                if value is not None
            ]
            parsed = GroundedAnswer(
                explanation="The result values are shown in the returned rows.",
                findings=[],
                evidence=evidence,
            )
        else:
            raise AssertionError(f"Unexpected response schema: {response_model}")
        return LLMResponse(
            parsed_output=parsed,
            provider_name="fake",
            model_name="fake",
            latency_seconds=0.01,
            token_usage=None,
            finish_status="STOP",
        )


class FakeRunner:
    """Test double used to provide deterministic FakeRunner behavior."""
    def __init__(self, results=(), failures=()):
        """Initialize the FakeRunner with its required collaborators and state."""
        self.results = iter(results)
        self.failures = iter(failures)
        self.calls = []

    def run(self, sql, row_limit=None):
        """Perform run and return the resulting application value."""
        self.calls.append((sql, row_limit))
        failure = next(self.failures, None)
        if failure is not None:
            raise failure
        return next(self.results)


def make_result(rows, columns=None, sql="SELECT result LIMIT 100"):
    """Build and return result."""
    return SafeQueryResult(
        executed_sql=sql,
        columns=columns or list(rows[0].keys()),
        rows=rows,
        row_count=len(rows),
        truncated=False,
        execution_time=0.025,
    )


def make_workflow(plan, result=None, *, repaired_plans=(), failures=(), results=()):
    """Build and return workflow."""
    llm = FakeLLM()
    planner = FakePlanner([plan], repaired_plans)
    runner = FakeRunner(results or ([result] if result is not None else ()), failures)
    workflow = AnalysisWorkflow(
        planner=planner,
        validator=SQLValidator(),
        query_runner=runner,
        answer_builder=AnswerBuilder(llm, max_rows_for_llm=2),
    )
    return workflow, planner, runner, llm


def test_yearwise_net_revenue_matches_golden_values():
    """Verify that yearwise net revenue matches golden values; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(
        intent="Net revenue by year",
        relevant_tables=["orders", "payments", "refunds"],
        sql=(
            "WITH payments_by_year AS ("
            "SELECT YEAR(o.order_date) AS year, SUM(p.amount) AS gross_revenue "
            "FROM payments p JOIN orders o ON o.order_id = p.order_id "
            "WHERE p.payment_status = 'successful' "
            "GROUP BY YEAR(o.order_date)), "
            "refunds_by_year AS ("
            "SELECT YEAR(o.order_date) AS year, SUM(r.refund_amount) AS refund_total "
            "FROM refunds r JOIN orders o ON o.order_id = r.order_id "
            "GROUP BY YEAR(o.order_date)) "
            "SELECT p.year AS order_year, "
            "p.gross_revenue - COALESCE(r.refund_total, 0) AS net_revenue "
            "FROM payments_by_year p LEFT JOIN refunds_by_year r ON r.year = p.year"
        ),
    )
    golden_rows = [
        {"order_year": 2024, "net_revenue": Decimal("2193722.64")},
        {"order_year": 2025, "net_revenue": Decimal("2317515.59")},
    ]
    workflow, _, runner, _ = make_workflow(
        plan,
        make_result(golden_rows),
    )

    result = workflow.analyze("Net revenue for 2024 and 2025", make_catalog())

    assert result.rows == golden_rows
    assert result.rows[0]["net_revenue"] == Decimal("2193722.64")
    assert result.rows[1]["net_revenue"] == Decimal("2317515.59")
    assert result.chart_spec.chart_type == "line"
    assert runner.calls[0][0].endswith("LIMIT 100")


def test_top_products_and_region_analysis_are_returned_as_bar_charts():
    """Verify that top products and region analysis are returned as bar charts; the test passes when the expected behavior is preserved."""
    scenarios = [
        (
            SQLPlan(
                intent="Top products",
                relevant_tables=["products"],
                sql="SELECT product_name, unit_price AS net_revenue FROM products",
            ),
            [{"product_name": "Product A", "net_revenue": Decimal("182046.68")}],
            "product_name",
        ),
        (
            SQLPlan(
                intent="Net revenue by region",
                relevant_tables=["customers", "orders", "payments"],
                sql=(
                    "SELECT c.region, SUM(p.amount) AS net_revenue "
                    "FROM customers c JOIN orders o ON o.customer_id = c.customer_id "
                    "JOIN payments p ON p.order_id = o.order_id GROUP BY c.region"
                ),
            ),
            [{"region": "Northeast", "net_revenue": Decimal("1928430.22")}],
            "region",
        ),
    ]
    for plan, rows, category_field in scenarios:
        workflow, _, _, _ = make_workflow(plan, make_result(rows))

        result = workflow.analyze("Compare categories", make_catalog())

        assert result.chart_spec.chart_type == "bar"
        assert result.chart_spec.x_field == category_field
        assert result.rows == rows


def test_ambiguous_question_returns_clarification_without_query():
    """Verify that ambiguous question returns clarification without query; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(
        intent="Clarify revenue",
        clarification_question="Do you mean gross or net revenue?",
    )
    workflow, _, runner, _ = make_workflow(plan)

    result = workflow.analyze("What is revenue?", make_catalog())

    assert result.clarification_question == "Do you mean gross or net revenue?"
    assert result.validated_sql is None
    assert result.chart_spec is None
    assert runner.calls == []


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM customers",
        "SELECT missing_column FROM customers",
        "SELECT * FROM unknown_table",
    ],
)
def test_unsafe_write_or_hallucinated_identifiers_never_reach_runner(sql):
    """Verify that unsafe write or hallucinated identifiers never reach runner; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(
        intent="Unsafe plan",
        relevant_tables=["customers"],
        sql=sql,
    )
    workflow, _, runner, _ = make_workflow(plan)

    result = workflow.analyze("Analyze data", make_catalog())

    assert runner.calls == []
    assert result.validated_sql is None
    assert result.warnings


def test_final_result_contains_grounded_explanation_sql_rows_chart_and_metadata():
    """Verify that final result contains grounded explanation sql rows chart and metadata; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(
        intent="Orders by year",
        relevant_tables=["orders"],
        sql="SELECT YEAR(order_date) AS order_year, COUNT(*) AS order_count FROM orders GROUP BY YEAR(order_date)",
        assumptions=["Only available years are included."],
        chart_suggestion=ChartSuggestion(
            chart_type="bar",
            title="Model suggested chart",
            x_field="order_year",
            y_field="order_count",
        ),
    )
    rows = [{"order_year": 2025, "order_count": 25}]
    workflow, _, _, answer_llm = make_workflow(plan, make_result(rows))

    result = workflow.analyze("Orders per year", make_catalog())

    assert result.explanation
    assert result.validated_sql == "SELECT result LIMIT 100"
    assert result.rows == rows
    assert result.chart_spec.chart_type == "line"
    assert result.chart_spec.title == "Orders by year"
    assert result.warnings == ["Only available years are included."]
    assert result.execution_metadata.row_count == 1
    assert result.execution_metadata.attempts == 1
    prompt_rows = json.loads(
        answer_llm.prompts[0][0].split("Columns and result rows (bounded):\n", 1)[1]
    )
    assert prompt_rows == rows


def test_database_failure_has_only_one_repair_attempt():
    """Verify that database failure has only one repair attempt; the test passes when the expected behavior is preserved."""
    invalid_first_plan = SQLPlan(
        intent="Orders",
        relevant_tables=["orders"],
        sql="SELECT order_id FROM orders",
    )
    repaired_plan = invalid_first_plan.model_copy(update={"sql": "SELECT order_id FROM orders"})
    workflow, planner, runner, _ = make_workflow(
        invalid_first_plan,
        repaired_plans=[repaired_plan],
        failures=[DatabaseQueryError("internal host credentials")],
        results=[make_result([{"order_id": 1}])],
    )

    result = workflow.analyze("List orders", make_catalog())

    assert len(planner.repair_calls) == 1
    assert len(runner.calls) == 2
    assert planner.repair_calls[0][3] == "The read-only query execution failed."
    assert result.execution_metadata.attempts == 2


def test_chart_policy_uses_kpi_and_table_types_for_other_result_shapes():
    """Verify that chart policy uses kpi and table types for other result shapes; the test passes when the expected behavior is preserved."""
    policy = ChartPolicy()
    simple_plan = SQLPlan(intent="Result")

    kpi = policy.build_spec(
        simple_plan,
        ["total"],
        [{"total": Decimal("250.00")}],
    )
    table = policy.build_spec(
        simple_plan,
        ["label"],
        [{"label": "no numeric measure"}],
    )

    assert kpi.chart_type == "kpi"
    assert kpi.y_field == "total"
    assert table.chart_type == "table"


def test_chart_policy_rejects_model_fields_not_present_in_result():
    """Verify that chart policy rejects model fields not present in result; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(
        intent="Revenue by region",
        chart_suggestion=ChartSuggestion(
            chart_type="bar",
            x_field="hallucinated_region",
            y_field="revenue",
        ),
    )

    chart = ChartPolicy().build_spec(
        plan,
        ["region", "net_revenue"],
        [{"region": "West", "net_revenue": Decimal("10.00")}],
    )

    assert chart.chart_type == "bar"
    assert chart.x_field == "region"
    assert chart.y_field == "net_revenue"


def test_answer_builder_sends_at_most_configured_rows_to_llm():
    """Verify that answer builder sends at most configured rows to llm; the test passes when the expected behavior is preserved."""
    llm = FakeLLM()
    rows = [{"amount": 1}, {"amount": 2}, {"amount": 3}]
    builder = AnswerBuilder(llm, max_rows_for_llm=2)

    result = builder.build(
        "Show amounts",
        SQLPlan(intent="Amounts"),
        "SELECT amount FROM payments",
        rows,
        None,
    )

    prompt_rows = json.loads(
        llm.prompts[0][0].split("Columns and result rows (bounded):\n", 1)[1]
    )
    assert prompt_rows == rows[:2]
    assert result.rows == rows
    assert result.warnings == [
        "Only the first 2 rows were used to draft the explanation."
    ]


def test_answer_builder_rejects_unsupported_numeric_claims():
    """Verify that answer builder rejects unsupported numeric claims; the test passes when the expected behavior is preserved."""
    class UnsupportedNumberProvider:
        """Represent UnsupportedNumberProvider data or behavior used by the application."""
        def generate_structured(self, prompt, response_model):
            """Perform generate structured and return the resulting application value."""
            assert prompt
            assert response_model is GroundedAnswer
            return SimpleNamespace(
                parsed_output=GroundedAnswer(
                    explanation="Total revenue was 999.",
                    findings=[],
                    evidence=["1"],
                )
            )

    builder = AnswerBuilder(UnsupportedNumberProvider())
    with pytest.raises(ValueError, match="unsupported numeric claims"):
        builder.build(
            "Show value",
            SQLPlan(intent="Value"),
            "SELECT 1",
            [{"value": 1}],
            None,
        )


def test_repair_is_attempted_only_once_even_if_second_execution_fails():
    """Verify that repair is attempted only once even if second execution fails; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(
        intent="Orders",
        relevant_tables=["orders"],
        sql="SELECT order_id FROM orders",
    )
    workflow, planner, runner, _ = make_workflow(
        plan,
        repaired_plans=[plan],
        failures=[
            DatabaseQueryError("first execution failure"),
            DatabaseQueryError("second execution failure"),
        ],
    )

    result = workflow.analyze("List orders", make_catalog())

    assert len(planner.repair_calls) == 1
    assert len(runner.calls) == 2
    assert result.validated_sql is None
    assert result.execution_metadata.attempts == 2
