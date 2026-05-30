"""Tests for GET /health endpoint."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient


def test_health_returns_ok_when_database_available(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database_available"] is True
    assert "timestamp" in body


def test_health_returns_degraded_when_database_unavailable(client: TestClient) -> None:
    with patch("app.health.is_database_available", return_value=False):
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database_available"] is False
