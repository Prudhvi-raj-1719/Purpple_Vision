# PROMPT: Verify POST /pos/ingest idempotency and partial-success batch handling.
# CHANGES MADE: POS ingest endpoint tests mirroring event ingest semantics.
"""Tests for POST /pos/ingest."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.db import PosTransactionRecord, get_session


def _pos_payload(
    transaction_id: str = "TXN_TEST_001",
    *,
    store_id: str = "STORE_BLR_002",
    timestamp: str = "2026-03-03T14:30:00Z",
    amount: float = 999.0,
) -> dict:
    return {
        "store_id": store_id,
        "transaction_id": transaction_id,
        "timestamp": timestamp,
        "basket_value_inr": amount,
    }


def test_pos_ingest_single_transaction_success(client: TestClient) -> None:
    response = client.post(
        "/pos/ingest",
        json={"transactions": [_pos_payload()]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["total_received"] == 1
    assert body["transactions_ingested"] == 1
    assert body["duplicates_skipped"] == 0
    assert body["rejected"] == 0
    assert body["errors"] == []

    session = get_session()
    try:
        record = session.get(PosTransactionRecord, "TXN_TEST_001")
        assert record is not None
        assert record.store_id == "STORE_BLR_002"
    finally:
        session.close()


def test_pos_ingest_duplicate_is_idempotent(client: TestClient) -> None:
    payload = {"transactions": [_pos_payload()]}
    first = client.post("/pos/ingest", json=payload)
    second = client.post("/pos/ingest", json=payload)

    assert first.json()["transactions_ingested"] == 1
    assert second.json()["transactions_ingested"] == 0
    assert second.json()["duplicates_skipped"] == 1


def test_pos_ingest_partial_success_on_validation_failure(client: TestClient) -> None:
    invalid = {**_pos_payload("TXN_BAD"), "transaction_id": "not-a-valid-txn-id"}
    response = client.post(
        "/pos/ingest",
        json={"transactions": [_pos_payload("TXN_OK"), invalid]},
    )

    body = response.json()
    assert body["status"] == "partial"
    assert body["transactions_ingested"] == 1
    assert body["rejected"] == 1
    assert body["errors"][0]["index"] == 1


def test_pos_ingest_rejects_empty_batch(client: TestClient) -> None:
    response = client.post("/pos/ingest", json={"transactions": []})
    assert response.status_code == 422


def test_pos_ingest_returns_503_when_database_unavailable(client: TestClient) -> None:
    with patch("app.pos_ingestion.is_database_available", return_value=False):
        response = client.post(
            "/pos/ingest",
            json={"transactions": [_pos_payload()]},
        )
    assert response.status_code == 503


def test_pos_ingest_returns_503_on_database_error(client: TestClient) -> None:
    with patch(
        "app.pos_ingestion.session_scope",
        side_effect=SQLAlchemyError("boom"),
    ):
        response = client.post(
            "/pos/ingest",
            json={"transactions": [_pos_payload()]},
        )
    assert response.status_code == 503
