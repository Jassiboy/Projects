"""Verify api behavior with isolated unit or opt-in integration tests."""

import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app.analysis.answer_builder import AnswerBuilder, GroundedAnswer
from backend.app.analysis.models import SQLPlan
from backend.app.analysis.workflow import AnalysisWorkflow
from backend.app.catalog.models import (
    BusinessMetric,
    ColumnCatalogEntry,
    SchemaCatalog,
    TableCatalogEntry,
)
from backend.app.database.base import DatabaseQueryError
from backend.app.database.safe_query_runner import SafeQueryResult
from backend.app.database.sql_validator import SQLValidator
from backend.app.dependencies import (
    get_analysis_workflow,
    get_catalog_service,
    database_is_healthy,
    get_database_adapter,
    get_database_settings,
)
from backend.app.main import create_app
from backend.app.llm.base import LLMRateLimitError, LLMTimeoutError


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
                description="Customer count",
                formula="COUNT(customer_id)",
                caveat="",
            ),
        ),
    )


class FakeCatalogService:
    """Test double used to provide deterministic FakeCatalogService behavior."""
    def __init__(self, *, delay: float = 0) -> None:
        """Initialize the FakeCatalogService with its required collaborators and state."""
        self.delay = delay

    def build_catalog(self, database: str) -> SchemaCatalog:
        """Build and return catalog."""
        if self.delay:
            time.sleep(self.delay)
        assert database == "analyst_ai"
        return make_catalog()


class FakePlanner:
    """Test double used to provide deterministic FakePlanner behavior."""
    def __init__(self, plan: SQLPlan | None = None, *, error: Exception | None = None):
        """Initialize the FakePlanner with its required collaborators and state."""
        self.plan_value = plan
        self.error = error

    def plan(self, *_args):
        """Perform plan and return the resulting application value."""
        assert len(_args) == 3
        if self.error is not None:
            raise self.error
        return self.plan_value


class FakeLLM:
    """Test double used to provide deterministic FakeLLM behavior."""
    def __init__(self, error: Exception | None = None) -> None:
        """Initialize the FakeLLM with its required collaborators and state."""
        self.error = error

    def generate_structured(self, prompt: str, response_model: type):
        """Perform generate structured and return the resulting application value."""
        assert prompt
        assert response_model is GroundedAnswer
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            parsed_output=GroundedAnswer(
                explanation="The matching customer information is shown below.",
                evidence=[],
            )
        )


class FakeRunner:
    """Test double used to provide deterministic FakeRunner behavior."""
    def __init__(self, *, error: Exception | None = None) -> None:
        """Initialize the FakeRunner with its required collaborators and state."""
        self.error = error
        self.calls = []

    def run(self, sql: str, row_limit: int | None = None) -> SafeQueryResult:
        """Perform run and return the resulting application value."""
        self.calls.append((sql, row_limit))
        if self.error is not None:
            raise self.error
        return SafeQueryResult(
            executed_sql=sql,
            columns=["region", "customer_count"],
            rows=[{"region": "North", "customer_count": 3}],
            row_count=1,
            truncated=False,
            execution_time=0.01,
        )


class FakeHealthAdapter:
    """Test double used to provide deterministic FakeHealthAdapter behavior."""
    def __init__(self, *, healthy: bool = True) -> None:
        """Initialize the FakeHealthAdapter with its required collaborators and state."""
        self.healthy = healthy
        self.calls = 0

    def health_check(self) -> bool:
        """Perform health check and return the resulting application value."""
        self.calls += 1
        if not self.healthy:
            raise DatabaseQueryError("internal connection detail")
        return True


class FakeConnectedAdapter(FakeHealthAdapter):
    """Test double used to provide deterministic FakeConnectedAdapter behavior."""
    def __init__(self, settings) -> None:
        """Initialize the FakeConnectedAdapter with its required collaborators and state."""
        super().__init__()
        self.settings = settings
        self.closed = False

    def list_tables(self):
        """Return the available tables records."""
        return [SimpleNamespace(name="orders"), SimpleNamespace(name="customers")]

    def close(self) -> None:
        """Perform close and return the resulting application value."""
        self.closed = True


def make_test_client(
    plan: SQLPlan | None = None,
    *,
    planner_error: Exception | None = None,
    runner_error: Exception | None = None,
    llm_error: Exception | None = None,
    catalog_delay: float = 0,
):
    """Build and return test client."""
    runner = FakeRunner(error=runner_error)
    workflow = AnalysisWorkflow(
        planner=FakePlanner(plan, error=planner_error),
        validator=SQLValidator(),
        query_runner=runner,
        answer_builder=AnswerBuilder(FakeLLM(llm_error)),
    )
    app = create_app()
    app.dependency_overrides[get_analysis_workflow] = lambda: workflow
    app.dependency_overrides[get_catalog_service] = lambda: FakeCatalogService(
        delay=catalog_delay
    )
    app.dependency_overrides[database_is_healthy] = lambda: True
    app.dependency_overrides[get_database_settings] = lambda: SimpleNamespace(
        database="analyst_ai"
    )
    return TestClient(app), runner, app


def test_health_endpoint_reports_application_and_database_health():
    """Verify that health endpoint reports application and database health; the test passes when the expected behavior is preserved."""
    client, _, _ = make_test_client()

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_health_endpoint_uses_injected_database_adapter():
    """Verify that health endpoint uses injected database adapter; the test passes when the expected behavior is preserved."""
    adapter = FakeHealthAdapter()
    app = create_app()
    app.dependency_overrides[get_database_adapter] = lambda: adapter

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
    assert adapter.calls == 1


def test_health_endpoint_reports_unavailable_when_database_probe_fails():
    """Verify that health endpoint reports unavailable when database probe fails; the test passes when the expected behavior is preserved."""
    adapter = FakeHealthAdapter(healthy=False)
    app = create_app()
    app.dependency_overrides[get_database_adapter] = lambda: adapter

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}
    assert "internal connection detail" not in response.text


def test_finalized_frontend_is_served_from_root_and_assets():
    """Verify that finalized frontend is served from root and assets; the test passes when the expected behavior is preserved."""
    client, _, _ = make_test_client()

    page = client.get("/")
    asset = client.get("/assets/index.html")

    assert page.status_code == 200
    assert "Analyst AI — Final Workspace" in page.text
    assert "fetch('/api/v1/analyze'" in page.text
    assert "Connect MySQL" in page.text
    assert "Four-year revenue comparison" not in page.text
    assert "position:absolute!important" in page.text
    assert asset.status_code == 200
    assert asset.text == page.text


def test_database_credentials_create_an_opaque_connection_session(monkeypatch):
    """Verify that database credentials create an opaque connection session; the test passes when the expected behavior is preserved."""
    monkeypatch.setattr(
        "backend.app.api.routes.database.MySQLReadOnlyAdapter",
        FakeConnectedAdapter,
    )
    app = create_app()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/database/connect",
            json={
                "host": "127.0.0.1",
                "port": 3306,
                "database": "analyst_ai",
                "user": "readonly_user",
                "password": "not-returned",
            },
        )

    assert response.status_code == 200
    result = response.json()
    assert result["database"] == "analyst_ai"
    assert result["table_count"] == 2
    assert len(result["connection_id"]) >= 32
    assert "not-returned" not in response.text


def test_database_connection_rejects_invalid_request_without_echoing_password():
    """Verify that database connection rejects invalid request without echoing password; the test passes when the expected behavior is preserved."""
    app = create_app()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/database/connect",
            json={
                "host": "",
                "database": "bad database name",
                "user": "",
                "password": "should-stay-secret",
            },
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "Request validation failed."}
    assert "should-stay-secret" not in response.text


def test_valid_question_returns_structured_analysis_response():
    """Verify that valid question returns structured analysis response; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(
        intent="Customers by region",
        relevant_tables=["customers"],
        sql="SELECT region, COUNT(*) AS customer_count FROM customers GROUP BY region",
    )
    client, runner, _ = make_test_client(plan)

    response = client.post(
        "/api/v1/analyze",
        json={"question": "Count customers by region"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["answer"]
    assert result["sql"] == runner.calls[0][0]
    assert result["columns"] == ["region", "customer_count"]
    assert result["rows"] == [{"region": "North", "customer_count": 3}]
    assert result["chart"]["chart_type"] == "bar"


def test_clarification_response_is_returned_without_query_execution():
    """Verify that clarification response is returned without query execution; the test passes when the expected behavior is preserved."""
    plan = SQLPlan(
        intent="Clarify metric",
        clarification_question="Which region should I use?",
    )
    client, runner, _ = make_test_client(plan)

    response = client.post(
        "/api/v1/analyze",
        json={"question": "Compare customers"},
    )

    assert response.status_code == 200
    assert response.json()["needs_clarification"] is True
    assert response.json()["clarification_question"] == "Which region should I use?"
    assert runner.calls == []


def test_empty_question_is_rejected_without_echoing_input():
    """Verify that empty question is rejected without echoing input; the test passes when the expected behavior is preserved."""
    client, runner, _ = make_test_client(
        SQLPlan(intent="Customers", direct_answer="A customer.")
    )

    response = client.post("/api/v1/analyze", json={"question": "  "})

    assert response.status_code == 422
    assert response.json() == {"detail": "Request validation failed."}
    assert runner.calls == []


def test_unsafe_edited_sql_is_rejected_before_runner():
    """Verify that unsafe edited sql is rejected before runner; the test passes when the expected behavior is preserved."""
    client, runner, _ = make_test_client(
        SQLPlan(intent="Unused", direct_answer="Unused")
    )

    response = client.post(
        "/api/v1/sql/run",
        json={
            "question": "Delete customers",
            "sql": "DELETE FROM customers",
        },
    )

    assert response.status_code == 422
    assert "SQL was rejected" in response.json()["detail"]
    assert runner.calls == []


def test_valid_edited_sql_reruns_and_builds_a_fresh_report():
    """Verify that valid edited sql reruns and builds a fresh report; the test passes when the expected behavior is preserved."""
    client, runner, _ = make_test_client(
        SQLPlan(intent="Unused", direct_answer="Unused")
    )

    response = client.post(
        "/api/v1/sql/run",
        json={
            "question": "Count customers by region",
            "sql": (
                "SELECT region, COUNT(*) AS customer_count FROM customers "
                "GROUP BY region"
            ),
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert len(runner.calls) == 1
    assert runner.calls[0][1] == 100
    assert result["sql"] == runner.calls[0][0]
    assert result["sql"].endswith("LIMIT 100")
    assert result["answer"] == "The matching customer information is shown below."
    assert result["rows"] == [{"region": "North", "customer_count": 3}]


def test_internal_workflow_error_is_sanitized():
    """Verify that internal workflow error is sanitized; the test passes when the expected behavior is preserved."""
    client, runner, _ = make_test_client(
        planner_error=RuntimeError("mysql://admin:internal-password@example-host")
    )

    response = client.post(
        "/api/v1/analyze",
        json={"question": "List customers"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Analysis service is temporarily unavailable."
    }
    assert "internal-password" not in response.text
    assert "example-host" not in response.text
    assert runner.calls == []


def test_gemini_timeout_returns_gateway_timeout_without_internal_details():
    """Verify that gemini timeout returns gateway timeout without internal details; the test passes when the expected behavior is preserved."""
    client, _, _ = make_test_client(
        planner_error=LLMTimeoutError("model=private api_key=secret")
    )

    response = client.post(
        "/api/v1/analyze",
        json={"question": "Explain net revenue"},
    )

    assert response.status_code == 504
    assert response.json() == {
        "detail": "The analysis provider timed out. Please try again."
    }
    assert "secret" not in response.text
    assert "private" not in response.text


def test_gemini_rate_limit_returns_too_many_requests_without_internal_details():
    """Verify that gemini rate limit returns too many requests without internal details; the test passes when the expected behavior is preserved."""
    client, runner, _ = make_test_client(
        planner_error=LLMRateLimitError("api_key=secret provider quota exhausted")
    )

    response = client.post(
        "/api/v1/analyze",
        json={"question": "Explain net revenue"},
    )

    assert response.status_code == 429
    assert response.json() == {
        "detail": "The analysis provider is temporarily rate limited. Please try again shortly."
    }
    assert "secret" not in response.text
    assert runner.calls == []


def test_sql_report_rate_limit_returns_too_many_requests():
    """Verify that sql report rate limit returns too many requests; the test passes when the expected behavior is preserved."""
    client, runner, _ = make_test_client(
        SQLPlan(intent="Unused", direct_answer="Unused"),
        llm_error=LLMRateLimitError("private provider quota details"),
    )

    response = client.post(
        "/api/v1/sql/run",
        json={
            "question": "Count customers",
            "sql": "SELECT region, COUNT(*) AS customer_count FROM customers GROUP BY region",
        },
    )

    assert response.status_code == 429
    assert response.json() == {
        "detail": "The analysis provider is temporarily rate limited. Please try again shortly."
    }
    assert "private provider quota details" not in response.text
    assert len(runner.calls) == 1


def test_gemini_timeout_while_summarizing_sql_returns_gateway_timeout():
    """Verify that gemini timeout while summarizing sql returns gateway timeout; the test passes when the expected behavior is preserved."""
    client, runner, _ = make_test_client(
        SQLPlan(intent="Unused", direct_answer="Unused"),
        llm_error=LLMTimeoutError("model=private api_key=secret"),
    )

    response = client.post(
        "/api/v1/sql/run",
        json={
            "question": "Count customers",
            "sql": "SELECT region, COUNT(*) AS customer_count FROM customers GROUP BY region",
        },
    )

    assert response.status_code == 504
    assert response.json() == {
        "detail": "The analysis provider timed out. Please try again."
    }
    assert len(runner.calls) == 1
    assert "secret" not in response.text


def test_request_timeout_returns_sanitized_gateway_timeout():
    """Verify that request timeout returns sanitized gateway timeout; the test passes when the expected behavior is preserved."""
    client, runner, app = make_test_client(
        SQLPlan(intent="Customers", direct_answer="A customer."),
        catalog_delay=0.1,
    )
    app.state.api_request_timeout_seconds = 0.01

    response = client.post(
        "/api/v1/analyze",
        json={"question": "What is a customer?"},
    )

    assert response.status_code == 504
    assert response.json() == {
        "detail": "The analysis request timed out. Please try again."
    }
    assert runner.calls == []


def test_database_failure_is_sanitized_for_edited_sql():
    """Verify that database failure is sanitized for edited sql; the test passes when the expected behavior is preserved."""
    client, runner, _ = make_test_client(
        SQLPlan(intent="Unused", direct_answer="Unused"),
        runner_error=DatabaseQueryError("password=hidden internal-db-host"),
    )

    response = client.post(
        "/api/v1/sql/run",
        json={
            "question": "Count customers",
            "sql": "SELECT COUNT(*) AS customer_count FROM customers",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "SQL execution is temporarily unavailable."
    }
    assert "hidden" not in response.text
    assert "internal-db-host" not in response.text
    assert len(runner.calls) == 1
