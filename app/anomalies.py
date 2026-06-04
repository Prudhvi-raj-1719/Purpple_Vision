"""Anomaly detection: queue spikes, conversion drops, and dead zones."""

from __future__ import annotations

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
from app.funnel import visitors_reached_billing
from app.heatmap import aggregate_zone_stats, build_heatmap_zones
from app.metrics import compute_conversion_rate, parse_metric_date
from app.models import Anomaly, AnomalySeverity, HeatmapZone, StoreAnomaliesResponse
from app.pos_correlation import converted_visitor_ids
from app.staff_detection import (
    build_sessions_for_analytics,
    count_customer_queue_joins,
)
from app.sessions import (
    BILLING_ZONE_ID,
    count_unique_visitors,
    customer_sessions,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stores", tags=["anomalies"])

# ---------------------------------------------------------------------------
# Anomaly type identifiers (challenge PDF Part B)
# ---------------------------------------------------------------------------
ANOMALY_QUEUE_SPIKE = "QUEUE_SPIKE"
ANOMALY_CONVERSION_DROP = "CONVERSION_DROP"
ANOMALY_DEAD_ZONE = "DEAD_ZONE"

# ---------------------------------------------------------------------------
# Queue spike thresholds — count of non-staff BILLING_QUEUE_JOIN events/day
# ---------------------------------------------------------------------------
# WARNING: elevated queue pressure; investigate staffing at billing counters.
QUEUE_SPIKE_WARNING_JOINS = 10
# CRITICAL: severe queue backlog; immediate operational response recommended.
QUEUE_SPIKE_CRITICAL_JOINS = 20

# ---------------------------------------------------------------------------
# Conversion drop thresholds — store-wide conversion_rate (North Star metric)
# Only evaluated when at least one non-staff visitor reached billing.
# ---------------------------------------------------------------------------
# WARNING: conversion materially below typical retail benchmark (~20%).
CONVERSION_DROP_WARNING_RATE = 0.20
# CRITICAL: conversion critically low; likely checkout or pricing issue.
CONVERSION_DROP_CRITICAL_RATE = 0.10

# ---------------------------------------------------------------------------
# Dead zone thresholds — heatmap normalized_score (0–100) per zone
# Only evaluated when two or more zones have customer visits (normalization
# requires a relative comparison; a lone zone always scores 100).
# ---------------------------------------------------------------------------
# WARNING: zone engagement well below the store's busiest zone.
DEAD_ZONE_WARNING_SCORE = 20.0
# CRITICAL: zone is effectively unused relative to peak traffic areas.
DEAD_ZONE_CRITICAL_SCORE = 10.0

# Operational recommendations aligned with challenge PDF anomaly responses.
SUGGESTED_ACTION_QUEUE_SPIKE = (
    "Deploy additional billing staff or open express checkout lanes to reduce wait times."
)
SUGGESTED_ACTION_CONVERSION_DROP = (
    "Investigate checkout friction, pricing displays, and POS availability at billing counters."
)
SUGGESTED_ACTION_DEAD_ZONE = (
    "Review planogram, signage, and staffing for the underperforming zone; consider promotions."
)


def _anomaly_detected_at(detected_at: datetime | None) -> datetime:
    """UTC timestamp attached to each anomaly (request time by default)."""
    if detected_at is not None:
        if detected_at.tzinfo is None:
            return detected_at.replace(tzinfo=timezone.utc)
        return detected_at.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def count_non_staff_queue_joins(
    events: Sequence[EventRecord],
    staff_ids: frozenset[str],
) -> int:
    """Count BILLING_QUEUE_JOIN events excluding staff detections."""
    return count_customer_queue_joins(events, staff_ids)


def detect_queue_spike(
    queue_joins: int,
    *,
    detected_at: datetime | None = None,
) -> Anomaly | None:
    """Flag unusually high billing queue join volume for the day."""
    when = _anomaly_detected_at(detected_at)
    if queue_joins >= QUEUE_SPIKE_CRITICAL_JOINS:
        return Anomaly(
            anomaly_type=ANOMALY_QUEUE_SPIKE,
            severity=AnomalySeverity.CRITICAL,
            title="Critical billing queue spike detected",
            description=(
                f"Queue joins ({queue_joins}) exceed the critical threshold "
                f"of {QUEUE_SPIKE_CRITICAL_JOINS} for the day."
            ),
            suggested_action=SUGGESTED_ACTION_QUEUE_SPIKE,
            detected_at=when,
            supporting_metrics={"queue_joins": queue_joins},
        )

    if queue_joins >= QUEUE_SPIKE_WARNING_JOINS:
        return Anomaly(
            anomaly_type=ANOMALY_QUEUE_SPIKE,
            severity=AnomalySeverity.WARN,
            title="Billing queue spike detected",
            description=(
                f"Queue joins ({queue_joins}) exceed the warning threshold "
                f"of {QUEUE_SPIKE_WARNING_JOINS} for the day."
            ),
            suggested_action=SUGGESTED_ACTION_QUEUE_SPIKE,
            detected_at=when,
            supporting_metrics={"queue_joins": queue_joins},
        )

    return None


def detect_conversion_drop(
    sessions: list,
    transactions: list[PosTransactionRecord],
    *,
    detected_at: datetime | None = None,
) -> Anomaly | None:
    """
    Flag low conversion when visitors reached billing but POS correlation is weak.

    Uses compute_conversion_rate() from metrics (unchanged North Star formula).
    Skipped when no non-staff visitors reached billing — zero conversions
    without billing traffic is not a meaningful drop signal.
    """
    billing_visitors = visitors_reached_billing(sessions)
    if not billing_visitors:
        return None

    when = _anomaly_detected_at(detected_at)
    unique_visitors = count_unique_visitors(sessions)
    converted_count = len(converted_visitor_ids(sessions, transactions))
    conversion_rate = compute_conversion_rate(sessions, transactions)

    metrics = {
        "conversion_rate": round(conversion_rate, 4),
        "unique_visitors": unique_visitors,
        "converted_visitors": converted_count,
        "visitors_reached_billing": len(billing_visitors),
    }

    if conversion_rate < CONVERSION_DROP_CRITICAL_RATE:
        return Anomaly(
            anomaly_type=ANOMALY_CONVERSION_DROP,
            severity=AnomalySeverity.CRITICAL,
            title="Critical conversion drop detected",
            description=(
                f"Conversion rate ({conversion_rate:.1%}) is below the critical "
                f"threshold of {CONVERSION_DROP_CRITICAL_RATE:.0%} despite "
                f"{len(billing_visitors)} visitor(s) reaching billing."
            ),
            suggested_action=SUGGESTED_ACTION_CONVERSION_DROP,
            detected_at=when,
            supporting_metrics=metrics,
        )

    if conversion_rate < CONVERSION_DROP_WARNING_RATE:
        return Anomaly(
            anomaly_type=ANOMALY_CONVERSION_DROP,
            severity=AnomalySeverity.WARN,
            title="Conversion drop detected",
            description=(
                f"Conversion rate ({conversion_rate:.1%}) is below the warning "
                f"threshold of {CONVERSION_DROP_WARNING_RATE:.0%} despite "
                f"{len(billing_visitors)} visitor(s) reaching billing."
            ),
            suggested_action=SUGGESTED_ACTION_CONVERSION_DROP,
            detected_at=when,
            supporting_metrics=metrics,
        )

    return None


def detect_dead_zones(
    zones: Sequence[HeatmapZone],
    *,
    detected_at: datetime | None = None,
) -> list[Anomaly]:
    """
    Flag zones with extremely low heatmap engagement vs the store peak zone.

    Requires at least two zones with activity; otherwise relative comparison
    is undefined (single zone always normalizes to 100).
    """
    if len(zones) < 2:
        return []

    when = _anomaly_detected_at(detected_at)
    anomalies: list[Anomaly] = []
    for zone in zones:
        if zone.zone_id.upper() == BILLING_ZONE_ID:
            continue
        score = zone.normalized_score
        if score < DEAD_ZONE_CRITICAL_SCORE:
            anomalies.append(
                Anomaly(
                    anomaly_type=ANOMALY_DEAD_ZONE,
                    severity=AnomalySeverity.CRITICAL,
                    title=f"Critical dead zone: {zone.zone_id}",
                    description=(
                        f"Zone {zone.zone_id} normalized engagement score "
                        f"({score:.1f}) is below the critical threshold of "
                        f"{DEAD_ZONE_CRITICAL_SCORE}."
                    ),
                    suggested_action=SUGGESTED_ACTION_DEAD_ZONE,
                    detected_at=when,
                    supporting_metrics={
                        "zone_id": zone.zone_id,
                        "normalized_score": round(score, 2),
                        "visit_count": zone.visit_count,
                        "unique_visitors": zone.unique_visitors,
                        "total_dwell_time_ms": zone.total_dwell_time_ms,
                    },
                )
            )
        elif score < DEAD_ZONE_WARNING_SCORE:
            anomalies.append(
                Anomaly(
                    anomaly_type=ANOMALY_DEAD_ZONE,
                    severity=AnomalySeverity.WARN,
                    title=f"Dead zone: {zone.zone_id}",
                    description=(
                        f"Zone {zone.zone_id} normalized engagement score "
                        f"({score:.1f}) is below the warning threshold of "
                        f"{DEAD_ZONE_WARNING_SCORE}."
                    ),
                    suggested_action=SUGGESTED_ACTION_DEAD_ZONE,
                    detected_at=when,
                    supporting_metrics={
                        "zone_id": zone.zone_id,
                        "normalized_score": round(score, 2),
                        "visit_count": zone.visit_count,
                        "unique_visitors": zone.unique_visitors,
                        "total_dwell_time_ms": zone.total_dwell_time_ms,
                    },
                )
            )

    return anomalies


def detect_store_anomalies(
    events: list[EventRecord],
    transactions: list[PosTransactionRecord],
    *,
    detected_at: datetime | None = None,
) -> list[Anomaly]:
    """Run all anomaly detectors and return ordered results."""
    sessions, _classifications, staff_ids = build_sessions_for_analytics(events)
    queue_joins = count_non_staff_queue_joins(events, staff_ids)
    aggregates = aggregate_zone_stats(sessions)
    heatmap_zones = build_heatmap_zones(aggregates)

    anomalies: list[Anomaly] = []

    queue_anomaly = detect_queue_spike(queue_joins, detected_at=detected_at)
    if queue_anomaly is not None:
        anomalies.append(queue_anomaly)

    conversion_anomaly = detect_conversion_drop(
        sessions, transactions, detected_at=detected_at
    )
    if conversion_anomaly is not None:
        anomalies.append(conversion_anomaly)

    anomalies.extend(detect_dead_zones(heatmap_zones, detected_at=detected_at))

    return anomalies


def compute_store_anomalies(
    store_id: str,
    metric_date: date,
    events: list[EventRecord],
    transactions: list[PosTransactionRecord],
) -> StoreAnomaliesResponse:
    """Derive anomaly list from events and POS rows for one store and UTC day."""
    return StoreAnomaliesResponse(
        store_id=store_id,
        date=metric_date.isoformat(),
        anomalies=detect_store_anomalies(events, transactions),
    )


@router.get(
    "/{store_id}/anomalies",
    response_model=StoreAnomaliesResponse,
    summary="Store anomaly alerts",
    description=(
        "Detects queue spikes, conversion drops, and dead zones using "
        "ingested events and POS data for a UTC calendar day."
    ),
    responses={
        503: {"description": "Database unavailable"},
        422: {"description": "Invalid date query parameter"},
    },
)
def get_store_anomalies(
    store_id: str,
    date_param: str | None = Query(
        default=None,
        alias="date",
        description="UTC calendar day (YYYY-MM-DD). Defaults to today (UTC).",
    ),
    db: Session = Depends(get_db),
) -> StoreAnomaliesResponse:
    """Compute store anomalies from ingested events and POS transactions."""
    if not is_database_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        )

    metric_date = parse_metric_date(date_param)

    try:
        events = fetch_store_events(db, store_id, day=metric_date)
        transactions = fetch_store_pos_transactions(db, store_id, day=metric_date)
        return compute_store_anomalies(store_id, metric_date, events, transactions)
    except SQLAlchemyError as exc:
        logger.exception("Database error computing anomalies for %s", store_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error while computing anomalies",
        ) from exc
