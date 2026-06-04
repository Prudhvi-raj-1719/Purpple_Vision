"""Debug/demo endpoint for staff detection transparency."""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import fetch_store_events, get_db, is_database_available
from app.metrics import parse_metric_date
from app.sessions import build_sessions, count_unique_visitors, customer_sessions
from app.staff_detection import (
    REASON_EVENT_FLAGGED,
    REASON_HIGH_REENTRY,
    REASON_HIGH_SESSIONS,
    REASON_LONG_STORE_TIME,
    REASON_MANY_ZONES,
    STAFF_MIN_REENTRY_COUNT,
    STAFF_MIN_SESSION_COUNT,
    STAFF_MIN_STORE_TIME_SECONDS,
    STAFF_MIN_UNIQUE_ZONES,
    StaffClassification,
    aggregate_visitor_profiles,
    build_sessions_for_analytics,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stores", tags=["debug"])


class StaffAnalysisEvidence(BaseModel):
    """Concrete values used by the staff classifier."""

    model_config = ConfigDict(extra="forbid")

    total_store_time_seconds: int = Field(ge=0)
    session_count: int = Field(ge=0)
    reentry_count: int = Field(ge=0)
    unique_zones_visited: int = Field(ge=0)


class StaffAnalysisClassification(BaseModel):
    """One visitor staff classification record."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "visitor_id": "VIS_staff001",
                    "is_staff": True,
                    "staff_score": 4,
                    "evidence": {
                        "total_store_time_seconds": 2348,
                        "session_count": 4,
                        "reentry_count": 3,
                        "unique_zones_visited": 12,
                    },
                    "reasons": [
                        "Store time 2348s exceeded threshold 1800s",
                        "Re-entry count 3 met threshold 3",
                        "Visited 12 unique zones exceeding threshold 8",
                        "Session count 4 met threshold 4",
                    ],
                }
            ]
        },
    )

    visitor_id: str
    is_staff: bool
    staff_score: int = Field(ge=0)
    evidence: StaffAnalysisEvidence
    reasons: list[str] = Field(default_factory=list)


class StaffAnalysisSummary(BaseModel):
    """Before/after analytics impact from staff filtering."""

    model_config = ConfigDict(extra="forbid")

    raw_visitors: int = Field(
        ge=0,
        description="Distinct visitor_ids before staff filtering.",
    )
    staff_detected: int = Field(
        ge=0,
        description="Visitors classified as staff for this store-day.",
    )
    customer_visitors: int = Field(
        ge=0,
        description="Distinct non-staff visitors used in analytics.",
    )
    raw_sessions: int = Field(
        ge=0,
        description="Session count before staff filtering.",
    )
    customer_sessions: int = Field(
        ge=0,
        description="Non-staff sessions used in analytics.",
    )


class StaffAnalysisResponse(BaseModel):
    """GET /stores/{store_id}/staff-analysis response."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "store_id": "STORE_BLR_002",
                    "date": "2026-06-01",
                    "total_visitors": 130,
                    "staff_detected": 2,
                    "summary": {
                        "raw_visitors": 130,
                        "staff_detected": 2,
                        "customer_visitors": 128,
                        "raw_sessions": 161,
                        "customer_sessions": 153,
                    },
                    "classifications": [
                        {
                            "visitor_id": "VIS_staff001",
                            "is_staff": True,
                            "staff_score": 4,
                            "evidence": {
                                "total_store_time_seconds": 2348,
                                "session_count": 4,
                                "reentry_count": 3,
                                "unique_zones_visited": 12,
                            },
                            "reasons": [
                                "Store time 2348s exceeded threshold 1800s",
                                "Re-entry count 3 met threshold 3",
                                "Visited 12 unique zones exceeding threshold 8",
                                "Session count 4 met threshold 4",
                            ],
                        }
                    ],
                }
            ]
        },
    )

    store_id: str
    date: str = Field(description="UTC calendar day (YYYY-MM-DD).")
    total_visitors: int = Field(ge=0)
    staff_detected: int = Field(ge=0)
    summary: StaffAnalysisSummary
    classifications: list[StaffAnalysisClassification] = Field(default_factory=list)


def _sort_key(c: StaffClassification) -> tuple[int, str]:
    # staff_score descending, visitor_id ascending
    return (-c.staff_score, c.visitor_id)


def _explanatory_reasons(
    classification: StaffClassification, evidence: StaffAnalysisEvidence
) -> list[str]:
    reasons: list[str] = []
    for code in classification.reasons:
        if code == REASON_LONG_STORE_TIME:
            reasons.append(
                f"Store time {evidence.total_store_time_seconds}s exceeded threshold "
                f"{STAFF_MIN_STORE_TIME_SECONDS}s"
            )
        elif code == REASON_HIGH_REENTRY:
            reasons.append(
                f"Re-entry count {evidence.reentry_count} met threshold "
                f"{STAFF_MIN_REENTRY_COUNT}"
            )
        elif code == REASON_MANY_ZONES:
            reasons.append(
                f"Visited {evidence.unique_zones_visited} unique zones exceeding threshold "
                f"{STAFF_MIN_UNIQUE_ZONES}"
            )
        elif code == REASON_HIGH_SESSIONS:
            reasons.append(
                f"Session count {evidence.session_count} met threshold "
                f"{STAFF_MIN_SESSION_COUNT}"
            )
        elif code == REASON_EVENT_FLAGGED:
            reasons.append("Visitor was explicitly flagged as staff by the event pipeline")
        else:
            reasons.append(code)
    return reasons


@router.get(
    "/{store_id}/staff-analysis",
    response_model=StaffAnalysisResponse,
    summary="Debug staff detection analysis",
    description=(
        "Returns per-visitor staff classifications for a store on a UTC calendar day, "
        "plus a before/after summary showing how staff filtering affects visitor and "
        "session counts. Intended for demo/debug use only."
    ),
    response_model_exclude_none=True,
    responses={
        503: {"description": "Database unavailable"},
        422: {"description": "Invalid date query parameter"},
    },
)
def get_staff_analysis(
    store_id: str,
    date_param: str | None = Query(
        default=None,
        alias="date",
        description="UTC calendar day (YYYY-MM-DD). Defaults to today (UTC).",
    ),
    db: Session = Depends(get_db),
) -> StaffAnalysisResponse:
    if not is_database_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        )

    metric_date: date = parse_metric_date(date_param)

    try:
        events = fetch_store_events(db, store_id, day=metric_date)
        sessions, classifications, _staff_ids = build_sessions_for_analytics(events)
    except SQLAlchemyError as exc:
        logger.exception("Database error computing staff analysis for %s", store_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error while computing staff analysis",
        ) from exc

    raw_visitors = len({event.visitor_id for event in events})
    sorted_classifications = sorted(classifications, key=_sort_key)
    staff_detected = sum(1 for c in sorted_classifications if c.is_staff)
    customer_visitor_count = count_unique_visitors(sessions)
    raw_session_count = len(build_sessions(events))
    customer_session_count = len(customer_sessions(sessions))

    summary = StaffAnalysisSummary(
        raw_visitors=raw_visitors,
        staff_detected=staff_detected,
        customer_visitors=customer_visitor_count,
        raw_sessions=raw_session_count,
        customer_sessions=customer_session_count,
    )

    profiles = {p.visitor_id: p for p in aggregate_visitor_profiles(sessions, events)}

    response_classifications: list[StaffAnalysisClassification] = []
    for c in sorted_classifications:
        profile = profiles.get(c.visitor_id)
        if profile is None:
            evidence = StaffAnalysisEvidence(
                total_store_time_seconds=0,
                session_count=0,
                reentry_count=0,
                unique_zones_visited=0,
            )
        else:
            evidence = StaffAnalysisEvidence(
                total_store_time_seconds=int(round(profile.total_store_time_seconds)),
                session_count=profile.session_count,
                reentry_count=profile.reentry_count,
                unique_zones_visited=profile.unique_zones_visited,
            )

        response_classifications.append(
            StaffAnalysisClassification(
                visitor_id=c.visitor_id,
                is_staff=c.is_staff,
                staff_score=c.staff_score,
                evidence=evidence,
                reasons=_explanatory_reasons(c, evidence),
            )
        )

    return StaffAnalysisResponse(
        store_id=store_id,
        date=metric_date.isoformat(),
        total_visitors=raw_visitors,
        staff_detected=staff_detected,
        summary=summary,
        classifications=response_classifications,
    )

