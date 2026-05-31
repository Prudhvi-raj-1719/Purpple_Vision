"""Offline invoice-centric purchase matching (ported from NOTEBK purchase_matching.py)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pipeline.config import (
    AGGREGATED_TRANSACTIONS_JSON,
    PIPELINE_DEMO_DIR,
    PURCHASE_MATCHES_JSON,
)
from pipeline.event_adapter import resolve_utc_timestamp
from pipeline.pos_loader import load_aggregated_transactions

logger = logging.getLogger(__name__)

MATCH_WINDOW_MINUTES = 5

ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")

QUEUE_EVENT_TYPES = frozenset({"QUEUE_ENTER", "QUEUE_EXIT"})
PAYMENT_EVENT_TYPES = frozenset({"PAYMENT_ENTER", "PAYMENT_EXIT"})
ZONE_ENTER = "ZONE_ENTER"
QUEUE_ZONE_NAMES = frozenset({"BillingQueue"})
PAYMENT_ZONE_NAMES = frozenset({"PaymentArea"})

DEFAULT_EVENT_FILES: dict[str, Path] = {
    "CAM1": PIPELINE_DEMO_DIR / "cam1_events.notbk.jsonl",
    "CAM2": PIPELINE_DEMO_DIR / "cam2_events.notbk.jsonl",
    "CAM5": PIPELINE_DEMO_DIR / "cam5_events.notbk.jsonl",
}


@dataclass
class MatchingStats:
    total_invoices: int = 0
    matched_invoices: int = 0
    unmatched_invoices: int = 0
    confidence_scores: list[float] = field(default_factory=list)
    load_notes: list[str] = field(default_factory=list)


def parse_event_datetime(value: str) -> datetime:
    """Parse NOTEBK-style event_datetime string to naive datetime."""
    text = value.strip().replace(" ", "T")
    if "." in text:
        base, frac = text.split(".", 1)
        millis = int(frac.ljust(3, "0")[:3])
        return datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(
            microsecond=millis * 1000
        )
    return datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")


def parse_transaction_datetime(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")


def format_transaction_datetime(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_event_datetime(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def resolve_event_wall_clock(event: dict[str, Any], camera_id: str) -> datetime | None:
    """Resolve pipeline demo event timestamp to naive wall-clock datetime."""
    raw = event.get("event_datetime") or event.get("timestamp")
    if raw is None:
        return None
    text = str(raw).strip()
    if ISO_DATETIME_RE.match(text):
        return parse_event_datetime(text)
    utc_dt = resolve_utc_timestamp(text, camera_id)
    return utc_dt.replace(tzinfo=None)


def discover_event_file(camera_id: str, demo_dir: Path | None = None) -> Path | None:
    """Prefer camN_events.notbk.jsonl, fallback to camN_events.jsonl."""
    base = demo_dir or PIPELINE_DEMO_DIR
    cam_lower = camera_id.lower()
    for name in (f"{cam_lower}_events.notbk.jsonl", f"{cam_lower}_events.jsonl"):
        path = base / name
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def build_default_event_files(demo_dir: Path | None = None) -> dict[str, Path]:
    """Build camera → event file map from pipeline_demo directory."""
    base = demo_dir or PIPELINE_DEMO_DIR
    files: dict[str, Path] = {}
    for camera_id in ("CAM1", "CAM2", "CAM5"):
        path = discover_event_file(camera_id, base)
        if path is not None:
            files[camera_id] = path
    return files


def load_events_by_camera(
    event_files: dict[str, Path],
    stats: MatchingStats,
) -> dict[str, list[dict[str, Any]]]:
    """Load and normalize CCTV events; attach _parsed_datetime for window search."""
    by_camera: dict[str, list[dict[str, Any]]] = {
        camera: [] for camera in event_files
    }

    for camera_id, path in event_files.items():
        if not path.exists():
            stats.load_notes.append(f"{path.name}: missing (0 events)")
            continue

        count = 0
        with path.open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    stats.load_notes.append(
                        f"{path.name} line {line_no}: JSON error ({exc})"
                    )
                    continue

                parsed = resolve_event_wall_clock(event, camera_id)
                if parsed is None:
                    stats.load_notes.append(
                        f"{path.name} line {line_no}: missing timestamp"
                    )
                    continue

                event["_parsed_datetime"] = parsed
                event["event_datetime"] = format_event_datetime(parsed)
                event.setdefault("camera", camera_id)
                by_camera[camera_id].append(event)
                count += 1

        stats.load_notes.append(f"{path.name}: {count} events")

    for events in by_camera.values():
        events.sort(key=lambda item: item["_parsed_datetime"])

    return by_camera


def events_in_window(
    events: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if window_start <= event["_parsed_datetime"] <= window_end
    ]


def export_event(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if not key.startswith("_")}


def has_queue_activity(events: list[dict[str, Any]]) -> bool:
    for event in events:
        if event.get("event_type") in QUEUE_EVENT_TYPES:
            return True
        if event.get("zone") in QUEUE_ZONE_NAMES:
            return True
    return False


def has_payment_activity(events: list[dict[str, Any]]) -> bool:
    for event in events:
        if event.get("event_type") in PAYMENT_EVENT_TYPES:
            return True
        if event.get("zone") in PAYMENT_ZONE_NAMES:
            return True
    return False


def zones_visited(events: list[dict[str, Any]]) -> list[str]:
    zones: list[str] = []
    seen: set[str] = set()
    for event in events:
        if event.get("event_type") != ZONE_ENTER:
            continue
        zone = event.get("zone")
        if not zone or zone in seen:
            continue
        seen.add(str(zone))
        zones.append(str(zone))
    return zones


def count_zone_interactions(events: list[dict[str, Any]]) -> int:
    count = 0
    for event in events:
        event_type = event.get("event_type", "")
        if event_type in (ZONE_ENTER, "ZONE_EXIT", "DWELL_COMPLETED"):
            count += 1
        elif event_type in QUEUE_EVENT_TYPES | PAYMENT_EVENT_TYPES:
            count += 1
    return count


def temporal_proximity_score(
    nearby_events: list[dict[str, Any]],
    transaction_dt: datetime,
    window_seconds: float,
) -> float:
    if not nearby_events:
        return 0.0

    min_delta = min(
        abs((event["_parsed_datetime"] - transaction_dt).total_seconds())
        for event in nearby_events
    )
    if window_seconds <= 0:
        return 0.0
    closeness = 1.0 - min(min_delta / window_seconds, 1.0)
    return closeness * 0.35


def compute_confidence_score(
    nearby_events: list[dict[str, Any]],
    transaction_dt: datetime,
    window_minutes: int,
) -> float:
    if not nearby_events:
        return 0.0

    score = 0.15
    window_seconds = window_minutes * 60.0

    if has_payment_activity(nearby_events):
        score += 0.25
    if has_queue_activity(nearby_events):
        score += 0.20

    zone_interactions = count_zone_interactions(nearby_events)
    if zone_interactions >= 3:
        score += 0.20
    elif zone_interactions >= 1:
        score += 0.10

    score += temporal_proximity_score(
        nearby_events, transaction_dt, window_seconds
    )

    return round(min(score, 1.0), 2)


def build_journey_summary(nearby_events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "zones_visited": zones_visited(nearby_events),
        "queue_activity": has_queue_activity(nearby_events),
        "payment_activity": has_payment_activity(nearby_events),
    }


def match_transaction(
    transaction: dict[str, Any],
    events_by_camera: dict[str, list[dict[str, Any]]],
    window: timedelta,
) -> dict[str, Any]:
    """Match one POS invoice to nearby CCTV events across CAM1/CAM2/CAM5."""
    raw_dt = transaction.get("transaction_datetime")
    if not raw_dt:
        return {
            "invoice_number": transaction.get("invoice_number", ""),
            "transaction_datetime": None,
            "match_found": False,
            "reason": "Missing transaction_datetime",
        }

    transaction_dt = parse_transaction_datetime(str(raw_dt))
    window_start = transaction_dt - window
    window_end = transaction_dt + window

    cam1_nearby = events_in_window(
        events_by_camera.get("CAM1", []), window_start, window_end
    )
    cam2_nearby = events_in_window(
        events_by_camera.get("CAM2", []), window_start, window_end
    )
    cam5_nearby = events_in_window(
        events_by_camera.get("CAM5", []), window_start, window_end
    )

    candidate_customer_journey = {
        "cam1_events": [export_event(event) for event in cam1_nearby],
        "cam2_events": [export_event(event) for event in cam2_nearby],
        "cam5_events": [export_event(event) for event in cam5_nearby],
    }

    matching_events = (
        candidate_customer_journey["cam1_events"]
        + candidate_customer_journey["cam2_events"]
        + candidate_customer_journey["cam5_events"]
    )
    matching_events.sort(key=lambda item: item.get("event_datetime", ""))

    brands = transaction.get("brand_names") or []
    base_record: dict[str, Any] = {
        "invoice_number": transaction.get("invoice_number", ""),
        "transaction_datetime": str(raw_dt),
        "brands_purchased": brands,
        "total_amount": transaction.get("total_amount"),
        "match_window_minutes": MATCH_WINDOW_MINUTES,
        "search_window": {
            "from": format_transaction_datetime(window_start),
            "to": format_transaction_datetime(window_end),
        },
        "candidate_customer_journey": candidate_customer_journey,
    }

    if not matching_events:
        return {
            **base_record,
            "match_found": False,
            "reason": "No CCTV events in time window",
            "matching_events": [],
            "confidence_score": 0.0,
            "journey_summary": {
                "zones_visited": [],
                "queue_activity": False,
                "payment_activity": False,
            },
        }

    all_nearby_parsed = cam1_nearby + cam2_nearby + cam5_nearby
    confidence = compute_confidence_score(
        all_nearby_parsed, transaction_dt, MATCH_WINDOW_MINUTES
    )

    return {
        **base_record,
        "match_found": True,
        "matching_events": matching_events,
        "confidence_score": confidence,
        "journey_summary": build_journey_summary(all_nearby_parsed),
    }


def average_confidence(scores: list[float]) -> float | None:
    if not scores:
        return None
    return round(sum(scores) / len(scores), 2)


def run_matching(
    *,
    transactions_path: Path | None = None,
    event_files: dict[str, Path] | None = None,
    demo_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], MatchingStats]:
    """Run invoice-centric purchase matching on aggregated POS + pipeline demo events."""
    stats = MatchingStats()
    files = event_files or build_default_event_files(demo_dir)
    events_by_camera = load_events_by_camera(files, stats)

    if transactions_path is not None:
        with transactions_path.open(encoding="utf-8") as handle:
            transactions = json.load(handle)
    else:
        transactions = load_aggregated_transactions()

    if not isinstance(transactions, list):
        raise ValueError("Expected aggregated transactions JSON array")

    stats.total_invoices = len(transactions)
    window = timedelta(minutes=MATCH_WINDOW_MINUTES)
    results: list[dict[str, Any]] = []

    for transaction in transactions:
        record = match_transaction(transaction, events_by_camera, window)
        results.append(record)

        if record.get("match_found"):
            stats.matched_invoices += 1
            stats.confidence_scores.append(float(record.get("confidence_score", 0.0)))
        else:
            stats.unmatched_invoices += 1

    return results, stats


def save_purchase_matches(
    results: list[dict[str, Any]],
    output_path: Path | None = None,
) -> Path:
    """Write purchase_matches.json."""
    out = output_path or PURCHASE_MATCHES_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out


def run_cli(
    *,
    transactions_path: Path | None = None,
    demo_dir: Path | None = None,
    output_path: Path | None = None,
) -> tuple[list[dict[str, Any]], MatchingStats, Path]:
    """CLI: match invoices, write JSON, print summary."""
    results, stats = run_matching(
        transactions_path=transactions_path,
        demo_dir=demo_dir,
    )
    out = save_purchase_matches(results, output_path)

    avg_conf = average_confidence(stats.confidence_scores)
    print("Purchase matching (offline)")
    print("=" * 50)
    print(f"Match window: +/- {MATCH_WINDOW_MINUTES} minutes")
    print(f"Total invoices: {stats.total_invoices}")
    print(f"Matched: {stats.matched_invoices}")
    print(f"Unmatched: {stats.unmatched_invoices}")
    if avg_conf is not None:
        print(f"Average confidence (matched): {avg_conf}")
    else:
        print("Average confidence (matched): N/A")
    print("\nEvent file notes:")
    for note in stats.load_notes:
        print(f"  {note}")
    print(f"\nWrote: {out}")
    return results, stats, out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_cli()
