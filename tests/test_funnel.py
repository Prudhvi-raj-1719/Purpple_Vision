"""Tests for store funnel computation and GET /stores/{store_id}/funnel."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.db import EventRecord, PosTransactionRecord, get_session
from app.funnel import (
    STAGE_CONVERTED_VISITORS,
    STAGE_REACHED_ANY_ZONE,
    STAGE_REACHED_BILLING,
    STAGE_UNIQUE_VISITORS,
    build_funnel_stages,
    compute_drop_off_pct,
    compute_overall_conversion_rate,
    compute_store_funnel,
    visitors_reached_any_zone,
    visitors_reached_billing,
)
from app.sessions import build_sessions, count_unique_visitors

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


def _stage_counts(response_stages: list[dict]) -> dict[str, int]:
    return {stage["stage"]: stage["count"] for stage in response_stages}


class TestDropOffFormula:
    def test_drop_off_between_stages(self) -> None:
        assert compute_drop_off_pct(100, 75) == 25.0

    def test_drop_off_zero_when_no_loss(self) -> None:
        assert compute_drop_off_pct(50, 50) == 0.0

    def test_drop_off_none_when_prior_stage_zero(self) -> None:
        assert compute_drop_off_pct(0, 0) is None


class TestVisitorStageSets:
    def test_visitors_reached_any_zone_aggregates_across_sessions(self) -> None:
        events = [
            _record("e1", "ENTRY", visitor_id="VIS_a", hour=10),
            _record("e2", "EXIT", visitor_id="VIS_a", hour=11),
            _record("e3", "REENTRY", visitor_id="VIS_a", hour=12),
            _record(
                "e4",
                "ZONE_ENTER",
                zone_id="SKINCARE",
                visitor_id="VIS_a",
                hour=12,
                minute=5,
            ),
        ]
        sessions = build_sessions(events)

        assert visitors_reached_any_zone(sessions) == {"VIS_a"}

    def test_visitors_reached_billing_from_second_session_only(self) -> None:
        events = [
            _record("e1", "ENTRY", visitor_id="VIS_a", hour=10),
            _record("e2", "ZONE_ENTER", zone_id="SKINCARE", visitor_id="VIS_a", hour=10, minute=5),
            _record("e3", "EXIT", visitor_id="VIS_a", hour=11),
            _record("e4", "REENTRY", visitor_id="VIS_a", hour=12),
            _record(
                "e5",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                visitor_id="VIS_a",
                hour=12,
                minute=5,
                metadata={"queue_depth": 1},
            ),
        ]
        sessions = build_sessions(events)

        assert visitors_reached_billing(sessions) == {"VIS_a"}


class TestFunnelComputation:
    def test_happy_path_funnel_with_drop_offs(self) -> None:
        events = [
            # Visitor 1: zone + billing + converts
            _record("e1", "ENTRY", visitor_id="VIS_v1", hour=14, minute=0),
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
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                visitor_id="VIS_v1",
                hour=14,
                minute=10,
                metadata={"queue_depth": 1},
            ),
            _record("e4", "EXIT", visitor_id="VIS_v1", hour=14, minute=25),
            # Visitor 2: zone only
            _record("e5", "ENTRY", visitor_id="VIS_v2", hour=15, minute=0),
            _record(
                "e6",
                "ZONE_ENTER",
                zone_id="ELECTRONICS",
                visitor_id="VIS_v2",
                hour=15,
                minute=5,
            ),
            _record("e7", "EXIT", visitor_id="VIS_v2", hour=15, minute=20),
            # Visitor 3: entry/exit only
            _record("e8", "ENTRY", visitor_id="VIS_v3", hour=16, minute=0),
            _record("e9", "EXIT", visitor_id="VIS_v3", hour=16, minute=10),
        ]
        txns = [_pos("TXN_100", hour=14, minute=12)]

        result = compute_store_funnel(STORE, METRIC_DATE, events, txns)
        counts = _stage_counts([s.model_dump() for s in result.stages])

        assert result.store_id == STORE
        assert result.date == DAY
        assert counts[STAGE_UNIQUE_VISITORS] == 3
        assert counts[STAGE_REACHED_ANY_ZONE] == 2
        assert counts[STAGE_REACHED_BILLING] == 1
        assert counts[STAGE_CONVERTED_VISITORS] == 1
        assert result.overall_conversion_rate == 1 / 3

        stages = result.stages
        assert stages[0].drop_off_pct is None
        assert stages[1].drop_off_pct == (1 / 3) * 100
        assert stages[2].drop_off_pct == 50.0
        assert stages[3].drop_off_pct == 0.0

    def test_empty_store_all_zeros(self) -> None:
        result = compute_store_funnel(STORE, METRIC_DATE, [], [])

        assert result.overall_conversion_rate == 0.0
        for stage in result.stages:
            assert stage.count == 0
            assert stage.drop_off_pct is None

    def test_staff_excluded_from_funnel(self) -> None:
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
            _record(
                "e3",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                is_staff=True,
                hour=10,
                minute=10,
                metadata={"queue_depth": 1},
            ),
            _record("e4", "EXIT", is_staff=True, hour=11),
            _record("e5", "ENTRY", visitor_id="VIS_cust", hour=12),
            _record("e6", "EXIT", visitor_id="VIS_cust", hour=13),
        ]
        txns = [_pos("TXN_STAFF", hour=10, minute=11)]

        result = compute_store_funnel(STORE, METRIC_DATE, events, txns)
        counts = _stage_counts([s.model_dump() for s in result.stages])

        assert counts[STAGE_UNIQUE_VISITORS] == 1
        assert counts[STAGE_REACHED_ANY_ZONE] == 0
        assert counts[STAGE_REACHED_BILLING] == 0
        assert counts[STAGE_CONVERTED_VISITORS] == 0

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
        result = compute_store_funnel(STORE, METRIC_DATE, events, txns)

        assert count_unique_visitors(sessions) == 1
        assert result.overall_conversion_rate == 1.0
        assert _stage_counts([s.model_dump() for s in result.stages])[
            STAGE_CONVERTED_VISITORS
        ] == 1

    def test_no_pos_transactions_zero_conversions(self) -> None:
        events = [
            _record("e1", "ENTRY", hour=14),
            _record(
                "e2",
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                hour=14,
                minute=10,
                metadata={"queue_depth": 1},
            ),
            _record("e3", "EXIT", hour=14, minute=20),
        ]
        result = compute_store_funnel(STORE, METRIC_DATE, events, [])

        assert _stage_counts([s.model_dump() for s in result.stages])[
            STAGE_CONVERTED_VISITORS
        ] == 0
        assert result.overall_conversion_rate == 0.0
        assert result.stages[3].drop_off_pct == 100.0

    def test_pos_outside_window_not_converted(self) -> None:
        events = [
            _record("e1", "ENTRY", hour=14),
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
        txns = [_pos("TXN_LATE", hour=14, minute=20)]

        result = compute_store_funnel(STORE, METRIC_DATE, events, txns)

        assert _stage_counts([s.model_dump() for s in result.stages])[
            STAGE_REACHED_BILLING
        ] == 1
        assert _stage_counts([s.model_dump() for s in result.stages])[
            STAGE_CONVERTED_VISITORS
        ] == 0


class TestFunnelStageBuilder:
    def test_build_funnel_stages_order(self) -> None:
        stages = build_funnel_stages(10, 8, 4, 2)

        assert [s.stage for s in stages] == [
            STAGE_UNIQUE_VISITORS,
            STAGE_REACHED_ANY_ZONE,
            STAGE_REACHED_BILLING,
            STAGE_CONVERTED_VISITORS,
        ]
        assert [s.count for s in stages] == [10, 8, 4, 2]
        assert stages[0].drop_off_pct is None
        assert stages[1].drop_off_pct == 20.0


class TestOverallConversionRate:
    def test_overall_conversion_rate_formula(self) -> None:
        assert compute_overall_conversion_rate(4, 1) == 0.25
        assert compute_overall_conversion_rate(0, 0) == 0.0


class TestFunnelEndpoint:
    def test_get_funnel_returns_json(self, client: TestClient) -> None:
        _persist_events(
            _record("e1", "ENTRY", visitor_id="VIS_api1", hour=14, minute=0),
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
                "BILLING_QUEUE_JOIN",
                zone_id="BILLING",
                visitor_id="VIS_api1",
                hour=14,
                minute=10,
                metadata={"queue_depth": 1},
            ),
            _record("e4", "EXIT", visitor_id="VIS_api1", hour=14, minute=20),
        )
        _persist_pos(_pos("TXN_API", hour=14, minute=12))

        response = client.get(f"/stores/{STORE}/funnel?date={DAY}")

        assert response.status_code == 200
        body = response.json()
        assert body["store_id"] == STORE
        assert body["date"] == DAY
        assert len(body["stages"]) == 4
        assert body["overall_conversion_rate"] == 1.0
        assert body["stages"][0]["stage"] == STAGE_UNIQUE_VISITORS
        assert body["stages"][0]["drop_off_pct"] is None

    def test_get_funnel_empty_store(self, client: TestClient) -> None:
        response = client.get(f"/stores/{STORE}/funnel?date={DAY}")

        assert response.status_code == 200
        body = response.json()
        assert body["overall_conversion_rate"] == 0.0
        assert all(stage["count"] == 0 for stage in body["stages"])

    def test_get_funnel_invalid_date_returns_422(self, client: TestClient) -> None:
        response = client.get(f"/stores/{STORE}/funnel?date=bad-date")

        assert response.status_code == 422

    def test_get_funnel_returns_503_when_database_unavailable(
        self, client: TestClient
    ) -> None:
        with patch("app.funnel.is_database_available", return_value=False):
            response = client.get(f"/stores/{STORE}/funnel")

        assert response.status_code == 503

    def test_get_funnel_returns_503_on_database_error(
        self, client: TestClient
    ) -> None:
        with patch(
            "app.funnel.fetch_store_events",
            side_effect=SQLAlchemyError("boom"),
        ):
            response = client.get(f"/stores/{STORE}/funnel?date={DAY}")

        assert response.status_code == 503
