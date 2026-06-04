from __future__ import annotations

import json
from pathlib import Path

from app.ingestion import ingest_event_dicts


def _load_demo_events() -> list[dict]:
    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / "data" / "synthetic" / "store_1" / "synthetic_events_store_1.jsonl"
    events: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def test_staff_analysis_endpoint_returns_classifications_sorted(client) -> None:
    events = _load_demo_events()

    # Ingest in batches (ingestion limit is 500).
    batch_size = 500
    for start in range(0, len(events), batch_size):
        result = ingest_event_dicts(events[start : start + batch_size])
        assert result.rejected == 0

    resp = client.get("/stores/STORE_BLR_002/staff-analysis?date=2026-06-01")
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["store_id"] == "STORE_BLR_002"
    assert payload["date"] == "2026-06-01"
    assert payload["total_visitors"] > 0
    assert payload["staff_detected"] > 0

    summary = payload["summary"]
    assert summary["raw_visitors"] == payload["total_visitors"]
    assert summary["staff_detected"] == payload["staff_detected"]
    assert summary["staff_detected"] > 0
    assert summary["customer_visitors"] == summary["raw_visitors"] - summary["staff_detected"]
    assert summary["raw_sessions"] > summary["customer_sessions"]
    assert summary["raw_sessions"] - summary["customer_sessions"] == (
        summary["staff_detected"] * 4
    )

    classifications = payload["classifications"]
    assert isinstance(classifications, list)
    assert len(classifications) == payload["total_visitors"]

    # Sorting: staff_score descending, visitor_id ascending.
    keys = [(-c["staff_score"], c["visitor_id"]) for c in classifications]
    assert keys == sorted(keys)

    # Ensure demo staff visitors are present with evidence and explanatory reasons.
    by_id = {c["visitor_id"]: c for c in classifications}
    for staff_id in ("VIS_staff001", "VIS_staff002", "VIS_staff003"):
        assert staff_id in by_id
        assert by_id[staff_id]["is_staff"] is True
        assert by_id[staff_id]["staff_score"] >= 3

        evidence = by_id[staff_id]["evidence"]
        assert evidence["session_count"] >= 4
        assert evidence["reentry_count"] >= 3
        assert evidence["unique_zones_visited"] >= 8
        assert evidence["total_store_time_seconds"] >= 1800

        reasons = by_id[staff_id]["reasons"]
        assert any(
            f"Store time {evidence['total_store_time_seconds']}s" in r and "1800s" in r
            for r in reasons
        )
        assert any(
            f"Re-entry count {evidence['reentry_count']}" in r and "threshold 3" in r
            for r in reasons
        )
        assert any(
            f"Visited {evidence['unique_zones_visited']} unique zones" in r
            and "threshold 8" in r
            for r in reasons
        )
        assert any(
            f"Session count {evidence['session_count']}" in r and "threshold 4" in r
            for r in reasons
        )

