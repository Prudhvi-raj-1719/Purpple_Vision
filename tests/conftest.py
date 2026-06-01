"""Shared pytest fixtures for API tests."""

from __future__ import annotations

import os

# Must be set before app.db is imported by test modules.
os.environ["DATABASE_URL"] = "sqlite:///./data/databases/test_api.db"

import pytest
from fastapi.testclient import TestClient

from app.db import drop_all_tables, init_db
from app.main import app


@pytest.fixture(autouse=True)
def fresh_database() -> None:
    """Provide a clean database for every test."""
    drop_all_tables()
    init_db()
    yield
    drop_all_tables()


@pytest.fixture
def client() -> TestClient:
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def sample_entry_event() -> dict:
    """Valid ENTRY event payload."""
    return {
        "event_id": "550e8400-e29b-41d4-a716-446655440000",
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_c8a2f1",
        "event_type": "ENTRY",
        "timestamp": "2026-03-03T14:22:10Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.92,
        "metadata": {"session_seq": 1},
    }
    