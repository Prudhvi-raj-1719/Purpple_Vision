"""Store metrics computation and GET /stores/{store_id}/metrics endpoint."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import (
    EventRecord,
    PosTransactionRecord,
    fetch_store_events,
    fetch_store_pos_transactions,
    get_db,
    is_database_available,
)
from app.models import StoreMetricsResponse
from app.pos_correlation import converted_visitor_ids
from app.sessions import (
    VisitorSession,
    build_sessions,
    count_unique_visitors,
    customer_sessions,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stores", tags=["metrics"])


def _session_total_dwell_ms(session: VisitorSession) -> int:
    return sum(session.total_dwell_ms_by_zone.values())


def compute_average_dwell_time_ms(sessions: list[VisitorSession]) -> float:
    """Mean total zone dwell per customer session (0 when no sessions)."""
    customers = customer_sessions(sessions)
    if not customers:
        return 0.0
    total = sum(_session_total_dwell_ms(session) for session in customers)
    return total / len(customers)


def compute_billing_reach_rate(sessions: list[VisitorSession]) -> float:
    """Fraction of customer sessions that reached the billing zone."""
    customers = customer_sessions(sessions)
    if not customers:
        return 0.0
    reached = sum(1 for session in customers if session.reached_billing)
    return reached / len(customers)


def compute_queue_abandonment_rate(sessions: list[VisitorSession]) -> float:
    """Fraction of queue-join sessions that abandoned before purchase."""
    customers = customer_sessions(sessions)
    joined = [session for session in customers if session.joined_queue]
    if not joined:
        return 0.0
    abandoned = sum(1 for session in joined if session.abandoned_queue)
    return abandoned / len(joined)


def compute_conversion_rate(
    sessions: list[VisitorSession],
    transactions: list[PosTransactionRecord],
) -> float:
    """
    North Star: unique visitors with a converted session ÷ unique visitors.

    A visitor with multiple sessions (REENTRY) counts once in the numerator
    if any session correlates to a POS transaction.
    """
    unique = count_unique_visitors(sessions)
    if unique == 0:
        return 0.0
    converted = converted_visitor_ids(sessions, transactions)
    return len(converted) / unique


def compute_store_metrics(
    store_id: str,
    metric_date: date,
    events: list[EventRecord],
    transactions: list[PosTransactionRecord],
) -> StoreMetricsResponse:
    """Derive PDF metrics from events and POS rows for one store and UTC day."""
    sessions = build_sessions(events)
    customers = customer_sessions(sessions)

    return StoreMetricsResponse(
        store_id=store_id,
        date=metric_date.isoformat(),
        unique_visitors=count_unique_visitors(sessions),
        conversion_rate=compute_conversion_rate(sessions, transactions),
        average_dwell_time_ms=compute_average_dwell_time_ms(sessions),
        queue_abandonment_rate=compute_queue_abandonment_rate(sessions),
        billing_reach_rate=compute_billing_reach_rate(sessions),
        total_sessions=len(customers),
    )


def parse_metric_date(date_param: str | None) -> date:
    """Parse YYYY-MM-DD query param; default to current UTC day."""
    if date_param is None:
        return datetime.now(timezone.utc).date()
    try:
        return date.fromisoformat(date_param)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date must be ISO format YYYY-MM-DD",
        ) from exc


@router.get(
    "/{store_id}/metrics",
    response_model=StoreMetricsResponse,
    summary="Store analytics metrics",
    description=(
        "Returns unique visitors, conversion rate, dwell, queue abandonment, "
        "billing reach, and session count for a store on a UTC calendar day."
    ),
    responses={
        503: {"description": "Database unavailable"},
        422: {"description": "Invalid date query parameter"},
    },
)
def get_store_metrics(
    store_id: str,
    date_param: str | None = Query(
        default=None,
        alias="date",
        description="UTC calendar day (YYYY-MM-DD). Defaults to today (UTC).",
    ),
    db: Session = Depends(get_db),
) -> StoreMetricsResponse:
    """Compute store metrics from ingested events and POS transactions."""
    if not is_database_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        )

    metric_date = parse_metric_date(date_param)

    try:
        events = fetch_store_events(db, store_id, day=metric_date)
        transactions = fetch_store_pos_transactions(db, store_id, day=metric_date)
        return compute_store_metrics(store_id, metric_date, events, transactions)
    except SQLAlchemyError as exc:
        logger.exception("Database error computing metrics for %s", store_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error while computing metrics",
        ) from exc
