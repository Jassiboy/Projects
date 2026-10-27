"""Expose application and database health status."""

from fastapi import APIRouter, Depends, Response, status

from backend.app.dependencies import database_is_healthy
from backend.app.schemas.api import HealthResponse


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(
    response: Response,
    database_healthy: bool = Depends(database_is_healthy),
) -> HealthResponse:
    """Return application and database health while setting the matching HTTP status."""
    response.status_code = (
        status.HTTP_200_OK if database_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return HealthResponse(
        status="ok" if database_healthy else "degraded",
        database="connected" if database_healthy else "unavailable",
    )
