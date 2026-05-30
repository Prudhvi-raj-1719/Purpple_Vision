"""Tests for GET /health endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db import EventRecord, get_session
from app.health import build_store_feed_statuses, compute_health_response

UTC = timezone.utc
STORE = "STORE_BLR_002"


def test_health_returns_ok_when_database_available(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database_available"] is True
    assert "timestamp" in body
    assert body["stores"] == []
    assert body["warnings"] == []


def test_health_returns_degraded_when_database_unavailable(client: TestClient) -> None:
    with patch("app.health.is_database_available", return_value=False):
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database_available"] is False
    assert "database_unavailable" in body["warnings"]


def test_health_includes_per_store_last_event_at(client: TestClient) -> None:
    session = get_session()
    try:
        session.add(
            EventRecord(
                event_id="health-event-1",
                store_id=STORE,
                camera_id="CAM_ENTRY_01",
                visitor_id="VIS_health1",
                event_type="ENTRY",
                timestamp=datetime(2026, 3, 3, 14, 0, tzinfo=UTC),
                zone_id=None,
                dwell_ms=0,
                is_staff=False,
                confidence=0.9,
                metadata_json="{}",
                ingested_at=datetime.now(UTC),
            )
        )
        session.commit()
    finally:
        session.close()

    response = client.get("/health")

    assert response.status_code == 200
    stores = response.json()["stores"]
    assert len(stores) == 1
    assert stores[0]["store_id"] == STORE
    assert stores[0]["last_event_at"] is not None
    assert stores[0]["stale"] is False


def test_health_flags_stale_feed(client: TestClient) -> None:
    stale_time = datetime.now(UTC) - timedelta(minutes=30)
    session = get_session()
    try:
        session.add(
            EventRecord(
                event_id="health-stale-1",
                store_id=STORE,
                camera_id="CAM_ENTRY_01",
                visitor_id="VIS_stale1",
                event_type="ENTRY",
                timestamp=datetime(2026, 3, 3, 10, 0, tzinfo=UTC),
                zone_id=None,
                dwell_ms=0,
                is_staff=False,
                confidence=0.9,
                metadata_json="{}",
                ingested_at=stale_time,
            )
        )
        session.commit()
    finally:
        session.close()

    with patch("app.health.get_stale_feed_threshold_minutes", return_value=10):
        response = client.get("/health")

    body = response.json()
    assert body["status"] == "degraded"
    assert any(w.startswith("STALE_FEED:") for w in body["warnings"])
    assert body["stores"][0]["stale"] is True


def test_build_store_feed_statuses_marks_recent_feed_fresh() -> None:
    now = datetime.now(UTC)
    rows = [(STORE, now - timedelta(minutes=5), now - timedelta(minutes=1))]
    stores, warnings = build_store_feed_statuses(rows, now=now, threshold_minutes=10)

    assert stores[0].stale is False
    assert warnings == []
