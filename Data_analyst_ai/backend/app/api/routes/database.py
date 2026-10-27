"""Create temporary read-only database sessions from user-supplied MySQL credentials."""

from secrets import token_urlsafe

from fastapi import APIRouter, HTTPException, Request, status

from backend.app.config import DatabaseSettings
from backend.app.database.base import DatabaseError
from backend.app.database.mysql import MySQLReadOnlyAdapter
from backend.app.dependencies import run_with_request_timeout
from backend.app.schemas.api import DatabaseConnectRequest, DatabaseConnectResponse


router = APIRouter()


@router.post("/database/connect", response_model=DatabaseConnectResponse)
async def connect_database(
    body: DatabaseConnectRequest,
    request: Request,
) -> DatabaseConnectResponse:
    """Validate credentials, open a read-only database session, and return its opaque identifier."""
    adapter: MySQLReadOnlyAdapter | None = None
    try:
        settings = DatabaseSettings(
            DB_HOST=body.host,
            DB_PORT=body.port,
            DB_USER=body.user,
            DB_PASSWORD=body.password.get_secret_value(),
            DB_NAME=body.database,
            DB_POOL_SIZE=2,
        )
        adapter = MySQLReadOnlyAdapter(settings)
        await run_with_request_timeout(request, adapter.health_check)
        tables = await run_with_request_timeout(request, adapter.list_tables)
    except (DatabaseError, TimeoutError, ValueError):
        if adapter is not None:
            adapter.close()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not connect with those database credentials.",
        ) from None

    connection_id = token_urlsafe(32)
    sessions = getattr(request.app.state, "database_sessions", None)
    if sessions is None:
        sessions = {}
        request.app.state.database_sessions = sessions
    sessions[connection_id] = {"adapter": adapter, "settings": settings}
    return DatabaseConnectResponse(
        connection_id=connection_id,
        database=settings.database,
        table_count=len(tables),
    )
