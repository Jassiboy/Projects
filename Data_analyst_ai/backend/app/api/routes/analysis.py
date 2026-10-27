"""Expose natural-language analysis and edited-SQL execution endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.app.analysis.models import AnalysisResponse
from backend.app.analysis.workflow import (
    AnalysisWorkflow,
    AnalysisWorkflowError,
    AnalysisWorkflowRateLimitError,
    AnalysisWorkflowTimeoutError,
)
from backend.app.catalog.catalog_service import CatalogService
from backend.app.catalog.metadata_loader import CatalogLoadError
from backend.app.config import DatabaseSettings
from backend.app.database.base import DatabaseError
from backend.app.dependencies import (
    ApplicationDependencyError,
    catalog_glossary_json,
    get_analysis_workflow,
    get_catalog_service,
    get_database_settings,
    run_with_request_timeout,
)
from backend.app.schemas.api import AnalyzeRequest, SQLRunRequest


router = APIRouter()


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze(
    body: AnalyzeRequest,
    request: Request,
    workflow: AnalysisWorkflow = Depends(get_analysis_workflow),
    catalog_service: CatalogService = Depends(get_catalog_service),
    database_settings: DatabaseSettings = Depends(get_database_settings),
) -> AnalysisResponse:
    """Revalidate edited SQL, execute it, and return a regenerated analysis response."""
    try:
        catalog = await run_with_request_timeout(
            request,
            catalog_service.build_catalog,
            database_settings.database,
        )
        return await run_with_request_timeout(
            request,
            workflow.analyze,
            body.question,
            catalog,
            catalog_glossary_json(catalog),
        )
    except TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The analysis request timed out. Please try again.",
        ) from None
    except AnalysisWorkflowTimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The analysis provider timed out. Please try again.",
        ) from None
    except AnalysisWorkflowRateLimitError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The analysis provider is temporarily rate limited. Please try again shortly.",
        ) from None
    except (
        AnalysisWorkflowError,
        ApplicationDependencyError,
        CatalogLoadError,
        DatabaseError,
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analysis service is temporarily unavailable.",
        ) from None


@router.post("/sql/run", response_model=AnalysisResponse)
async def run_edited_sql(
    body: SQLRunRequest,
    request: Request,
    workflow: AnalysisWorkflow = Depends(get_analysis_workflow),
    catalog_service: CatalogService = Depends(get_catalog_service),
    database_settings: DatabaseSettings = Depends(get_database_settings),
) -> AnalysisResponse:
    """Process a natural-language question and return a validated analysis response."""
    try:
        catalog = await run_with_request_timeout(
            request,
            catalog_service.build_catalog,
            database_settings.database,
        )
        response = await run_with_request_timeout(
            request,
            workflow.rerun_with_sql,
            body.question,
            catalog,
            body.sql,
            body.assumptions,
        )
    except TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The SQL request timed out. Please try again.",
        ) from None
    except AnalysisWorkflowTimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The analysis provider timed out. Please try again.",
        ) from None
    except AnalysisWorkflowRateLimitError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The analysis provider is temporarily rate limited. Please try again shortly.",
        ) from None
    except (
        AnalysisWorkflowError,
        ApplicationDependencyError,
        CatalogLoadError,
        DatabaseError,
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SQL execution is temporarily unavailable.",
        ) from None

    if response.sql is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="SQL was rejected or could not be safely executed.",
        )
    return response
