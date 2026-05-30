"""Session-based visitor funnel with stage counts and drop-off percentages."""

from __future__ import annotations

import logging
from datetime import date
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
from app.metrics import parse_metric_date
from app.models import FunnelStage, StoreFunnelResponse
from app.pos_correlation import converted_visitor_ids
from app.sessions import (
    VisitorSession,
    build_sessions,
    count_unique_visitors,
    customer_sessions,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stores", tags=["funnel"])

STAGE_UNIQUE_VISITORS = "unique_visitors"
STAGE_REACHED_ANY_ZONE = "reached_any_zone"
# PDF funnel: Entry → Zone Visit → Billing Queue → Purchase
STAGE_BILLING_QUEUE = "billing_queue"
STAGE_CONVERTED_VISITORS = "converted_visitors"

# Deprecated stage key kept for imports in legacy tests/docs (use billing_queue).
STAGE_REACHED_BILLING = STAGE_BILLING_QUEUE

FUNNEL_STAGE_ORDER = (
    STAGE_UNIQUE_VISITORS,
    STAGE_REACHED_ANY_ZONE,
    STAGE_BILLING_QUEUE,
    STAGE_CONVERTED_VISITORS,
)


def compute_drop_off_pct(previous_count: int, current_count: int) -> float | None:
    """
    Percentage of visitors lost between consecutive funnel stages.

    Returns None when the prior stage count is zero (undefined drop-off).
    """
    if previous_count == 0:
        return None
    lost = previous_count - current_count
    return (lost / previous_count) * 100.0


def visitors_reached_any_zone(sessions: Sequence[VisitorSession]) -> set[str]:
    """Distinct non-staff visitor_ids with at least one zone visit in any session."""
    return {
        session.visitor_id
        for session in customer_sessions(sessions)
        if session.zones_visited
    }


def visitors_joined_billing_queue(sessions: Sequence[VisitorSession]) -> set[str]:
    """Distinct non-staff visitor_ids who joined the billing queue in any session."""
    return {
        session.visitor_id
        for session in customer_sessions(sessions)
        if session.joined_queue
    }


def visitors_reached_billing(sessions: Sequence[VisitorSession]) -> set[str]:
    """Distinct non-staff visitor_ids who reached billing in any session."""
    return {
        session.visitor_id
        for session in customer_sessions(sessions)
        if session.reached_billing
    }


def compute_overall_conversion_rate(
    unique_visitors: int,
    converted_count: int,
) -> float:
    """North Star: converted visitors ÷ unique visitors."""
    if unique_visitors == 0:
        return 0.0
    return converted_count / unique_visitors


def build_funnel_stages(
    unique_visitors: int,
    zone_count: int,
    billing_count: int,
    converted_count: int,
) -> list[FunnelStage]:
    """Build ordered funnel stages with inter-stage drop-off percentages."""
    counts = (unique_visitors, zone_count, billing_count, converted_count)
    stages: list[FunnelStage] = []

    for index, (stage_name, count) in enumerate(zip(FUNNEL_STAGE_ORDER, counts)):
        drop_off = None
        if index > 0:
            drop_off = compute_drop_off_pct(counts[index - 1], count)
        stages.append(
            FunnelStage(stage=stage_name, count=count, drop_off_pct=drop_off)
        )

    return stages


def compute_store_funnel(
    store_id: str,
    metric_date: date,
    events: list[EventRecord],
    transactions: list[PosTransactionRecord],
) -> StoreFunnelResponse:
    """Derive visitor-level funnel from events and POS rows for one UTC day."""
    sessions = build_sessions(events)

    unique_visitors = count_unique_visitors(sessions)
    zone_count = len(visitors_reached_any_zone(sessions))
    billing_count = len(visitors_joined_billing_queue(sessions))
    converted_count = len(converted_visitor_ids(sessions, transactions))

    return StoreFunnelResponse(
        store_id=store_id,
        date=metric_date.isoformat(),
        stages=build_funnel_stages(
            unique_visitors, zone_count, billing_count, converted_count
        ),
        overall_conversion_rate=compute_overall_conversion_rate(
            unique_visitors, converted_count
        ),
    )


@router.get(
    "/{store_id}/funnel",
    response_model=StoreFunnelResponse,
    summary="Store conversion funnel",
    description=(
        "Returns visitor-level funnel stages (unique → zone → billing queue → converted) "
        "with drop-off percentages and overall conversion rate for a UTC calendar day."
    ),
    responses={
        503: {"description": "Database unavailable"},
        422: {"description": "Invalid date query parameter"},
    },
)
def get_store_funnel(
    store_id: str,
    date_param: str | None = Query(
        default=None,
        alias="date",
        description="UTC calendar day (YYYY-MM-DD). Defaults to today (UTC).",
    ),
    db: Session = Depends(get_db),
) -> StoreFunnelResponse:
    """Compute store funnel from ingested events and POS transactions."""
    if not is_database_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        )

    metric_date = parse_metric_date(date_param)

    try:
        events = fetch_store_events(db, store_id, day=metric_date)
        transactions = fetch_store_pos_transactions(db, store_id, day=metric_date)
        return compute_store_funnel(store_id, metric_date, events, transactions)
    except SQLAlchemyError as exc:
        logger.exception("Database error computing funnel for %s", store_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error while computing funnel",
        ) from exc
