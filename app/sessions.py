"""Visitor session lifecycle management derived from ingested events."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence
from uuid import uuid4

from app.db import EventRecord
from app.models import Event, EventType

# Canonical billing zone id from store_layout.json conventions.
BILLING_ZONE_ID = "BILLING"

_SESSION_OPENERS = frozenset({EventType.ENTRY, EventType.REENTRY})
_BILLING_EVENT_TYPES = frozenset(
    {EventType.BILLING_QUEUE_JOIN, EventType.BILLING_QUEUE_ABANDON}
)


@dataclass
class VisitorSession:
    """
    One contiguous in-store visit for a visitor_id.

    Opens on ENTRY or REENTRY, closes on EXIT. Built in-memory from event rows —
    not persisted to a separate database table.
    """

    session_id: str
    visitor_id: str
    store_id: str
    start_event_type: EventType
    start_event_id: str
    started_at: datetime
    ended_at: datetime | None = None
    is_open: bool = True
    is_staff: bool = False
    zones_visited: set[str] = field(default_factory=set)
    reached_billing: bool = False
    joined_queue: bool = False
    abandoned_queue: bool = False
    billing_activity_at: datetime | None = None
    total_dwell_ms_by_zone: dict[str, int] = field(default_factory=dict)
    event_count: int = 0


def build_sessions(events: Sequence[EventRecord | Event]) -> list[VisitorSession]:
    """
    Derive visitor sessions from chronological event records.

    Events are sorted by timestamp before processing. Multiple sessions may share
    the same visitor_id when REENTRY occurs after EXIT.
    """
    normalized = [_normalize_event(event) for event in events]
    normalized.sort(key=lambda item: item["timestamp"])

    sessions: list[VisitorSession] = []
    open_by_visitor: dict[str, VisitorSession] = {}

    for event in normalized:
        event_type: EventType = event["event_type"]
        visitor_id: str = event["visitor_id"]

        if event_type in _SESSION_OPENERS:
            _open_session(
                sessions=sessions,
                open_by_visitor=open_by_visitor,
                event=event,
                start_event_type=event_type,
            )
            continue

        session = open_by_visitor.get(visitor_id)
        if session is None:
            # Orphan EXIT / zone events without an open session are ignored.
            continue

        session.event_count += 1
        _apply_session_event(session, event)

        if event_type == EventType.EXIT:
            session.ended_at = event["timestamp"]
            session.is_open = False
            open_by_visitor.pop(visitor_id, None)

    return sessions


def _normalize_event(event: EventRecord | Event) -> dict[str, Any]:
    """Convert EventRecord or Pydantic Event to a uniform processing dict."""
    if isinstance(event, Event):
        return {
            "event_id": str(event.event_id),
            "store_id": event.store_id,
            "visitor_id": event.visitor_id,
            "event_type": event.event_type,
            "timestamp": event.timestamp,
            "zone_id": event.zone_id,
            "dwell_ms": event.dwell_ms,
            "is_staff": event.is_staff,
            "metadata": event.metadata.model_dump(exclude_none=True),
        }

    metadata = json.loads(event.metadata_json) if event.metadata_json else {}
    return {
        "event_id": event.event_id,
        "store_id": event.store_id,
        "visitor_id": event.visitor_id,
        "event_type": EventType(event.event_type),
        "timestamp": event.timestamp,
        "zone_id": event.zone_id,
        "dwell_ms": event.dwell_ms,
        "is_staff": event.is_staff,
        "metadata": metadata,
    }


def _open_session(
    *,
    sessions: list[VisitorSession],
    open_by_visitor: dict[str, VisitorSession],
    event: dict[str, Any],
    start_event_type: EventType,
) -> None:
    """Open a session on ENTRY or REENTRY, closing any stale open session first."""
    visitor_id = event["visitor_id"]

    existing = open_by_visitor.get(visitor_id)
    if existing is not None:
        existing.ended_at = event["timestamp"]
        existing.is_open = False
        open_by_visitor.pop(visitor_id, None)

    session = VisitorSession(
        session_id=str(uuid4()),
        visitor_id=visitor_id,
        store_id=event["store_id"],
        start_event_type=start_event_type,
        start_event_id=event["event_id"],
        started_at=event["timestamp"],
        is_staff=event["is_staff"],
        event_count=1,
    )
    sessions.append(session)
    open_by_visitor[visitor_id] = session


def _mark_billing_activity(session: VisitorSession, timestamp: datetime) -> None:
    """Record the first billing-zone interaction timestamp for POS correlation."""
    session.reached_billing = True
    if session.billing_activity_at is None:
        session.billing_activity_at = timestamp


def _apply_session_event(session: VisitorSession, event: dict[str, Any]) -> None:
    """Update session state for a non-threshold event."""
    event_type: EventType = event["event_type"]
    zone_id: str | None = event["zone_id"]
    timestamp: datetime = event["timestamp"]

    if event_type == EventType.ZONE_ENTER and zone_id:
        session.zones_visited.add(zone_id)
        if _is_billing_zone(zone_id):
            _mark_billing_activity(session, timestamp)

    elif event_type == EventType.ZONE_DWELL and zone_id:
        session.zones_visited.add(zone_id)
        session.total_dwell_ms_by_zone[zone_id] = (
            session.total_dwell_ms_by_zone.get(zone_id, 0) + event["dwell_ms"]
        )
        if _is_billing_zone(zone_id):
            _mark_billing_activity(session, timestamp)

    elif event_type == EventType.BILLING_QUEUE_JOIN:
        _mark_billing_activity(session, timestamp)
        session.joined_queue = True
        if zone_id:
            session.zones_visited.add(zone_id)

    elif event_type == EventType.BILLING_QUEUE_ABANDON:
        _mark_billing_activity(session, timestamp)
        session.abandoned_queue = True
        if zone_id:
            session.zones_visited.add(zone_id)

    # ZONE_EXIT: no session field updates per design report.


def _is_billing_zone(zone_id: str) -> bool:
    return zone_id.upper() == BILLING_ZONE_ID


def count_unique_visitors(sessions: Sequence[VisitorSession]) -> int:
    """Count distinct non-staff visitor_ids (REENTRY does not double-count)."""
    return len(
        {
            session.visitor_id
            for session in sessions
            if not session.is_staff
        }
    )


def customer_sessions(sessions: Sequence[VisitorSession]) -> list[VisitorSession]:
    """Return only non-staff sessions for downstream metrics."""
    return [session for session in sessions if not session.is_staff]
