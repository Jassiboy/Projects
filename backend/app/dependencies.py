"""Assemble request-scoped database, catalog, and analysis services for the FastAPI application."""

import asyncio
from collections.abc import Callable
from dataclasses import asdict
import json
import time
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, status

from backend.app.analysis.answer_builder import AnswerBuilder
from backend.app.analysis.planner import AnalysisPlanner
from backend.app.analysis.workflow import AnalysisWorkflow
from backend.app.catalog.catalog_service import CatalogService
from backend.app.catalog.metadata_loader import MetadataLoader
from backend.app.config import DatabaseSettings, LLMSettings
from backend.app.database.base import DatabaseAdapter
from backend.app.database.mysql import MySQLReadOnlyAdapter
from backend.app.database.safe_query_runner import SafeQueryRunner
from backend.app.database.sql_validator import SQLValidator
from backend.app.llm.factory import create_llm_provider


API_REQUEST_TIMEOUT_SECONDS = 60.0
API_RESULT_ROW_LIMIT = 100
DATABASE_QUERY_TIMEOUT_SECONDS = 5.0


class ApplicationDependencyError(RuntimeError):
    """A sanitized error while initializing application services."""


def get_database_settings(request: Request) -> DatabaseSettings:
    """Resolve and return database settings for the active connection session or environment."""
    session = getattr(request.state, "database_session", None)
    if session is not None:
        return session["settings"]
    settings = getattr(request.app.state, "database_settings", None)
    if settings is None:
        try:
            settings = DatabaseSettings()
        except Exception:
            raise ApplicationDependencyError(
                "Database service is unavailable."
            ) from None
        request.app.state.database_settings = settings
    return settings


def get_database_adapter(
    request: Request,
    x_database_connection: str | None = Header(default=None),
) -> DatabaseAdapter:
    """Resolve and return the database adapter authorized for the current request."""
    if x_database_connection:
        sessions = getattr(request.app.state, "database_sessions", {})
        session = sessions.get(x_database_connection)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Database connection has expired. Please connect again.",
            )
        request.state.database_session = session
        return session["adapter"]

    settings = get_database_settings(request)
    adapter = getattr(request.app.state, "database_adapter", None)
    if adapter is None:
        try:
            adapter = MySQLReadOnlyAdapter(settings)
        except Exception:
            raise ApplicationDependencyError(
                "Database service is unavailable."
            ) from None
        request.app.state.database_adapter = adapter
    return adapter


def get_catalog_service(
    request: Request,
    database_adapter: DatabaseAdapter = Depends(get_database_adapter),
) -> CatalogService:
    """Return the catalog service cached for the active database adapter."""
    services = getattr(request.app.state, "catalog_services", None)
    if services is None:
        services = {}
        request.app.state.catalog_services = services
    key = id(database_adapter)
    service = services.get(key)
    if service is None:
        service = CatalogService(MetadataLoader(database_adapter))
        services[key] = service
    return service


def get_analysis_workflow(
    request: Request,
    database_adapter: DatabaseAdapter = Depends(get_database_adapter),
) -> AnalysisWorkflow:
    """Return the analysis workflow wired to the active database adapter and LLM."""
    workflows = getattr(request.app.state, "analysis_workflows", None)
    if workflows is None:
        workflows = {}
        request.app.state.analysis_workflows = workflows
    key = id(database_adapter)
    workflow = workflows.get(key)
    if workflow is None:
        try:
            llm_provider = create_llm_provider(LLMSettings())
            workflow = AnalysisWorkflow(
                planner=AnalysisPlanner(llm_provider),
                validator=SQLValidator(),
                query_runner=SafeQueryRunner(
                    database_adapter,
                    timeout_seconds=DATABASE_QUERY_TIMEOUT_SECONDS,
                ),
                answer_builder=AnswerBuilder(llm_provider),
                row_limit=API_RESULT_ROW_LIMIT,
            )
        except Exception:
            raise ApplicationDependencyError(
                "Analysis service is unavailable."
            ) from None
        workflows[key] = workflow
    return workflow


async def database_is_healthy(
    request: Request,
    adapter: DatabaseAdapter = Depends(get_database_adapter),
) -> bool:
    """Probe the active database and return whether it is available."""
    try:
        return await run_with_request_timeout(request, adapter.health_check)
    except Exception:
        return False


async def run_with_request_timeout(
    request: Request,
    operation: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run blocking work in a thread and return its result within the request deadline."""
    deadline = getattr(request.state, "api_request_deadline", None)
    if deadline is None:
        timeout_seconds = getattr(
            request.app.state,
            "api_request_timeout_seconds",
            API_REQUEST_TIMEOUT_SECONDS,
        )
        deadline = time.monotonic() + timeout_seconds
        request.state.api_request_deadline = deadline
    remaining_seconds = deadline - time.monotonic()
    if remaining_seconds <= 0:
        raise TimeoutError
    return await asyncio.wait_for(
        asyncio.to_thread(operation, *args, **kwargs),
        timeout=remaining_seconds,
    )


def catalog_glossary_json(catalog: Any) -> str:
    """Serialize business metrics into compact JSON for the LLM prompt."""
    metrics = [asdict(metric) for metric in catalog.business_metrics]
    return json.dumps(metrics, ensure_ascii=True, separators=(",", ":"))
