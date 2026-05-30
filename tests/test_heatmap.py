# PROMPT: Verify heatmap data_confidence flag when fewer than 20 customer sessions.
# CHANGES MADE: Tests for data_confidence true/false on heatmap response.
"""Tests for store heatmap computation and GET /stores/{store_id}/heatmap."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.db import EventRecord, get_session
from app.heatmap import (
    MIN_SESSIONS_FOR_DATA_CONFIDENCE,
    ZoneAggregate,
    aggregate_zone_stats,
    build_heatmap_zones,
    compute_data_confidence,
    compute_engagement_scores,
    compute_store_heatmap,
    normalize_scores,
)
from app.sessions import build_sessions

UTC = timezone.utc
STORE = "STORE_BLR_002"
DAY = "2026-03-03"
METRIC_DATE = datetime(2026, 3, 3, tzinfo=UTC).date()


def _ts(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 3, 3, hour, minute, second, tzinfo=UTC)


def _record(
    event_id: str,
    event_type: str,
    *,
    visitor_id: str = "VIS_a1b2c3",
    zone_id: str | None = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    hour: int = 14,
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


def _persist_events(*events: EventRecord) -> None:
    session = get_session()
    try:
        session.add_all(events)
        session.commit()
    finally:
        session.close()


def _zone_map(zones: list[dict]) -> dict[str, dict]:
    return {zone["zone_id"]: zone for zone in zones}


class TestZoneAggregate:
    def test_average_dwell_zero_when_no_visits(self) -> None:
        agg = ZoneAggregate()
        assert agg.average_dwell_time_ms == 0.0

    def test_engagement_score_combines_visits_and_dwell(self) -> None:
        agg = ZoneAggregate(
            visit_count=2,
            total_dwell_time_ms=30_000,
        )
        assert agg.engagement_score() == 2 + 30.0


class TestNormalization:
    def test_highest_zone_scores_100(self) -> None:
        scores = {"A": 50.0, "B": 100.0, "C": 25.0}
        normalized = normalize_scores(scores)

        assert normalized["B"] == 100.0
        assert normalized["A"] == 50.0
        assert normalized["C"] == 25.0

    def test_all_zero_scores_normalize_to_zero(self) -> None:
        scores = {"A": 0.0, "B": 0.0}
        normalized = normalize_scores(scores)

        assert normalized == {"A": 0.0, "B": 0.0}

    def test_empty_scores_returns_empty(self) -> None:
        assert normalize_scores({}) == {}


class TestAggregateZoneStats:
    def test_aggregates_visits_dwell_and_unique_visitors(self) -> None:
        events = [
            _record("e1", "ENTRY", visitor_id="VIS_v1", hour=14),
            _record(
                "e2",
                "ZONE_ENTER",
                zone_id="SKINCARE",
                visitor_id="VIS_v1",
                hour=14,
                minute=5,
            ),
            _record(
                "e3",
                "ZONE_DWELL",
                zone_id="SKINCARE",
                dwell_ms=30_000,
                visitor_id="VIS_v1",
                hour=14,
                minute=6,
            ),
            _record("e4", "EXIT", visitor_id="VIS_v1", hour=14, minute=20),
            _record("e5", "ENTRY", visitor_id="VIS_v2", hour=15),
            _record(
                "e6",
                "ZONE_ENTER",
                zone_id="SKINCARE",
                visitor_id="VIS_v2",
                hour=15,
                minute=5,
            ),
            _record("e7", "EXIT", visitor_id="VIS_v2", hour=15, minute=15),
        ]
        sessions = build_sessions(events)
        aggregates = aggregate_zone_stats(sessions)

        assert "SKINCARE" in aggregates
        agg = aggregates["SKINCARE"]
        assert agg.visit_count == 2
        assert agg.unique_visitors == 2
        assert agg.total_dwell_time_ms == 30_000
        assert agg.average_dwell_time_ms == 15_000.0

    def test_zone_enter_without_dwell_has_zero_dwell(self) -> None:
        events = [
            _record("e1", "ENTRY", hour=14),
            _record("e2", "ZONE_ENTER", zone_id="ELECTRONICS", hour=14, minute=5),
            _record("e3", "EXIT", hour=14, minute=10),
        ]
        aggregates = aggregate_zone_stats(build_sessions(events))

        agg = aggregates["ELECTRONICS"]
        assert agg.visit_count == 1
        assert agg.total_dwell_time_ms == 0
        assert agg.average_dwell_time_ms == 0.0

    def test_staff_sessions_excluded(self) -> None:
        events = [
            _record("e1", "ENTRY", is_staff=True, hour=10),
            _record(
                "e2",
                "ZONE_ENTER",
                zone_id="SKINCARE",
                is_staff=True,
                hour=10,
                minute=5,
            ),
            _record("e3", "EXIT", is_staff=True, hour=11),
            _record("e4", "ENTRY", visitor_id="VIS_cust", hour=12),
            _record("e5", "EXIT", visitor_id="VIS_cust", hour=13),
        ]
        aggregates = aggregate_zone_stats(build_sessions(events))

        assert aggregates == {}

    def test_reentry_counts_second_visit_to_same_zone(self) -> None:
        events = [
            _record("e1", "ENTRY", visitor_id="VIS_a", hour=10),
            _record(
                "e2",
                "ZONE_ENTER",
                zone_id="SKINCARE",
                visitor_id="VIS_a",
                hour=10,
                minute=5,
            ),
            _record("e3", "EXIT", visitor_id="VIS_a", hour=11),
            _record("e4", "REENTRY", visitor_id="VIS_a", hour=12),
            _record(
                "e5",
                "ZONE_ENTER",
                zone_id="SKINCARE",
                visitor_id="VIS_a",
                hour=12,
                minute=5,
            ),
            _record("e6", "EXIT", visitor_id="VIS_a", hour=13),
        ]
        aggregates = aggregate_zone_stats(build_sessions(events))

        agg = aggregates["SKINCARE"]
        assert agg.visit_count == 2
        assert agg.unique_visitors == 1


class TestDataConfidence:
    def _session_events(self, visitor_id: str, index: int) -> list[EventRecord]:
        base_minute = index * 2
        return [
            _record(f"en{index}", "ENTRY", visitor_id=visitor_id, hour=10, minute=base_minute),
            _record(
                f"zx{index}",
                "ZONE_ENTER",
                zone_id="SKINCARE",
                visitor_id=visitor_id,
                hour=10,
                minute=base_minute + 1,
            ),
            _record(
                f"ex{index}",
                "EXIT",
                visitor_id=visitor_id,
                hour=10,
                minute=base_minute + 2,
            ),
        ]

    def test_data_confidence_false_below_threshold(self) -> None:
        events: list[EventRecord] = []
        for index in range(MIN_SESSIONS_FOR_DATA_CONFIDENCE - 1):
            events.extend(self._session_events(f"VIS_dc{index}", index))

        sessions = build_sessions(events)
        assert compute_data_confidence(sessions) is False

        result = compute_store_heatmap(STORE, METRIC_DATE, events)
        assert result.data_confidence is False

    def test_data_confidence_true_at_threshold(self) -> None:
        events: list[EventRecord] = []
        for index in range(MIN_SESSIONS_FOR_DATA_CONFIDENCE):
            events.extend(self._session_events(f"VIS_ok{index}", index))

        sessions = build_sessions(events)
        assert compute_data_confidence(sessions) is True

        result = compute_store_heatmap(STORE, METRIC_DATE, events)
        assert result.data_confidence is True


class TestHeatmapComputation:
    def test_happy_path_with_normalization(self) -> None:
        events = [
            _record("e1", "ENTRY", visitor_id="VIS_v1", hour=14),
            _record(
                "e2",
                "ZONE_ENTER",
                zone_id="SKINCARE",
                visitor_id="VIS_v1",
                hour=14,
                minute=5,
            ),
            _record(
                "e3",
                "ZONE_DWELL",
                zone_id="SKINCARE",
                dwell_ms=60_000,
                visitor_id="VIS_v1",
                hour=14,
                minute=6,
            ),
            _record(
                "e4",
                "ZONE_ENTER",
                zone_id="BILLING",
                visitor_id="VIS_v1",
                hour=14,
                minute=10,
            ),
            _record(
                "e5",
                "ZONE_DWELL",
                zone_id="BILLING",
                dwell_ms=30_000,
                visitor_id="VIS_v1",
                hour=14,
                minute=11,
            ),
            _record("e6", "EXIT", visitor_id="VIS_v1", hour=14, minute=20),
        ]
        result = compute_store_heatmap(STORE, METRIC_DATE, events)
        zones = _zone_map([z.model_dump() for z in result.zones])

        assert result.store_id == STORE
        assert result.date == DAY
        assert set(zones) == {"BILLING", "SKINCARE"}

        # SKINCARE: visit=1, dwell=60000 -> score = 1 + 60 = 61
        # BILLING: visit=1, dwell=30000 -> score = 1 + 30 = 31
        assert zones["SKINCARE"]["normalized_score"] == 100.0
        assert zones["BILLING"]["normalized_score"] == (31 / 61) * 100
        assert zones["SKINCARE"]["visit_count"] == 1
        assert zones["SKINCARE"]["total_dwell_time_ms"] == 60_000

    def test_empty_store_returns_empty_zones(self) -> None:
        result = compute_store_heatmap(STORE, METRIC_DATE, [])

        assert result.zones == []
        assert result.data_confidence is False

    def test_build_heatmap_zones_sorted_by_zone_id(self) -> None:
        aggregates = {
            "ZEBRA": ZoneAggregate(visit_count=1),
            "ALPHA": ZoneAggregate(visit_count=2),
        }
        zones = build_heatmap_zones(aggregates)

        assert [z.zone_id for z in zones] == ["ALPHA", "ZEBRA"]


class TestEngagementScores:
    def test_compute_engagement_scores_from_aggregates(self) -> None:
        aggregates = {
            "A": ZoneAggregate(visit_count=3, total_dwell_time_ms=10_000),
        }
        scores = compute_engagement_scores(aggregates)

        assert scores["A"] == 3 + 10.0


class TestHeatmapEndpoint:
    def test_get_heatmap_returns_json(self, client: TestClient) -> None:
        _persist_events(
            _record("e1", "ENTRY", visitor_id="VIS_api1", hour=14),
            _record(
                "e2",
                "ZONE_ENTER",
                zone_id="SKINCARE",
                visitor_id="VIS_api1",
                hour=14,
                minute=5,
            ),
            _record(
                "e3",
                "ZONE_DWELL",
                zone_id="SKINCARE",
                dwell_ms=30_000,
                visitor_id="VIS_api1",
                hour=14,
                minute=6,
            ),
            _record("e4", "EXIT", visitor_id="VIS_api1", hour=14, minute=20),
        )

        response = client.get(f"/stores/{STORE}/heatmap?date={DAY}")

        assert response.status_code == 200
        body = response.json()
        assert body["store_id"] == STORE
        assert body["date"] == DAY
        assert body["data_confidence"] is False
        assert len(body["zones"]) == 1
        zone = body["zones"][0]
        assert zone["zone_id"] == "SKINCARE"
        assert zone["visit_count"] == 1
        assert zone["unique_visitors"] == 1
        assert zone["total_dwell_time_ms"] == 30_000
        assert zone["normalized_score"] == 100.0

    def test_get_heatmap_empty_store(self, client: TestClient) -> None:
        response = client.get(f"/stores/{STORE}/heatmap?date={DAY}")

        assert response.status_code == 200
        assert response.json()["zones"] == []

    def test_get_heatmap_invalid_date_returns_422(self, client: TestClient) -> None:
        response = client.get(f"/stores/{STORE}/heatmap?date=not-a-date")

        assert response.status_code == 422

    def test_get_heatmap_returns_503_when_database_unavailable(
        self, client: TestClient
    ) -> None:
        with patch("app.heatmap.is_database_available", return_value=False):
            response = client.get(f"/stores/{STORE}/heatmap")

        assert response.status_code == 503

    def test_get_heatmap_returns_503_on_database_error(
        self, client: TestClient
    ) -> None:
        with patch(
            "app.heatmap.fetch_store_events",
            side_effect=SQLAlchemyError("boom"),
        ):
            response = client.get(f"/stores/{STORE}/heatmap?date={DAY}")

        assert response.status_code == 503
