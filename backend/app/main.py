"""Create the FastAPI application, serve the frontend, and sanitize application-level errors."""

from contextlib import asynccontextmanager
from pathlib import Path
import sys

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

if __package__ == "app":
    project_root = str(Path(__file__).resolve().parents[2])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from backend.app.api.router import router
from backend.app.dependencies import ApplicationDependencyError


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifetime and close all database adapters during shutdown."""
    yield
    for session in getattr(app.state, "database_sessions", {}).values():
        session["adapter"].close()
    adapter = getattr(app.state, "database_adapter", None)
    if adapter is not None:
        adapter.close()


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    app = FastAPI(title="Data Analyst AI API", lifespan=lifespan)
    app.include_router(router)
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIR),
        name="assets",
    )

    @app.get("/", include_in_schema=False)
    def frontend() -> FileResponse:
        """Return the finalized frontend HTML file."""
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        """Perform handle unexpected error and return the resulting application value."""
        return JSONResponse(
            status_code=422,
            content={"detail": "Request validation failed."},
        )

    @app.exception_handler(ApplicationDependencyError)
    async def handle_dependency_error(
        _request: Request,
        _exc: ApplicationDependencyError,
    ) -> JSONResponse:
        """Perform handle dependency error and return the resulting application value."""
        return JSONResponse(
            status_code=503,
            content={"detail": "Application services are temporarily unavailable."},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        _request: Request,
        _exc: Exception,
    ) -> JSONResponse:
        """Perform handle request validation error and return the resulting application value."""
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal error occurred."},
        )

    return app


app = create_app()
