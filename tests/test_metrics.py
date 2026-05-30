# PROMPT: Verify store metrics match the challenge PDF (per-zone dwell, queue depth).
# CHANGES MADE: Tests for average_dwell_by_zone and current_queue_depth on metrics API.
"""Tests for store metrics computation and GET /stores/{store_id}/metrics."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.db import EventRecord, PosTransactionRecord, get_session
from app.metrics import (
    compute_average_dwell_by_zone,
    compute_average_dwell_time_ms,
    compute_billing_reach_rate,
    compute_conversion_rate,
    compute_current_queue_depth,
    compute_queue_abandonment_rate,
    compute_store_metrics,
)
from app.pos_correlation import is_session_converted
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


def _pos(
    transaction_id: str,
    *,
    hour: int = 14,
    minute: int = 5,
    store_id: str = STORE,
    amount: float = 500.0,
) -> PosTransactionRecord:
    return PosTransactionRecord(
        transaction_id=transaction_id,
        store_id=store_id,
        timestamp=_ts(hour, minute),
        basket_value_inr=amount,
    )


def _persist_events(*events: EventRecord) -> None:
    session = get_session()
    try:
        session.add_all(events)
        session.commit()
    finally:
        session.close()


def _persist_pos(*transactions: PosTransactionRecord) -> None:
    session = get_session()
    try:
        session.add_all(transactions)
        session.commit()
    finally:
        session.close()


def _ingest(client: TestClient, events: list[dict]) -> None:
    response = client.post("/events/ingest", json={"events": events})
    assert response.status_code == 200


def _event_payload(
    event_id: str,
    event_type: str,
    *,
    visitor_id: str = "VIS_a1b2c3",
    zone_id: str | None = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    hour: int = 14,
    minute: int = 0,
    queue_depth: int | None = None,
) -> dict:
    metadata: dict = {"session_seq": 1}
    if queue_depth is not None:
        metadata["queue_depth"] = queue_depth
    return {
        "event_id": event_id,
        "store_id": STORE,
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": _ts(hour, minute).isoformat().replace("+00:00", "Z"),
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": is_staff,
        "confidence": 0.9,
        "metadata": metadata,
    }


class TestPosCorrelation:
    def test_converted_when_pos_within_five_minutes_of_billing(self) -> None:
        events = [
            _record("e1", "ENTRY", hour=14, minute=0),
            _record(
                "e2",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                hour=14,
                minute=10,
                metadata={"queue_depth": 1},
            ),
            _record("e3", "EXIT", hour=14, minute=30),
        ]
        sessions = build_sessions(events)
        txns = [_pos("TXN_001", hour=14, minute=12)]

        assert is_session_converted(sessions[0], txns) is True

    def test_not_converted_when_pos_outside_window(self) -> None:
        events = [
            _record("e1", "ENTRY", hour=14, minute=0),
            _record(
                "e2",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                hour=14,
                minute=10,
                metadata={"queue_depth": 1},
            ),
            _record("e3", "EXIT", hour=14, minute=30),
        ]
        sessions = build_sessions(events)
        txns = [_pos("TXN_001", hour=14, minute=20)]

        assert is_session_converted(sessions[0], txns) is False

    def test_staff_session_never_converted(self) -> None:
        events = [
            _record("e1", "ENTRY", hour=14, minute=0, is_staff=True),
            _record(
                "e2",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                hour=14,
                minute=10,
                is_staff=True,
                metadata={"queue_depth": 1},
            ),
        ]
        sessions = build_sessions(events)
        txns = [_pos("TXN_001", hour=14, minute=11)]

        assert is_session_converted(sessions[0], txns) is False


class TestMetricsComputation:
    def test_happy_path_metrics(self) -> None:
        events = [
            _record("e1", "ENTRY", visitor_id="VIS_v1", hour=14, minute=0),
            _record(
                "e2",
                "ZONE_DWELL",
                zone_id="SKINCARE",
                dwell_ms=30_000,
                visitor_id="VIS_v1",
                hour=14,
                minute=5,
            ),
            _record(
                "e3",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                visitor_id="VIS_v1",
                hour=14,
                minute=10,
                metadata={"queue_depth": 2},
            ),
            _record("e4", "EXIT", visitor_id="VIS_v1", hour=14, minute=25),
            _record("e5", "ENTRY", visitor_id="VIS_v2", hour=15, minute=0),
            _record("e6", "EXIT", visitor_id="VIS_v2", hour=15, minute=10),
        ]
        txns = [_pos("TXN_100", hour=14, minute=12)]

        result = compute_store_metrics(STORE, METRIC_DATE, events, txns)

        assert result.store_id == STORE
        assert result.date == DAY
        assert result.unique_visitors == 2
        assert result.total_sessions == 2
        assert result.conversion_rate == 0.5
        assert result.billing_reach_rate == 0.5
        assert result.average_dwell_time_ms == 15_000.0
        assert result.queue_abandonment_rate == 0.0

    def test_empty_store_returns_zeros(self) -> None:
        result = compute_store_metrics(STORE, METRIC_DATE, [], [])

        assert result.unique_visitors == 0
        assert result.conversion_rate == 0.0
        assert result.total_sessions == 0
        assert result.billing_reach_rate == 0.0
        assert result.queue_abandonment_rate == 0.0
        assert result.average_dwell_time_ms == 0.0

    def test_staff_only_excluded_from_visitor_metrics(self) -> None:
        events = [
            _record("e1", "ENTRY", is_staff=True, hour=10),
            _record("e2", "EXIT", is_staff=True, hour=11),
        ]
        result = compute_store_metrics(STORE, METRIC_DATE, events, [])

        assert result.unique_visitors == 0
        assert result.total_sessions == 0

    def test_queue_abandonment_rate(self) -> None:
        events = [
            _record("e1", "ENTRY", hour=14, minute=0),
            _record(
                "e2",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                hour=14,
                minute=10,
                metadata={"queue_depth": 1},
            ),
            _record("e3", "BILLING_QUEUE_ABANDON", zone_id="BILLING", hour=14, minute=15),
            _record("e4", "EXIT", hour=14, minute=20),
        ]
        result = compute_store_metrics(STORE, METRIC_DATE, events, [])

        assert result.queue_abandonment_rate == 1.0

    def test_reentry_counts_one_unique_visitor(self) -> None:
        events = [
            _record("e1", "ENTRY", hour=10),
            _record("e2", "EXIT", hour=11),
            _record("e3", "REENTRY", hour=12),
            _record(
                "e4",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                hour=12,
                minute=5,
                metadata={"queue_depth": 1},
            ),
            _record("e5", "EXIT", hour=13),
        ]
        txns = [_pos("TXN_200", hour=12, minute=7)]
        sessions = build_sessions(events)

        assert compute_conversion_rate(sessions, txns) == 1.0
        result = compute_store_metrics(STORE, METRIC_DATE, events, txns)
        assert result.unique_visitors == 1
        assert result.total_sessions == 2


class TestPdfMetricsFields:
    def test_average_dwell_by_zone_per_visit(self) -> None:
        events = [
            _record("e1", "ENTRY", visitor_id="VIS_z1", hour=14),
            _record(
                "e2",
                "ZONE_DWELL",
                zone_id="SKINCARE",
                dwell_ms=40_000,
                visitor_id="VIS_z1",
                hour=14,
                minute=5,
            ),
            _record("e3", "ENTRY", visitor_id="VIS_z2", hour=15),
            _record(
                "e4",
                "ZONE_DWELL",
                zone_id="SKINCARE",
                dwell_ms=20_000,
                visitor_id="VIS_z2",
                hour=15,
                minute=5,
            ),
        ]
        sessions = build_sessions(events)
        by_zone = {metric.zone_id: metric.average_dwell_ms for metric in compute_average_dwell_by_zone(sessions)}

        assert by_zone["SKINCARE"] == 30_000.0

    def test_current_queue_depth_from_latest_join(self) -> None:
        events = [
            _record(
                "e1",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                hour=14,
                metadata={"queue_depth": 2},
            ),
            _record(
                "e2",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                hour=14,
                minute=10,
                metadata={"queue_depth": 5},
            ),
        ]
        assert compute_current_queue_depth(events) == 5

    def test_current_queue_depth_zero_without_joins(self) -> None:
        events = [_record("e1", "ENTRY", hour=14)]
        assert compute_current_queue_depth(events) == 0

    def test_current_queue_depth_ignores_staff_joins(self) -> None:
        events = [
            _record(
                "e1",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                hour=14,
                minute=10,
                is_staff=True,
                metadata={"queue_depth": 9},
            ),
            _record(
                "e2",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                hour=14,
                metadata={"queue_depth": 3},
            ),
        ]
        assert compute_current_queue_depth(events) == 3

    def test_store_metrics_includes_pdf_fields(self) -> None:
        events = [
            _record("e1", "ENTRY", visitor_id="VIS_m1", hour=14),
            _record(
                "e2",
                "ZONE_DWELL",
                zone_id="SKINCARE",
                dwell_ms=30_000,
                visitor_id="VIS_m1",
                hour=14,
                minute=5,
            ),
            _record(
                "e3",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                visitor_id="VIS_m1",
                hour=14,
                minute=10,
                metadata={"queue_depth": 4},
            ),
        ]
        result = compute_store_metrics(STORE, METRIC_DATE, events, [])

        assert result.current_queue_depth == 4
        by_zone = {z.zone_id: z.average_dwell_ms for z in result.average_dwell_by_zone}
        assert by_zone["SKINCARE"] == 30_000.0
        assert by_zone["BILLING"] == 0.0


class TestMetricsEndpoint:
    def test_get_metrics_returns_json_for_store(
        self, client: TestClient
    ) -> None:
        _persist_events(
            _record("e1", "ENTRY", visitor_id="VIS_api1", hour=14, minute=0),
            _record(
                "e2",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                visitor_id="VIS_api1",
                hour=14,
                minute=10,
                metadata={"queue_depth": 1},
            ),
            _record("e3", "EXIT", visitor_id="VIS_api1", hour=14, minute=20),
        )
        _persist_pos(_pos("TXN_API", hour=14, minute=12))

        response = client.get(f"/stores/{STORE}/metrics?date={DAY}")

        assert response.status_code == 200
        body = response.json()
        assert body["store_id"] == STORE
        assert body["date"] == DAY
        assert body["unique_visitors"] == 1
        assert body["conversion_rate"] == 1.0
        assert body["total_sessions"] == 1
        assert "average_dwell_time_ms" in body
        assert "average_dwell_by_zone" in body
        assert "current_queue_depth" in body
        assert body["current_queue_depth"] == 1
        assert "billing_reach_rate" in body
        assert "queue_abandonment_rate" in body

    def test_get_metrics_acceptance_gate_store(
        self, client: TestClient
    ) -> None:
        """Acceptance gate #4: GET /stores/STORE_BLR_002/metrics returns JSON."""
        response = client.get("/stores/STORE_BLR_002/metrics?date=2026-03-03")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["store_id"] == "STORE_BLR_002"

    def test_get_metrics_via_ingest_flow(self, client: TestClient) -> None:
        _ingest(
            client,
            [
                _event_payload(
                    "550e8400-e29b-41d4-a716-446655440010",
                    "ENTRY",
                    visitor_id="VIS_flow1",
                    hour=14,
                    minute=0,
                ),
                _event_payload(
                    "550e8400-e29b-41d4-a716-446655440011",
                    "ZONE_DWELL",
                    zone_id="SKINCARE",
                    dwell_ms=30_000,
                    visitor_id="VIS_flow1",
                    hour=14,
                    minute=5,
                ),
                _event_payload(
                    "550e8400-e29b-41d4-a716-446655440012",
                    "EXIT",
                    visitor_id="VIS_flow1",
                    hour=14,
                    minute=20,
                ),
            ],
        )

        response = client.get(f"/stores/{STORE}/metrics?date={DAY}")

        assert response.status_code == 200
        body = response.json()
        assert body["unique_visitors"] == 1
        assert body["total_sessions"] == 1
        assert body["average_dwell_time_ms"] == 30_000.0
        assert body["conversion_rate"] == 0.0

    def test_get_metrics_invalid_date_returns_422(self, client: TestClient) -> None:
        response = client.get(f"/stores/{STORE}/metrics?date=not-a-date")

        assert response.status_code == 422

    def test_get_metrics_returns_503_when_database_unavailable(
        self, client: TestClient
    ) -> None:
        with patch("app.metrics.is_database_available", return_value=False):
            response = client.get(f"/stores/{STORE}/metrics")

        assert response.status_code == 503

    def test_get_metrics_returns_503_on_database_error(
        self, client: TestClient
    ) -> None:
        with patch(
            "app.metrics.fetch_store_events",
            side_effect=SQLAlchemyError("boom"),
        ):
            response = client.get(f"/stores/{STORE}/metrics?date={DAY}")

        assert response.status_code == 503


class TestMetricFormulasUnit:
    def test_billing_reach_rate_formula(self) -> None:
        events = [
            _record("e1", "ENTRY", visitor_id="VIS_a"),
            _record("e2", "ZONE_ENTER", zone_id="BILLING", visitor_id="VIS_a", hour=14, minute=5),
            _record("e3", "EXIT", visitor_id="VIS_a", hour=14, minute=10),
            _record("e4", "ENTRY", visitor_id="VIS_b", hour=15),
            _record("e5", "EXIT", visitor_id="VIS_b", hour=15, minute=10),
        ]
        sessions = build_sessions(events)
        assert compute_billing_reach_rate(sessions) == 0.5

    def test_average_dwell_only_counts_customer_sessions(self) -> None:
        events = [
            _record("e1", "ENTRY", is_staff=True),
            _record(
                "e2",
                "ZONE_DWELL",
                zone_id="SKINCARE",
                dwell_ms=60_000,
                is_staff=True,
                hour=14,
                minute=5,
            ),
            _record("e3", "ENTRY", visitor_id="VIS_cust", hour=15),
            _record(
                "e4",
                "ZONE_DWELL",
                zone_id="SKINCARE",
                dwell_ms=20_000,
                visitor_id="VIS_cust",
                hour=15,
                minute=5,
            ),
        ]
        sessions = build_sessions(events)
        assert compute_average_dwell_time_ms(sessions) == 20_000.0

    def test_queue_abandonment_zero_when_no_queue_joins(self) -> None:
        events = [
            _record("e1", "ENTRY"),
            _record("e2", "ZONE_ENTER", zone_id="SKINCARE", hour=14, minute=5),
            _record("e3", "EXIT", hour=14, minute=10),
        ]
        sessions = build_sessions(events)
        assert compute_queue_abandonment_rate(sessions) == 0.0
