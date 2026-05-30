"""Tests for scripts/seed_from_sample.py idempotent seeding."""

from __future__ import annotations

import json
from pathlib import Path

from app.db import EventRecord, PosTransactionRecord, get_session, init_db
from scripts.seed_from_sample import seed_database


def _write_sample_events(path: Path) -> None:
    event = {
        "event_id": "550e8400-e29b-41d4-a716-446655440900",
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_seed01",
        "event_type": "ENTRY",
        "timestamp": "2026-03-03T14:00:00Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.9,
        "metadata": {"session_seq": 1},
    }
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")


def _write_pos_csv(path: Path) -> None:
    path.write_text(
        "store_id,transaction_id,timestamp,basket_value_inr\n"
        "STORE_BLR_002,TXN_SEED01,2026-03-03T14:05:00Z,250.00\n",
        encoding="utf-8",
    )


def test_seed_database_is_idempotent(tmp_path: Path) -> None:
    events_path = tmp_path / "sample_events.jsonl"
    pos_path = tmp_path / "pos_transactions.csv"
    _write_sample_events(events_path)
    _write_pos_csv(pos_path)

    init_db()
    first = seed_database(events_path=events_path, pos_path=pos_path)
    second = seed_database(events_path=events_path, pos_path=pos_path)

    assert first["events"]["inserted"] == 1
    assert first["pos_transactions"]["inserted"] == 1
    assert second["events"]["duplicates_skipped"] == 1
    assert second["pos_transactions"]["duplicates_skipped"] == 1

    session = get_session()
    try:
        assert session.get(EventRecord, "550e8400-e29b-41d4-a716-446655440900") is not None
        assert session.get(PosTransactionRecord, "TXN_SEED01") is not None
    finally:
        session.close()
