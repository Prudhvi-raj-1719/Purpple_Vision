"""Health check endpoint with per-store feed status and STALE_FEED warnings."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import fetch_store_feed_statuses, get_db, is_database_available
from app.models import HealthResponse, StoreFeedStatus

router = APIRouter(tags=["health"])

STALE_FEED_WARNING_PREFIX = "STALE_FEED"


def get_stale_feed_threshold_minutes() -> int:
    """Lag threshold from STALE_FEED_THRESHOLD_MINUTES (default 10 minutes)."""
    raw = os.getenv("STALE_FEED_THRESHOLD_MINUTES", "10")
    try:
        return max(1, int(raw))
    except ValueError:
        return 10


def build_store_feed_statuses(
    rows: list[tuple[str, datetime | None, datetime | None]],
    *,
    now: datetime,
    threshold_minutes: int,
) -> tuple[list[StoreFeedStatus], list[str]]:
    """
    Build per-store feed rows and STALE_FEED warnings.

    Staleness is based on time since the last ingested event (feed lag), not the
    event's business timestamp.
    """
    threshold = timedelta(minutes=threshold_minutes)
    stores: list[StoreFeedStatus] = []
    warnings: list[str] = []

    for store_id, last_event_at, last_ingested_at in rows:
        stale = False
        if last_ingested_at is None:
            stale = True
        else:
            ingested_at = last_ingested_at
            if ingested_at.tzinfo is None:
                ingested_at = ingested_at.replace(tzinfo=timezone.utc)
            stale = (now - ingested_at.astimezone(timezone.utc)) > threshold

        if stale:
            warnings.append(f"{STALE_FEED_WARNING_PREFIX}: {store_id}")

        stores.append(
            StoreFeedStatus(
                store_id=store_id,
                last_event_at=last_event_at,
                stale=stale,
            )
        )

    return stores, warnings


def compute_health_response(session: Session | None = None) -> HealthResponse:
    """Assemble the full health payload."""
    now = datetime.now(timezone.utc)
    db_available = is_database_available()
    threshold_minutes = get_stale_feed_threshold_minutes()

    stores: list[StoreFeedStatus] = []
    warnings: list[str] = []

    if db_available and session is not None:
        try:
            rows = fetch_store_feed_statuses(session)
            stores, warnings = build_store_feed_statuses(
                rows,
                now=now,
                threshold_minutes=threshold_minutes,
            )
        except SQLAlchemyError:
            db_available = False

    if not db_available:
        warnings = list(warnings)
        warnings.append("database_unavailable")

    has_stale_feed = any(store.stale for store in stores)
    if not db_available or has_stale_feed:
        status = "degraded"
    else:
        status = "ok"

    return HealthResponse(
        status=status,
        database_available=db_available,
        timestamp=now,
        stores=stores,
        warnings=warnings,
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
    description=(
        "Returns service status, database availability, per-store last_event_at, "
        "and STALE_FEED warnings when ingest lag exceeds the configured threshold."
    ),
)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """Report service, database, and per-store CCTV feed health."""
    return compute_health_response(db)
