"""Tests for heuristic staff detection."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db import EventRecord
from app.sessions import build_sessions, customer_sessions, count_unique_visitors
from app.staff_detection import (
    REASON_HIGH_REENTRY,
    REASON_LONG_STORE_TIME,
    REASON_MANY_ZONES,
    STAFF_SCORE_THRESHOLD,
    aggregate_visitor_profiles,
    build_sessions_for_analytics,
    classify_staff_profiles,
)

UTC = timezone.utc
STORE = "STORE_BLR_002"


def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 1, hour, minute, 0, tzinfo=UTC)


def _record(
    event_id: str,
    event_type: str,
    *,
    visitor_id: str,
    zone_id: str | None = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    hour: int = 10,
    minute: int = 0,
    metadata: dict | None = None,
) -> EventRecord:
    return EventRecord(
        event_id=event_id,
        store_id=STORE,
        camera_id="CAM_ENTRY_01",
        visitor_id=visitor_id,
        event_type=event_type,
        timestamp=_ts(hour, minute),
        zone_id=zone_id,
        dwell_ms=dwell_ms,
        is_staff=is_staff,
        confidence=0.9,
        metadata_json=json.dumps(metadata or {}),
    )


def _entry(visitor_id: str, hour: int, *, is_staff: bool = False) -> EventRecord:
    return _record(
        f"e-{visitor_id}-entry-{hour}",
        "ENTRY",
        visitor_id=visitor_id,
        is_staff=is_staff,
        hour=hour,
    )


def _exit(visitor_id: str, hour: int, minute: int = 30) -> EventRecord:
    return _record(
        f"e-{visitor_id}-exit-{hour}",
        "EXIT",
        visitor_id=visitor_id,
        hour=hour,
        minute=minute,
    )


def _dwell(visitor_id: str, zone: str, hour: int) -> EventRecord:
    return _record(
        f"e-{visitor_id}-{zone}-{hour}",
        "ZONE_DWELL",
        visitor_id=visitor_id,
        zone_id=zone,
        dwell_ms=45_000,
        hour=hour,
        minute=10,
        metadata={"sku_zone": zone},
    )


class TestStaffDetection:
    def test_single_signal_does_not_classify_staff(self) -> None:
        events = [
            _entry("VIS_0001", 10),
            _dwell("VIS_0001", "GOODVIBES", 10),
            _exit("VIS_0001", 11),
        ]
        sessions = build_sessions(events)
        profiles = aggregate_visitor_profiles(sessions, events)
        result = classify_staff_profiles(profiles, events)[0]

        assert result.is_staff is False
        assert result.staff_score < STAFF_SCORE_THRESHOLD

    def test_three_signals_classify_staff(self) -> None:
        visitor = "VIS_staff"
        zones = [
            "GOODVIBES",
            "PILGRIM",
            "LAKME",
            "DERMACO",
            "MAYBELLINE",
            "FACESCANADA",
            "MINIMALIST",
            "AQUOLOGICA",
        ]
        events: list[EventRecord] = []
        hour = 8
        for _cycle in range(4):
            events.append(_entry(visitor, hour))
            for zone in zones:
                events.append(_dwell(visitor, zone, hour))
            events.append(_exit(visitor, hour + 1))
            hour += 2

        sessions, classifications, staff_ids = build_sessions_for_analytics(events)
        staff = next(c for c in classifications if c.visitor_id == visitor)

        assert staff.is_staff is True
        assert staff.staff_score >= STAFF_SCORE_THRESHOLD
        assert REASON_LONG_STORE_TIME in staff.reasons
        assert REASON_HIGH_REENTRY in staff.reasons
        assert REASON_MANY_ZONES in staff.reasons
        assert visitor in staff_ids
        assert customer_sessions(sessions) == []
        assert count_unique_visitors(sessions) == 0

    def test_event_flagged_staff_always_excluded(self) -> None:
        events = [
            _entry("VIS_flagged", 10, is_staff=True),
            _exit("VIS_flagged", 10),
        ]
        _, classifications, staff_ids = build_sessions_for_analytics(events)
        staff = classifications[0]

        assert staff.is_staff is True
        assert "event_flagged" in staff.reasons
        assert "VIS_flagged" in staff_ids

    def test_reentry_count_is_session_count_minus_one(self) -> None:
        visitor = "VIS_re"
        events = [
            _entry(visitor, 9),
            _exit(visitor, 10),
            _entry(visitor, 11),
            _exit(visitor, 12),
            _entry(visitor, 13),
            _exit(visitor, 14),
        ]
        sessions = build_sessions(events)
        profile = aggregate_visitor_profiles(sessions, events)[0]

        assert profile.session_count == 3
        assert profile.reentry_count == 2
