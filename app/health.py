"""Health check endpoint."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.db import is_database_available

router = APIRouter(tags=["health"])


class HealthCheckResponse(BaseModel):
    """GET /health response."""

    status: str = Field(
        description="Application status: 'ok' when DB is reachable, else 'degraded'.",
    )
    database_available: bool = Field(
        description="True when the SQLite database accepts connections.",
    )
    timestamp: datetime = Field(
        description="UTC timestamp when the health check was performed.",
    )


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    summary="Service health check",
    description=(
        "Returns application status and database availability. "
        "Used by orchestrators and the acceptance gate."
    ),
)
def health_check() -> HealthCheckResponse:
    """Report service and database health."""
    db_available = is_database_available()
    return HealthCheckResponse(
        status="ok" if db_available else "degraded",
        database_available=db_available,
        timestamp=datetime.now(timezone.utc),
    )
