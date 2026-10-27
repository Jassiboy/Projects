"""Register all versioned API route groups for the application."""

from fastapi import APIRouter

from .routes import analysis, database, health


router = APIRouter(prefix="/api/v1")
router.include_router(database.router, tags=["database"])
router.include_router(health.router, tags=["health"])
router.include_router(analysis.router, tags=["analysis"])
