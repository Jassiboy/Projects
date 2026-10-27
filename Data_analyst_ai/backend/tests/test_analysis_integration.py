"""Verify analysis integration behavior with isolated unit or opt-in integration tests."""

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.analysis.answer_builder import AnswerBuilder, GroundedAnswer
from backend.app.analysis.chart_policy import ChartPolicy
from backend.app.analysis.models import SQLPlan
from backend.app.analysis.planner import AnalysisPlanner
from backend.app.analysis.workflow import AnalysisWorkflow
from backend.app.catalog.catalog_service import CatalogService
from backend.app.catalog.metadata_loader import MetadataLoader
from backend.app.database.mysql import MySQLReadOnlyAdapter
from backend.app.database.safe_query_runner import SafeQueryRunner
from backend.app.database.sql_validator import SQLValidator
from backend.app.llm.models import LLMResponse


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_MYSQL_INTEGRATION") != "1",
    reason="Set RUN_MYSQL_INTEGRATION=1 to use the configured MySQL database",
)


class _GoldenPlanner(AnalysisPlanner):
    """Test double used to provide deterministic GoldenPlanner behavior."""
    def __init__(self, plan: SQLPlan) -> None:
        """Initialize the _GoldenPlanner with its required collaborators and state."""
        self._plan = plan
        self.prompt_context = ()

    def plan(self, *args):
        """Perform plan and return the resulting application value."""
        self.prompt_context = args
        return self._plan


class _GroundingProvider:
    """Test double used to provide deterministic GroundingProvider behavior."""
    def generate_structured(self, prompt, response_model):
        """Perform generate structured and return the resulting application value."""
        assert response_model is GroundedAnswer
        marker = "Columns and result rows (bounded):\n"
        rows = json.loads(prompt.split(marker, 1)[1])
        evidence = [
            str(cell)
            for row in rows[:1]
            for cell in row.values()
            if cell is not None
        ]
        return LLMResponse(
            parsed_output=GroundedAnswer(
                explanation="The returned figures are grounded in the result rows.",
                findings=[],
                evidence=evidence,
            ),
            provider_name="test",
            model_name="deterministic",
            latency_seconds=0,
            token_usage=None,
            finish_status="STOP",
        )


GOLDEN_QUERIES = (
    (
        "Compare net revenue for 2024 and 2025",
        SQLPlan(
            intent="Net revenue by order year",
            relevant_tables=["orders", "payments", "refunds"],
            sql="""
                WITH payments_by_year AS (
                    SELECT YEAR(o.order_date) AS year, SUM(p.amount) AS gross_revenue
                    FROM payments p
                    JOIN orders o ON o.order_id = p.order_id
                    WHERE p.payment_status = 'successful'
                    GROUP BY YEAR(o.order_date)
                ), refunds_by_year AS (
                    SELECT YEAR(o.order_date) AS year,
                        SUM(r.refund_amount) AS refund_total
                    FROM refunds r
                    JOIN orders o ON o.order_id = r.order_id
                    GROUP BY YEAR(o.order_date)
                )
                SELECT p.year, p.gross_revenue - COALESCE(r.refund_total, 0)
                    AS net_revenue
                FROM payments_by_year p
                LEFT JOIN refunds_by_year r ON r.year = p.year
                WHERE p.year IN (2024, 2025)
                ORDER BY p.year
            """,
        ),
        [
            {"year": 2024, "net_revenue": Decimal("2193722.64")},
            {"year": 2025, "net_revenue": Decimal("2317515.59")},
        ],
        "line",
    ),
    (
        "Show the top five products by net line-item revenue",
        SQLPlan(
            intent="Top products by net line-item revenue",
            relevant_tables=["products", "order_items", "orders", "payments", "refunds"],
            sql="""
                WITH product_gross AS (
                    SELECT p.product_id, p.product_name,
                        SUM(oi.quantity * oi.unit_price - oi.discount_amount)
                            AS gross_revenue
                    FROM products p
                    JOIN order_items oi ON oi.product_id = p.product_id
                    JOIN orders o ON o.order_id = oi.order_id
                    JOIN payments pay ON pay.order_id = o.order_id
                    WHERE pay.payment_status = 'successful'
                    GROUP BY p.product_id, p.product_name
                ), product_refunds AS (
                    SELECT oi.product_id, SUM(r.refund_amount) AS refund_total
                    FROM refunds r
                    JOIN order_items oi ON oi.order_item_id = r.order_item_id
                    GROUP BY oi.product_id
                )
                SELECT pg.product_name,
                    pg.gross_revenue - COALESCE(pr.refund_total, 0) AS net_revenue
                FROM product_gross pg
                LEFT JOIN product_refunds pr ON pr.product_id = pg.product_id
                ORDER BY net_revenue DESC, pg.product_name
                LIMIT 5
            """,
        ),
        [
            {"product_name": "Object-based 3rdgeneration intranet", "net_revenue": Decimal("182046.68")},
            {"product_name": "Organic multi-tasking info-mediaries", "net_revenue": Decimal("176037.31")},
            {"product_name": "Phased multi-state benchmark", "net_revenue": Decimal("170418.52")},
            {"product_name": "Inverse interactive framework", "net_revenue": Decimal("165224.22")},
            {"product_name": "Compatible maximized orchestration", "net_revenue": Decimal("163046.17")},
        ],
        "bar",
    ),
    (
        "Compare net revenue across customer regions",
        SQLPlan(
            intent="Net revenue by region",
            relevant_tables=["customers", "orders", "payments", "refunds"],
            sql="""
                WITH payments_by_region AS (
                    SELECT c.region, SUM(p.amount) AS gross_revenue
                    FROM customers c
                    JOIN orders o ON o.customer_id = c.customer_id
                    JOIN payments p ON p.order_id = o.order_id
                    WHERE p.payment_status = 'successful'
                    GROUP BY c.region
                ), refunds_by_region AS (
                    SELECT c.region, SUM(r.refund_amount) AS refund_total
                    FROM customers c
                    JOIN orders o ON o.customer_id = c.customer_id
                    JOIN refunds r ON r.order_id = o.order_id
                    GROUP BY c.region
                )
                SELECT p.region, p.gross_revenue - COALESCE(r.refund_total, 0)
                    AS net_revenue
                FROM payments_by_region p
                LEFT JOIN refunds_by_region r ON r.region = p.region
                ORDER BY net_revenue DESC
            """,
        ),
        [
            {"region": "Northeast", "net_revenue": Decimal("1928430.22")},
            {"region": "Southwest", "net_revenue": Decimal("1836180.11")},
            {"region": "Southeast", "net_revenue": Decimal("1766730.17")},
            {"region": "Midwest", "net_revenue": Decimal("1738721.69")},
            {"region": "West", "net_revenue": Decimal("1726407.46")},
        ],
        "bar",
    ),
)


@pytest.mark.parametrize(
    ("question", "plan", "golden_rows", "chart_type"),
    GOLDEN_QUERIES,
)
def test_real_mysql_analysis_matches_seeded_golden_results(
    question,
    plan,
    golden_rows,
    chart_type,
):
    """Verify that real mysql analysis matches seeded golden results; the test passes when the expected behavior is preserved."""
    adapter = MySQLReadOnlyAdapter()
    try:
        catalog = CatalogService(MetadataLoader(adapter)).build_catalog("analyst_ai")
        workflow = AnalysisWorkflow(
            planner=_GoldenPlanner(plan),
            validator=SQLValidator(),
            query_runner=SafeQueryRunner(adapter),
            answer_builder=AnswerBuilder(_GroundingProvider()),
            chart_policy=ChartPolicy(),
            row_limit=100,
        )

        result = workflow.analyze(question, catalog)
    finally:
        adapter.close()

    assert result.rows == golden_rows
    assert result.validated_sql
    assert result.explanation
    assert result.chart_spec.chart_type == chart_type
