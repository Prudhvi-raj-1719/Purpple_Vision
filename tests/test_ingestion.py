# PROMPT: Verify POST /events/ingest idempotency and partial-success batch handling.
# CHANGES MADE: Ingest validation and duplicate-skip tests per challenge schema.
"""Tests for POST /events/ingest idempotency and partial-success handling."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.db import EventRecord, get_session


def test_ingest_single_event_success(
    client: TestClient, sample_entry_event: dict
) -> None:
    response = client.post("/events/ingest", json={"events": [sample_entry_event]})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["total_received"] == 1
    assert body["events_ingested"] == 1
    assert body["duplicates_skipped"] == 0
    assert body["rejected"] == 0
    assert body["errors"] == []

    session = get_session()
    try:
        record = session.get(EventRecord, sample_entry_event["event_id"])
        assert record is not None
        assert record.store_id == "STORE_BLR_002"
    finally:
        session.close()


def test_ingest_duplicate_event_is_idempotent(
    client: TestClient, sample_entry_event: dict
) -> None:
    first = client.post("/events/ingest", json={"events": [sample_entry_event]})
    second = client.post("/events/ingest", json={"events": [sample_entry_event]})

    assert first.status_code == 200
    assert first.json()["events_ingested"] == 1

    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "success"
    assert body["events_ingested"] == 0
    assert body["duplicates_skipped"] == 1


def test_ingest_partial_success_on_validation_failure(
    client: TestClient, sample_entry_event: dict
) -> None:
    invalid_event = {
        **sample_entry_event,
        "event_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        "event_type": "ENTRY",
        "zone_id": "SKINCARE",
    }

    response = client.post(
        "/events/ingest",
        json={"events": [sample_entry_event, invalid_event]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["total_received"] == 2
    assert body["events_ingested"] == 1
    assert body["rejected"] == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["index"] == 1


def test_ingest_rejects_empty_batch(client: TestClient) -> None:
    response = client.post("/events/ingest", json={"events": []})

    assert response.status_code == 422


def test_ingest_returns_503_when_database_unavailable(
    client: TestClient, sample_entry_event: dict
) -> None:
    with patch("app.ingestion.is_database_available", return_value=False):
        response = client.post("/events/ingest", json={"events": [sample_entry_event]})

    assert response.status_code == 503
    assert response.json()["detail"] == "Database is unavailable"


def test_ingest_returns_503_on_database_error(
    client: TestClient, sample_entry_event: dict
) -> None:
    with patch(
        "app.ingestion.session_scope",
        side_effect=SQLAlchemyError("boom"),
    ):
        response = client.post("/events/ingest", json={"events": [sample_entry_event]})

    assert response.status_code == 503
    assert "Database error" in response.json()["detail"]
