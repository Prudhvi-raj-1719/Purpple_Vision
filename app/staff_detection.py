"""Heuristic staff detection from visitor event histories (analytics layer only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from app.db import EventRecord
from app.models import Event
from app.sessions import VisitorSession, build_sessions

# Conservative multi-signal thresholds (all signals must not fire alone).
STAFF_MIN_STORE_TIME_SECONDS = 1800
STAFF_MIN_REENTRY_COUNT = 3
STAFF_MIN_UNIQUE_ZONES = 8
STAFF_MIN_SESSION_COUNT = 4
STAFF_SCORE_THRESHOLD = 3

REASON_LONG_STORE_TIME = "long_store_time"
REASON_HIGH_REENTRY = "high_reentry_count"
REASON_MANY_ZONES = "many_zone_visits"
REASON_HIGH_SESSIONS = "high_session_count"
REASON_EVENT_FLAGGED = "event_flagged"


@dataclass(frozen=True)
class VisitorProfile:
    """Aggregated per-visitor activity for one store-day."""

    visitor_id: str
    first_seen: datetime
    last_seen: datetime
    total_store_time_seconds: float
    session_count: int
    reentry_count: int
    unique_zones_visited: int
    total_events: int


@dataclass(frozen=True)
class StaffClassification:
    """Transparent staff classification result for one visitor."""

    visitor_id: str
    is_staff: bool
    staff_score: int
    reasons: list[str] = field(default_factory=list)


def _normalize_event_row(event: EventRecord | Event | dict[str, Any]) -> dict[str, Any]:
    if isinstance(event, dict):
        return event
    if isinstance(event, Event):
        return {
            "visitor_id": event.visitor_id,
            "timestamp": event.timestamp,
            "is_staff": event.is_staff,
            "zone_id": event.zone_id,
            "event_type": event.event_type,
        }
    return {
        "visitor_id": event.visitor_id,
        "timestamp": event.timestamp,
        "is_staff": event.is_staff,
        "zone_id": event.zone_id,
        "event_type": event.event_type,
    }


def _visitor_last_timestamp(
    sessions: Sequence[VisitorSession],
    events: Sequence[EventRecord | Event | dict[str, Any]],
    visitor_id: str,
) -> datetime | None:
    latest: datetime | None = None
    for session in sessions:
        if session.visitor_id != visitor_id:
            continue
        for candidate in (session.ended_at, session.started_at):
            if candidate is not None and (latest is None or candidate > latest):
                latest = candidate
    for event in events:
        row = _normalize_event_row(event)
        if row["visitor_id"] != visitor_id:
            continue
        ts = row["timestamp"]
        if latest is None or ts > latest:
            latest = ts
    return latest


def aggregate_visitor_profiles(
    sessions: Sequence[VisitorSession],
    events: Sequence[EventRecord | Event | dict[str, Any]],
) -> list[VisitorProfile]:
    """Build per-visitor profiles from sessions and raw events for the same day."""
    visitor_ids = {session.visitor_id for session in sessions}
    for event in events:
        visitor_ids.add(_normalize_event_row(event)["visitor_id"])

    profiles: list[VisitorProfile] = []
    for visitor_id in sorted(visitor_ids):
        visitor_sessions = [s for s in sessions if s.visitor_id == visitor_id]
        visitor_events = [
            _normalize_event_row(e) for e in events if _normalize_event_row(e)["visitor_id"] == visitor_id
        ]

        if not visitor_sessions and not visitor_events:
            continue

        session_count = len(visitor_sessions)
        reentry_count = max(0, session_count - 1)

        zones: set[str] = set()
        for session in visitor_sessions:
            zones.update(session.zones_visited)
        for row in visitor_events:
            zone_id = row.get("zone_id")
            if zone_id:
                zones.add(zone_id)

        timestamps = [row["timestamp"] for row in visitor_events]
        timestamps.extend(s.started_at for s in visitor_sessions)
        timestamps.extend(s.ended_at for s in visitor_sessions if s.ended_at is not None)
        first_seen = min(timestamps)
        last_seen = max(timestamps)

        fallback_end = _visitor_last_timestamp(sessions, events, visitor_id) or last_seen
        total_store_time_seconds = 0.0
        for session in visitor_sessions:
            end = session.ended_at or fallback_end
            delta = (end - session.started_at).total_seconds()
            if delta > 0:
                total_store_time_seconds += delta

        profiles.append(
            VisitorProfile(
                visitor_id=visitor_id,
                first_seen=first_seen,
                last_seen=last_seen,
                total_store_time_seconds=round(total_store_time_seconds, 3),
                session_count=session_count,
                reentry_count=reentry_count,
                unique_zones_visited=len(zones),
                total_events=len(visitor_events),
            )
        )

    return profiles


def classify_staff_profiles(
    profiles: Sequence[VisitorProfile],
    events: Sequence[EventRecord | Event | dict[str, Any]],
) -> list[StaffClassification]:
    """
    Conservative staff classifier — requires staff_score >= STAFF_SCORE_THRESHOLD.

    Pipeline events with is_staff=True are always treated as staff (event_flagged).
    """
    event_staff_visitors = {
        _normalize_event_row(event)["visitor_id"]
        for event in events
        if _normalize_event_row(event)["is_staff"]
    }

    results: list[StaffClassification] = []
    for profile in profiles:
        score = 0
        reasons: list[str] = []

        if profile.total_store_time_seconds >= STAFF_MIN_STORE_TIME_SECONDS:
            score += 1
            reasons.append(REASON_LONG_STORE_TIME)

        if profile.reentry_count >= STAFF_MIN_REENTRY_COUNT:
            score += 1
            reasons.append(REASON_HIGH_REENTRY)

        if profile.unique_zones_visited >= STAFF_MIN_UNIQUE_ZONES:
            score += 1
            reasons.append(REASON_MANY_ZONES)

        if profile.session_count >= STAFF_MIN_SESSION_COUNT:
            score += 1
            reasons.append(REASON_HIGH_SESSIONS)

        is_staff = score >= STAFF_SCORE_THRESHOLD
        if profile.visitor_id in event_staff_visitors:
            is_staff = True
            if REASON_EVENT_FLAGGED not in reasons:
                reasons.append(REASON_EVENT_FLAGGED)

        results.append(
            StaffClassification(
                visitor_id=profile.visitor_id,
                is_staff=is_staff,
                staff_score=score,
                reasons=reasons,
            )
        )

    return results


def staff_visitor_ids(classifications: Sequence[StaffClassification]) -> frozenset[str]:
    """Distinct visitor_ids classified as staff."""
    return frozenset(c.visitor_id for c in classifications if c.is_staff)


def apply_staff_labels(
    sessions: Sequence[VisitorSession],
    classifications: Sequence[StaffClassification],
) -> None:
    """Mark sessions in-place when the visitor is classified as staff."""
    staff_ids = staff_visitor_ids(classifications)
    for session in sessions:
        if session.visitor_id in staff_ids:
            session.is_staff = True


def build_sessions_for_analytics(
    events: Sequence[EventRecord | Event | dict[str, Any]],
) -> tuple[list[VisitorSession], list[StaffClassification], frozenset[str]]:
    """
    Build sessions and overlay heuristic staff detection for analytics.

    Does not mutate stored events; only session.is_staff flags used downstream.
    """
    sessions = build_sessions(events)
    profiles = aggregate_visitor_profiles(sessions, events)
    classifications = classify_staff_profiles(profiles, events)
    apply_staff_labels(sessions, classifications)
    return sessions, classifications, staff_visitor_ids(classifications)


def is_customer_visitor(
    visitor_id: str,
    staff_ids: frozenset[str],
) -> bool:
    """True when the visitor is not classified as staff."""
    return visitor_id not in staff_ids


def count_customer_queue_joins(
    events: Sequence[EventRecord],
    staff_ids: frozenset[str],
) -> int:
    """Count BILLING_QUEUE_JOIN events for non-staff visitors."""
    return sum(
        1
        for event in events
        if event.event_type == "BILLING_QUEUE_JOIN"
        and is_customer_visitor(event.visitor_id, staff_ids)
    )
