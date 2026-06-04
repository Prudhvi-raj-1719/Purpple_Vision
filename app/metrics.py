"""Store metrics computation and GET /stores/{store_id}/metrics endpoint."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Sequence

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
from app.models import StoreMetricsResponse, ZoneDwellMetric
from app.pos_correlation import converted_visitor_ids
from app.staff_detection import (
    build_sessions_for_analytics,
    is_customer_visitor,
)
from app.sessions import (
    VisitorSession,
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


def compute_average_dwell_by_zone(
    sessions: list[VisitorSession],
) -> list[ZoneDwellMetric]:
    """
    Mean dwell per zone across customer session visits.

    Each session contributes at most one visit per zone; dwell is taken from
    session.total_dwell_ms_by_zone (same basis as the heatmap endpoint).
    """
    totals: dict[str, int] = {}
    visit_counts: dict[str, int] = {}

    for session in customer_sessions(sessions):
        for zone_id in session.zones_visited:
            visit_counts[zone_id] = visit_counts.get(zone_id, 0) + 1
            totals[zone_id] = totals.get(zone_id, 0) + session.total_dwell_ms_by_zone.get(
                zone_id, 0
            )

    return [
        ZoneDwellMetric(
            zone_id=zone_id,
            average_dwell_ms=(
                0.0
                if visit_counts[zone_id] == 0
                else totals[zone_id] / visit_counts[zone_id]
            ),
        )
        for zone_id in sorted(totals)
    ]


def compute_current_queue_depth(
    events: Sequence[EventRecord],
    staff_ids: frozenset[str] | None = None,
) -> int:
    """
    Latest non-staff billing queue depth for the event window.

    Uses metadata.queue_depth on the most recent BILLING_QUEUE_JOIN by timestamp.
    Returns 0 when no qualifying queue-join events exist.
    """
    latest: EventRecord | None = None

    for event in events:
        if event.event_type != "BILLING_QUEUE_JOIN":
            continue
        if staff_ids is not None and not is_customer_visitor(event.visitor_id, staff_ids):
            continue
        if staff_ids is None and event.is_staff:
            continue
        if latest is None or event.timestamp > latest.timestamp:
            latest = event

    if latest is None:
        return 0

    metadata = json.loads(latest.metadata_json) if latest.metadata_json else {}
    depth = metadata.get("queue_depth")
    if isinstance(depth, int) and depth > 0:
        return depth
    if isinstance(depth, float) and depth > 0:
        return int(depth)
    return 0


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
    sessions, _, staff_ids = build_sessions_for_analytics(events)
    customers = customer_sessions(sessions)

    total_revenue_inr = sum(
        transaction.basket_value_inr for transaction in transactions
    )

    return StoreMetricsResponse(
        store_id=store_id,
        date=metric_date.isoformat(),
        unique_visitors=count_unique_visitors(sessions),
        conversion_rate=compute_conversion_rate(sessions, transactions),
        average_dwell_time_ms=compute_average_dwell_time_ms(sessions),
        average_dwell_by_zone=compute_average_dwell_by_zone(sessions),
        current_queue_depth=compute_current_queue_depth(events, staff_ids),
        queue_abandonment_rate=compute_queue_abandonment_rate(sessions),
        billing_reach_rate=compute_billing_reach_rate(sessions),
        total_sessions=len(customers),
        total_revenue_inr=total_revenue_inr,
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
        "billing reach, session count, and daily POS revenue for a store on a UTC calendar day."
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
