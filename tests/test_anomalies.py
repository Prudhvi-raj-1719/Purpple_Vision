# PROMPT: Verify anomalies include PDF suggested_action for each alert type.
# CHANGES MADE: Tests assert suggested_action on queue, conversion, and dead-zone anomalies.
"""Tests for store anomaly detection and GET /stores/{store_id}/anomalies."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.anomalies import (
    ANOMALY_CONVERSION_DROP,
    ANOMALY_DEAD_ZONE,
    ANOMALY_QUEUE_SPIKE,
    CONVERSION_DROP_CRITICAL_RATE,
    CONVERSION_DROP_WARNING_RATE,
    DEAD_ZONE_CRITICAL_SCORE,
    DEAD_ZONE_WARNING_SCORE,
    QUEUE_SPIKE_CRITICAL_JOINS,
    QUEUE_SPIKE_WARNING_JOINS,
    SUGGESTED_ACTION_CONVERSION_DROP,
    SUGGESTED_ACTION_DEAD_ZONE,
    SUGGESTED_ACTION_QUEUE_SPIKE,
    compute_store_anomalies,
    count_non_staff_queue_joins,
    detect_conversion_drop,
    detect_dead_zones,
    detect_queue_spike,
    detect_store_anomalies,
)
from app.staff_detection import build_sessions_for_analytics
from app.db import EventRecord, PosTransactionRecord, get_session
from app.models import AnomalySeverity, HeatmapZone

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


def _queue_join_event(event_id: str, hour: int, minute: int = 0, **kwargs) -> EventRecord:
    return _record(
        event_id,
        "BILLING_QUEUE_JOIN",
        zone_id="BILLING",
        hour=hour,
        minute=minute,
        metadata={"queue_depth": 1},
        **kwargs,
    )


def _types(anomalies: list) -> list[str]:
    return [a.anomaly_type for a in anomalies]


class TestAnomalyPdfFields:
    def test_anomaly_includes_detected_at_and_warn_severity(self) -> None:
        fixed = datetime(2026, 3, 3, 18, 0, 0, tzinfo=UTC)
        result = detect_queue_spike(
            QUEUE_SPIKE_WARNING_JOINS,
            detected_at=fixed,
        )

        assert result is not None
        assert result.detected_at == fixed
        assert result.severity == AnomalySeverity.WARN
        assert result.severity.value == "WARN"

    def test_severity_enum_supports_info_warn_critical(self) -> None:
        assert {s.value for s in AnomalySeverity} == {"INFO", "WARN", "CRITICAL"}


class TestQueueSpikeDetection:
    def test_no_anomaly_below_warning_threshold(self) -> None:
        assert detect_queue_spike(QUEUE_SPIKE_WARNING_JOINS - 1) is None

    def test_warning_at_threshold(self) -> None:
        result = detect_queue_spike(QUEUE_SPIKE_WARNING_JOINS)

        assert result is not None
        assert result.anomaly_type == ANOMALY_QUEUE_SPIKE
        assert result.severity == AnomalySeverity.WARN
        assert result.suggested_action == SUGGESTED_ACTION_QUEUE_SPIKE
        assert result.supporting_metrics["queue_joins"] == QUEUE_SPIKE_WARNING_JOINS

    def test_critical_at_threshold(self) -> None:
        result = detect_queue_spike(QUEUE_SPIKE_CRITICAL_JOINS)

        assert result is not None
        assert result.severity == AnomalySeverity.CRITICAL

    def test_staff_queue_joins_excluded(self) -> None:
        events = [
            _queue_join_event("e1", 14, is_staff=True),
            _queue_join_event("e2", 14, minute=1, visitor_id="VIS_cust", is_staff=False),
        ]
        _, _, staff_ids = build_sessions_for_analytics(events)
        assert count_non_staff_queue_joins(events, staff_ids) == 1


class TestConversionDropDetection:
    def _billing_session_events(self, visitor_id: str, event_prefix: str) -> list[EventRecord]:
        return [
            _record(f"{event_prefix}a", "ENTRY", visitor_id=visitor_id, hour=10),
            _record(
                f"{event_prefix}b",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                visitor_id=visitor_id,
                hour=10,
                minute=5,
                metadata={"queue_depth": 1},
            ),
            _record(f"{event_prefix}c", "EXIT", visitor_id=visitor_id, hour=10, minute=20),
        ]

    def test_skipped_when_no_billing_reachers(self) -> None:
        events = [
            _record("e1", "ENTRY", hour=10),
            _record("e2", "ZONE_ENTER", zone_id="SKINCARE", hour=10, minute=5),
            _record("e3", "EXIT", hour=10, minute=15),
        ]
        from app.sessions import build_sessions

        assert detect_conversion_drop(build_sessions(events), []) is None

    def test_critical_conversion_drop(self) -> None:
        events = self._billing_session_events("VIS_b1", "e1")
        events += self._billing_session_events("VIS_b2", "e2")
        events += self._billing_session_events("VIS_b3", "e3")
        events += self._billing_session_events("VIS_b4", "e4")
        events += self._billing_session_events("VIS_b5", "e5")
        events += self._billing_session_events("VIS_b6", "e6")
        events += self._billing_session_events("VIS_b7", "e7")
        events += self._billing_session_events("VIS_b8", "e8")
        events += self._billing_session_events("VIS_b9", "e9")
        events += self._billing_session_events("VIS_b10", "e10")

        from app.sessions import build_sessions

        sessions = build_sessions(events)
        result = detect_conversion_drop(sessions, [])

        assert result is not None
        assert result.anomaly_type == ANOMALY_CONVERSION_DROP
        assert result.severity == AnomalySeverity.CRITICAL
        assert result.suggested_action == SUGGESTED_ACTION_CONVERSION_DROP
        assert result.supporting_metrics["conversion_rate"] == 0.0

    def test_warning_conversion_drop_with_partial_conversion(self) -> None:
        events: list[EventRecord] = []
        # First visitor: billing early with matching POS → converted
        events.extend(self._billing_session_events("VIS_c0", "e0"))
        # Five more visitors: billing later with no POS → not converted
        for index in range(1, 6):
            events.extend(
                [
                    _record(f"en{index}", "ENTRY", visitor_id=f"VIS_c{index}", hour=15),
                    _record(
                        f"bj{index}",
                        "BILLING_QUEUE_JOIN",
                        zone_id="BILLING",
                        visitor_id=f"VIS_c{index}",
                        hour=15,
                        minute=5,
                        metadata={"queue_depth": 1},
                    ),
                    _record(f"ex{index}", "EXIT", visitor_id=f"VIS_c{index}", hour=15, minute=20),
                ]
            )
        txns = [_pos("TXN_ONE", hour=10, minute=7)]

        from app.sessions import build_sessions

        sessions = build_sessions(events)
        result = detect_conversion_drop(sessions, txns)

        assert result is not None
        assert result.severity == AnomalySeverity.WARN
        assert result.supporting_metrics["conversion_rate"] == round(1 / 6, 4)
        assert result.supporting_metrics["conversion_rate"] < CONVERSION_DROP_WARNING_RATE
        assert result.supporting_metrics["conversion_rate"] >= CONVERSION_DROP_CRITICAL_RATE


class TestDeadZoneDetection:
    def _zone(self, zone_id: str, score: float, visits: int = 1) -> HeatmapZone:
        return HeatmapZone(
            zone_id=zone_id,
            visit_count=visits,
            unique_visitors=visits,
            total_dwell_time_ms=0,
            average_dwell_time_ms=0.0,
            normalized_score=score,
        )

    def test_no_dead_zone_with_single_zone(self) -> None:
        assert detect_dead_zones([self._zone("SKINCARE", 100.0)]) == []

    def test_warning_dead_zone(self) -> None:
        zones = [
            self._zone("SKINCARE", 100.0),
            self._zone("ELECTRONICS", DEAD_ZONE_WARNING_SCORE - 1),
        ]
        results = detect_dead_zones(zones)

        assert len(results) == 1
        assert results[0].anomaly_type == ANOMALY_DEAD_ZONE
        assert results[0].severity == AnomalySeverity.WARN
        assert results[0].suggested_action == SUGGESTED_ACTION_DEAD_ZONE

    def test_critical_dead_zone(self) -> None:
        zones = [
            self._zone("SKINCARE", 100.0),
            self._zone("ELECTRONICS", DEAD_ZONE_CRITICAL_SCORE - 1),
        ]
        results = detect_dead_zones(zones)

        assert results[0].severity == AnomalySeverity.CRITICAL


class TestDetectStoreAnomalies:
    def test_empty_store_returns_no_anomalies(self) -> None:
        assert detect_store_anomalies([], []) == []

    def test_integrated_queue_spike_and_dead_zone(self) -> None:
        events = []
        for index in range(QUEUE_SPIKE_WARNING_JOINS):
            events.append(
                _queue_join_event(
                    f"q{index}",
                    hour=14,
                    minute=index,
                    visitor_id=f"VIS_q{index}",
                )
            )
            events.insert(
                index * 3,
                _record(
                    f"en{index}",
                    "ENTRY",
                    visitor_id=f"VIS_q{index}",
                    hour=14,
                    minute=index,
                ),
            )
            events.append(
                _record(
                    f"ex{index}",
                    "EXIT",
                    visitor_id=f"VIS_q{index}",
                    hour=14,
                    minute=index + 1,
                )
            )

        # Add two zones with skewed engagement for dead zone detection
        events.extend(
            [
                _record("z1", "ENTRY", visitor_id="VIS_z1", hour=15),
                _record(
                    "z2",
                    "ZONE_ENTER",
                    zone_id="SKINCARE",
                    visitor_id="VIS_z1",
                    hour=15,
                    minute=1,
                ),
                _record(
                    "z3",
                    "ZONE_DWELL",
                    zone_id="SKINCARE",
                    dwell_ms=90_000,
                    visitor_id="VIS_z1",
                    hour=15,
                    minute=2,
                ),
                _record("z4", "EXIT", visitor_id="VIS_z1", hour=15, minute=10),
                _record("z5", "ENTRY", visitor_id="VIS_z2", hour=16),
                _record(
                    "z6",
                    "ZONE_ENTER",
                    zone_id="ELECTRONICS",
                    visitor_id="VIS_z2",
                    hour=16,
                    minute=1,
                ),
                _record("z7", "EXIT", visitor_id="VIS_z2", hour=16, minute=5),
            ]
        )

        anomalies = detect_store_anomalies(events, [])
        types = _types(anomalies)

        assert ANOMALY_QUEUE_SPIKE in types
        assert ANOMALY_DEAD_ZONE in types


class TestComputeStoreAnomalies:
    def test_response_shape(self) -> None:
        result = compute_store_anomalies(STORE, METRIC_DATE, [], [])

        assert result.store_id == STORE
        assert result.date == DAY
        assert result.anomalies == []


class TestAnomaliesEndpoint:
    def test_get_anomalies_empty_store(self, client: TestClient) -> None:
        response = client.get(f"/stores/{STORE}/anomalies?date={DAY}")

        assert response.status_code == 200
        body = response.json()
        assert body["store_id"] == STORE
        assert body["date"] == DAY
        assert body["anomalies"] == []

    def test_get_anomalies_queue_spike(self, client: TestClient) -> None:
        events = []
        for index in range(QUEUE_SPIKE_WARNING_JOINS):
            vid = f"VIS_api{index}"
            events.extend(
                [
                    _record(f"en{index}", "ENTRY", visitor_id=vid, hour=14, minute=index),
                    _queue_join_event(f"q{index}", hour=14, minute=index, visitor_id=vid),
                    _record(f"ex{index}", "EXIT", visitor_id=vid, hour=14, minute=index + 1),
                ]
            )
        _persist_events(*events)

        response = client.get(f"/stores/{STORE}/anomalies?date={DAY}")

        assert response.status_code == 200
        anomalies = response.json()["anomalies"]
        types = [a["anomaly_type"] for a in anomalies]
        assert ANOMALY_QUEUE_SPIKE in types
        queue_alert = next(a for a in anomalies if a["anomaly_type"] == ANOMALY_QUEUE_SPIKE)
        assert queue_alert["suggested_action"] == SUGGESTED_ACTION_QUEUE_SPIKE
        assert queue_alert["severity"] == "WARN"
        assert "detected_at" in queue_alert

    def test_get_anomalies_invalid_date_returns_422(self, client: TestClient) -> None:
        response = client.get(f"/stores/{STORE}/anomalies?date=bad-date")

        assert response.status_code == 422

    def test_get_anomalies_returns_503_when_database_unavailable(
        self, client: TestClient
    ) -> None:
        with patch("app.anomalies.is_database_available", return_value=False):
            response = client.get(f"/stores/{STORE}/anomalies")

        assert response.status_code == 503

    def test_get_anomalies_returns_503_on_database_error(
        self, client: TestClient
    ) -> None:
        with patch(
            "app.anomalies.fetch_store_events",
            side_effect=SQLAlchemyError("boom"),
        ):
            response = client.get(f"/stores/{STORE}/anomalies?date={DAY}")

        assert response.status_code == 503
