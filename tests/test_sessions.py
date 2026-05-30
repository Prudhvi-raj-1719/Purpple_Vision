"""Tests for visitor session building from ingested events."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db import EventRecord
from app.models import Event, EventMetadata, EventType
from app.sessions import (
    build_sessions,
    count_unique_visitors,
    customer_sessions,
)

UTC = timezone.utc
STORE = "STORE_BLR_002"
VISITOR = "VIS_a1b2c3"


def _ts(minute: int, second: int = 0) -> datetime:
    return datetime(2026, 3, 3, 14, minute, second, tzinfo=UTC)


def _record(
    event_id: str,
    event_type: str,
    *,
    visitor_id: str = VISITOR,
    zone_id: str | None = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    minute: int = 0,
    second: int = 0,
    metadata: dict | None = None,
) -> EventRecord:
    return EventRecord(
        event_id=event_id,
        store_id=STORE,
        camera_id="CAM_ENTRY_01",
        visitor_id=visitor_id,
        event_type=event_type,
        timestamp=_ts(minute, second),
        zone_id=zone_id,
        dwell_ms=dwell_ms,
        is_staff=is_staff,
        confidence=0.9,
        metadata_json=json.dumps(metadata or {}),
    )


def _event(
    event_id: str,
    event_type: EventType,
    *,
    visitor_id: str = VISITOR,
    zone_id: str | None = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    minute: int = 0,
    second: int = 0,
    queue_depth: int | None = None,
) -> Event:
    metadata = EventMetadata()
    if queue_depth is not None:
        metadata = EventMetadata(queue_depth=queue_depth)
    return Event(
        event_id=event_id,
        store_id=STORE,
        camera_id="CAM_ENTRY_01",
        visitor_id=visitor_id,
        event_type=event_type,
        timestamp=_ts(minute, second),
        zone_id=zone_id,
        dwell_ms=dwell_ms,
        is_staff=is_staff,
        confidence=0.9,
        metadata=metadata,
    )


class TestEntryExit:
    def test_entry_then_exit_opens_and_closes_session(self) -> None:
        events = [
            _record("e1", "ENTRY", minute=22, second=10),
            _record("e2", "ZONE_ENTER", zone_id="SKINCARE", minute=23),
            _record("e3", "EXIT", minute=30),
        ]

        sessions = build_sessions(events)

        assert len(sessions) == 1
        session = sessions[0]
        assert session.start_event_type == EventType.ENTRY
        assert session.is_open is False
        assert session.ended_at == _ts(30)
        assert session.event_count == 3
        assert session.zones_visited == {"SKINCARE"}
        assert session.is_staff is False


class TestReentry:
    def test_entry_exit_reentry_exit_creates_two_sessions_same_visitor(self) -> None:
        events = [
            _record("e1", "ENTRY", minute=10),
            _record("e2", "EXIT", minute=20),
            _record("e3", "REENTRY", minute=25),
            _record("e4", "EXIT", minute=40),
        ]

        sessions = build_sessions(events)

        assert len(sessions) == 2
        assert sessions[0].start_event_type == EventType.ENTRY
        assert sessions[1].start_event_type == EventType.REENTRY
        assert sessions[0].visitor_id == sessions[1].visitor_id == VISITOR
        assert sessions[0].is_open is False
        assert sessions[1].is_open is False
        assert count_unique_visitors(sessions) == 1


class TestStaffSession:
    def test_staff_session_retained_and_flagged(self) -> None:
        events = [
            _record("e1", "ENTRY", minute=10, is_staff=True),
            _record("e2", "ZONE_ENTER", zone_id="SKINCARE", minute=11, is_staff=True),
            _record("e3", "EXIT", minute=15, is_staff=True),
        ]

        sessions = build_sessions(events)

        assert len(sessions) == 1
        assert sessions[0].is_staff is True
        assert count_unique_visitors(sessions) == 0
        assert customer_sessions(sessions) == []


class TestOrphanEvents:
    def test_orphan_exit_is_ignored(self) -> None:
        events = [_record("e1", "EXIT", minute=10)]

        sessions = build_sessions(events)

        assert sessions == []

    def test_orphan_reentry_opens_session(self) -> None:
        events = [
            _record("e1", "REENTRY", minute=10),
            _record("e2", "EXIT", minute=15),
        ]

        sessions = build_sessions(events)

        assert len(sessions) == 1
        assert sessions[0].start_event_type == EventType.REENTRY
        assert sessions[0].is_open is False


class TestDwellAggregation:
    def test_zone_dwell_accumulates_by_zone(self) -> None:
        events = [
            _record("e1", "ENTRY", minute=10),
            _record("e2", "ZONE_DWELL", zone_id="SKINCARE", dwell_ms=30_000, minute=11),
            _record("e3", "ZONE_DWELL", zone_id="SKINCARE", dwell_ms=30_000, minute=12),
            _record("e4", "ZONE_DWELL", zone_id="BILLING", dwell_ms=30_000, minute=13),
            _record("e5", "EXIT", minute=20),
        ]

        sessions = build_sessions(events)

        assert len(sessions) == 1
        session = sessions[0]
        assert session.total_dwell_ms_by_zone == {
            "SKINCARE": 60_000,
            "BILLING": 30_000,
        }
        assert session.zones_visited == {"SKINCARE", "BILLING"}
        assert session.reached_billing is True


class TestBillingQueue:
    def test_billing_queue_join_and_abandon(self) -> None:
        events = [
            _record("e1", "ENTRY", minute=10),
            _record(
                "e2",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                minute=15,
                metadata={"queue_depth": 2},
            ),
            _record("e3", "BILLING_QUEUE_ABANDON", zone_id="BILLING", minute=18),
            _record("e4", "EXIT", minute=20),
        ]

        sessions = build_sessions(events)

        assert len(sessions) == 1
        session = sessions[0]
        assert session.reached_billing is True
        assert session.joined_queue is True
        assert session.abandoned_queue is True
        assert "BILLING" in session.zones_visited

    def test_billing_reached_via_zone_enter(self) -> None:
        events = [
            _event("550e8400-e29b-41d4-a716-446655440000", EventType.ENTRY, minute=10),
            _event(
                "6ba7b811-9dad-41d4-a716-446655440001",
                EventType.ZONE_ENTER,
                zone_id="BILLING",
                minute=12,
            ),
            _event(
                "6ba7b812-9dad-41d4-a716-446655440002",
                EventType.EXIT,
                minute=20,
            ),
        ]

        sessions = build_sessions(events)

        assert len(sessions) == 1
        assert sessions[0].reached_billing is True
        assert sessions[0].joined_queue is False


class TestEventOrdering:
    def test_events_sorted_by_timestamp_not_input_order(self) -> None:
        events = [
            _record("e3", "EXIT", minute=30),
            _record("e1", "ENTRY", minute=10),
            _record("e2", "ZONE_ENTER", zone_id="SKINCARE", minute=20),
        ]

        sessions = build_sessions(events)

        assert len(sessions) == 1
        assert sessions[0].event_count == 3
        assert sessions[0].zones_visited == {"SKINCARE"}
