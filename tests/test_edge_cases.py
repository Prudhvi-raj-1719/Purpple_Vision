# PROMPT: Verify structured logging includes event_count on POST /events/ingest.
# CHANGES MADE: Ingest logging test; existing edge-case coverage retained.
"""Edge-case tests: empty store, staff-only clip, zero purchases, re-entry."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db import EventRecord, PosTransactionRecord, get_session
from app.health import compute_health_response

UTC = timezone.utc
STORE = "STORE_BLR_002"
DAY = "2026-03-03"


def _uuid() -> str:
    return str(uuid.uuid4())


def _record(
    event_id: str,
    event_type: str,
    *,
    visitor_id: str = "VIS_edge1",
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
        timestamp=datetime(2026, 3, 3, hour, minute, tzinfo=UTC),
        zone_id=zone_id,
        dwell_ms=dwell_ms,
        is_staff=is_staff,
        confidence=0.9,
        metadata_json=json.dumps(metadata or {}),
    )


def _persist(*events: EventRecord) -> None:
    session = get_session()
    try:
        session.add_all(events)
        session.commit()
    finally:
        session.close()


def _persist_pos(transaction_id: str, hour: int = 14, minute: int = 12) -> None:
    session = get_session()
    try:
        session.add(
            PosTransactionRecord(
                transaction_id=transaction_id,
                store_id=STORE,
                timestamp=datetime(2026, 3, 3, hour, minute, tzinfo=UTC),
                basket_value_inr=100.0,
            )
        )
        session.commit()
    finally:
        session.close()


class TestEmptyStore:
    def test_metrics_empty_store(self, client: TestClient) -> None:
        response = client.get(f"/stores/{STORE}/metrics?date={DAY}")
        assert response.status_code == 200
        body = response.json()
        assert body["unique_visitors"] == 0
        assert body["conversion_rate"] == 0.0
        assert body["total_sessions"] == 0

    def test_funnel_empty_store(self, client: TestClient) -> None:
        response = client.get(f"/stores/{STORE}/funnel?date={DAY}")
        assert response.status_code == 200
        assert all(stage["count"] == 0 for stage in response.json()["stages"])

    def test_heatmap_empty_store(self, client: TestClient) -> None:
        response = client.get(f"/stores/{STORE}/heatmap?date={DAY}")
        assert response.status_code == 200
        assert response.json()["zones"] == []

    def test_anomalies_empty_store(self, client: TestClient) -> None:
        response = client.get(f"/stores/{STORE}/anomalies?date={DAY}")
        assert response.status_code == 200
        assert response.json()["anomalies"] == []


class TestStaffOnlyTraffic:
    def test_metrics_exclude_staff(self, client: TestClient) -> None:
        _persist(
            _record("s1", "ENTRY", is_staff=True, hour=10),
            _record("s2", "ZONE_ENTER", zone_id="SKINCARE", is_staff=True, hour=10, minute=5),
            _record("s3", "EXIT", is_staff=True, hour=11),
        )
        response = client.get(f"/stores/{STORE}/metrics?date={DAY}")
        body = response.json()
        assert body["unique_visitors"] == 0
        assert body["total_sessions"] == 0

    def test_funnel_exclude_staff(self, client: TestClient) -> None:
        _persist(
            _record("s4", "ENTRY", is_staff=True, hour=10),
            _record(
                "s5",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                is_staff=True,
                hour=10,
                minute=5,
                metadata={"queue_depth": 1},
            ),
        )
        response = client.get(f"/stores/{STORE}/funnel?date={DAY}")
        counts = {s["stage"]: s["count"] for s in response.json()["stages"]}
        assert counts["unique_visitors"] == 0
        assert counts["reached_billing"] == 0


class TestZeroPurchases:
    def test_metrics_zero_conversion_without_pos(self, client: TestClient) -> None:
        _persist(
            _record("z1", "ENTRY", hour=14),
            _record(
                "z2",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                hour=14,
                minute=10,
                metadata={"queue_depth": 1},
            ),
            _record("z3", "EXIT", hour=14, minute=20),
        )
        response = client.get(f"/stores/{STORE}/metrics?date={DAY}")
        body = response.json()
        assert body["unique_visitors"] == 1
        assert body["conversion_rate"] == 0.0

    def test_anomalies_conversion_drop_with_billing_but_no_pos(
        self, client: TestClient
    ) -> None:
        _persist(
            _record("z4", "ENTRY", visitor_id="VIS_z4", hour=14),
            _record(
                "z5",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                visitor_id="VIS_z4",
                hour=14,
                minute=10,
                metadata={"queue_depth": 1},
            ),
            _record("z6", "EXIT", visitor_id="VIS_z4", hour=14, minute=20),
        )
        response = client.get(f"/stores/{STORE}/anomalies?date={DAY}")
        types = [a["anomaly_type"] for a in response.json()["anomalies"]]
        assert "CONVERSION_DROP" in types


class TestReentryScenarios:
    def test_metrics_reentry_single_unique_visitor(self, client: TestClient) -> None:
        _persist(
            _record("r1", "ENTRY", hour=10),
            _record("r2", "EXIT", hour=11),
            _record("r3", "REENTRY", hour=12),
            _record("r4", "EXIT", hour=13),
        )
        response = client.get(f"/stores/{STORE}/metrics?date={DAY}")
        body = response.json()
        assert body["unique_visitors"] == 1
        assert body["total_sessions"] == 2

    def test_funnel_reentry_does_not_double_count(self, client: TestClient) -> None:
        _persist(
            _record("r5", "ENTRY", hour=10),
            _record("r6", "EXIT", hour=11),
            _record("r7", "REENTRY", hour=12),
            _record("r8", "ZONE_ENTER", zone_id="SKINCARE", hour=12, minute=5),
            _record("r9", "EXIT", hour=13),
        )
        response = client.get(f"/stores/{STORE}/funnel?date={DAY}")
        counts = {s["stage"]: s["count"] for s in response.json()["stages"]}
        assert counts["unique_visitors"] == 1
        assert counts["reached_any_zone"] == 1


class TestIngestBatchLimits:
    def test_ingest_accepts_batch_of_500(self, client: TestClient) -> None:
        events = [
            {
                "event_id": _uuid(),
                "store_id": STORE,
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": f"VIS_batch{i}",
                "event_type": "ENTRY",
                "timestamp": "2026-03-03T14:00:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {"session_seq": 1},
            }
            for i in range(500)
        ]
        response = client.post("/events/ingest", json={"events": events})
        assert response.status_code == 200
        assert response.json()["events_ingested"] == 500

    def test_ingest_rejects_more_than_500_events(self, client: TestClient) -> None:
        events = [
            {
                "event_id": _uuid(),
                "store_id": STORE,
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": f"VIS_over{i}",
                "event_type": "ENTRY",
                "timestamp": "2026-03-03T14:00:00Z",
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.9,
                "metadata": {"session_seq": 1},
            }
            for i in range(501)
        ]
        response = client.post("/events/ingest", json={"events": events})
        assert response.status_code == 422


class TestStaleFeedDetection:
    def test_health_stale_feed_via_compute_health_response(self) -> None:
        from datetime import timedelta

        stale_time = datetime.now(UTC) - timedelta(minutes=30)
        session = get_session()
        try:
            session.add(
                EventRecord(
                    event_id="edge-stale-1",
                    store_id=STORE,
                    camera_id="CAM_ENTRY_01",
                    visitor_id="VIS_stale_edge",
                    event_type="ENTRY",
                    timestamp=datetime(2026, 3, 3, 8, 0, tzinfo=UTC),
                    zone_id=None,
                    dwell_ms=0,
                    is_staff=False,
                    confidence=0.9,
                    metadata_json="{}",
                    ingested_at=stale_time,
                )
            )
            session.commit()
            with patch("app.health.get_stale_feed_threshold_minutes", return_value=10):
                response = compute_health_response(session)
        finally:
            session.close()

        assert response.status == "degraded"
        assert any(w.startswith("STALE_FEED:") for w in response.warnings)
        assert response.stores[0].stale is True


class TestIngestLogging:
    def test_ingest_logs_event_count(self, client: TestClient) -> None:
        payload = {
            "events": [
                {
                    "event_id": "550e8400-e29b-41d4-a716-446655440099",
                    "store_id": STORE,
                    "camera_id": "CAM_ENTRY_01",
                    "visitor_id": "VIS_log1",
                    "event_type": "ENTRY",
                    "timestamp": "2026-03-03T14:00:00Z",
                    "zone_id": None,
                    "dwell_ms": 0,
                    "is_staff": False,
                    "confidence": 0.9,
                    "metadata": {"session_seq": 1},
                },
                {
                    "event_id": "550e8400-e29b-41d4-a716-446655440098",
                    "store_id": STORE,
                    "camera_id": "CAM_ENTRY_01",
                    "visitor_id": "VIS_log2",
                    "event_type": "ENTRY",
                    "timestamp": "2026-03-03T14:05:00Z",
                    "zone_id": None,
                    "dwell_ms": 0,
                    "is_staff": False,
                    "confidence": 0.9,
                    "metadata": {"session_seq": 1},
                },
            ]
        }
        with patch("app.logging_config.log_request") as mock_log:
            response = client.post("/events/ingest", json=payload)

        assert response.status_code == 200
        assert response.json()["total_received"] == 2
        mock_log.assert_called_once()
        assert mock_log.call_args.kwargs["event_count"] == 2
        assert mock_log.call_args.kwargs["endpoint"] == "/events/ingest"


class TestRequestLogging:
    def test_response_includes_trace_id_header(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert "X-Trace-Id" in response.headers
        assert len(response.headers["X-Trace-Id"]) > 0

    def test_store_endpoint_includes_trace_id(self, client: TestClient) -> None:
        response = client.get(f"/stores/{STORE}/metrics?date={DAY}")
        assert response.status_code == 200
        assert "X-Trace-Id" in response.headers
