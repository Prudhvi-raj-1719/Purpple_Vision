"""Zone visit frequency and dwell heatmap (normalized 0–100)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import EventRecord, fetch_store_events, get_db, is_database_available
from app.metrics import parse_metric_date
from app.models import HeatmapZone, StoreHeatmapResponse
from app.staff_detection import build_sessions_for_analytics
from app.sessions import (
    BILLING_ZONE_ID,
    VisitorSession,
    customer_sessions,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stores", tags=["heatmap"])

# Dwell milliseconds are scaled to seconds when computing engagement score.
DWELL_MS_TO_ENGAGEMENT_SECONDS = 1000.0

# PDF: heatmap comparisons are unreliable below this customer session count.
MIN_SESSIONS_FOR_DATA_CONFIDENCE = 20


@dataclass
class ZoneAggregate:
    """Mutable accumulator for per-zone heatmap statistics."""

    visit_count: int = 0
    unique_visitor_ids: set[str] = field(default_factory=set)
    total_dwell_time_ms: int = 0

    @property
    def unique_visitors(self) -> int:
        return len(self.unique_visitor_ids)

    @property
    def average_dwell_time_ms(self) -> float:
        if self.visit_count == 0:
            return 0.0
        return self.total_dwell_time_ms / self.visit_count

    def engagement_score(self) -> float:
        """Combine visit frequency and dwell for normalization."""
        return self.visit_count + (self.total_dwell_time_ms / DWELL_MS_TO_ENGAGEMENT_SECONDS)


def is_product_zone(zone_id: str) -> bool:
    """Product/browse zones only — checkout (BILLING) uses queue metrics elsewhere."""
    return zone_id.upper() != BILLING_ZONE_ID


def aggregate_zone_stats(sessions: Sequence[VisitorSession]) -> dict[str, ZoneAggregate]:
    """
    Build per-zone stats from customer sessions.

    Each session contributes at most one visit per zone (from zones_visited).
    Dwell is summed from session.total_dwell_ms_by_zone.
    BILLING is excluded; checkout is measured via queue and conversion metrics.
    """
    aggregates: dict[str, ZoneAggregate] = {}

    for session in customer_sessions(sessions):
        for zone_id in session.zones_visited:
            if not is_product_zone(zone_id):
                continue
            zone = aggregates.setdefault(zone_id, ZoneAggregate())
            zone.visit_count += 1
            zone.unique_visitor_ids.add(session.visitor_id)
            zone.total_dwell_time_ms += session.total_dwell_ms_by_zone.get(zone_id, 0)

    return aggregates


def compute_engagement_scores(
    aggregates: dict[str, ZoneAggregate],
) -> dict[str, float]:
    """Raw engagement score per zone before normalization."""
    return {zone_id: agg.engagement_score() for zone_id, agg in aggregates.items()}


def normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    """
    Scale engagement scores to 0–100.

    The highest-scoring zone receives 100; others are proportional.
    When all scores are zero, every zone receives 0.
    """
    if not scores:
        return {}

    max_score = max(scores.values())
    if max_score == 0.0:
        return {zone_id: 0.0 for zone_id in scores}

    return {
        zone_id: (score / max_score) * 100.0 for zone_id, score in scores.items()
    }


def compute_data_confidence(sessions: Sequence[VisitorSession]) -> bool:
    """True when at least 20 customer sessions exist (PDF heatmap reliability gate)."""
    return len(customer_sessions(sessions)) >= MIN_SESSIONS_FOR_DATA_CONFIDENCE


def build_heatmap_zones(aggregates: dict[str, ZoneAggregate]) -> list[HeatmapZone]:
    """Convert aggregates to response models with normalized scores."""
    scores = compute_engagement_scores(aggregates)
    normalized = normalize_scores(scores)

    zones: list[HeatmapZone] = []
    for zone_id in sorted(aggregates):
        agg = aggregates[zone_id]
        zones.append(
            HeatmapZone(
                zone_id=zone_id,
                visit_count=agg.visit_count,
                unique_visitors=agg.unique_visitors,
                total_dwell_time_ms=agg.total_dwell_time_ms,
                average_dwell_time_ms=agg.average_dwell_time_ms,
                normalized_score=normalized[zone_id],
            )
        )

    return zones


def compute_store_heatmap(
    store_id: str,
    metric_date: date,
    events: list[EventRecord],
) -> StoreHeatmapResponse:
    """Derive zone heatmap from events for one store and UTC day."""
    sessions, _, _staff_ids = build_sessions_for_analytics(events)
    aggregates = aggregate_zone_stats(sessions)

    return StoreHeatmapResponse(
        store_id=store_id,
        date=metric_date.isoformat(),
        zones=build_heatmap_zones(aggregates),
        data_confidence=compute_data_confidence(sessions),
    )


@router.get(
    "/{store_id}/heatmap",
    response_model=StoreHeatmapResponse,
    summary="Store zone heatmap",
    description=(
        "Returns per-zone visit counts, unique visitors, dwell totals, and "
        "engagement scores normalized to 0–100 for a UTC calendar day."
    ),
    responses={
        503: {"description": "Database unavailable"},
        422: {"description": "Invalid date query parameter"},
    },
)
def get_store_heatmap(
    store_id: str,
    date_param: str | None = Query(
        default=None,
        alias="date",
        description="UTC calendar day (YYYY-MM-DD). Defaults to today (UTC).",
    ),
    db: Session = Depends(get_db),
) -> StoreHeatmapResponse:
    """Compute store heatmap from ingested events."""
    if not is_database_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        )

    metric_date = parse_metric_date(date_param)

    try:
        events = fetch_store_events(db, store_id, day=metric_date)
        return compute_store_heatmap(store_id, metric_date, events)
    except SQLAlchemyError as exc:
        logger.exception("Database error computing heatmap for %s", store_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error while computing heatmap",
        ) from exc
