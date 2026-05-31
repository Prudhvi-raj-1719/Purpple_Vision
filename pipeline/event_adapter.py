"""Convert NOTEBK JSONL event rows into Purpple_Vision Event models."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from app.models import Event, EventMetadata, EventType

from pipeline.config import (
    CAMERA_PURPPLE_IDS,
    DEFAULT_CONFIDENCE,
    DEFAULT_STORE_ID,
    MIN_ZONE_DWELL_MS,
    parse_clip_start,
)

logger = logging.getLogger(__name__)

VIDEO_OFFSET_RE = re.compile(
    r"^(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$"
)
ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
)

ZONE_ID_MAP: dict[str, str] = {
    "PaymentArea": "BILLING",
    "BillingQueue": "BILLING",
    # CAM1 shelf brands (original names preserved in metadata.sku_zone)
    "FarmStay": "FARMSTAY",
    "TheFaceShop": "THEFACESHOP",
    "GoodVibes": "GOODVIBES",
    "DermaCo": "DERMACO",
    "Minimalist": "MINIMALIST",
    "Minimalist_top": "MINIMALIST_TOP",
    "Aquologica": "AQUOLOGICA",
    "Pilgrim": "PILGRIM",
    "D&K": "D_AND_K",
    # CAM2 shelf brands
    "LAKME": "LAKME",
    "MAYBELLINE": "MAYBELLINE",
    "FACESCANADA": "FACESCANADA",
    "swiss Beauty": "SWISS_BEAUTY",
    "MARS": "MARS",
    "ALPS": "ALPS",
    "LOREAL": "LOREAL",
    "EASTIND": "EASTIND",
}

EVENT_TYPE_MAP: dict[str, EventType] = {
    "ENTRY": EventType.ENTRY,
    "EXIT": EventType.EXIT,
    "REENTRY": EventType.REENTRY,
    "ZONE_ENTER": EventType.ZONE_ENTER,
    "ZONE_EXIT": EventType.ZONE_EXIT,
    "DWELL_COMPLETED": EventType.ZONE_DWELL,
    "QUEUE_ENTER": EventType.BILLING_QUEUE_JOIN,
    "QUEUE_EXIT": EventType.BILLING_QUEUE_ABANDON,
    "PAYMENT_ENTER": EventType.ZONE_ENTER,
    "PAYMENT_EXIT": EventType.ZONE_EXIT,
}


def _parse_video_offset_seconds(offset_timestamp: str) -> float:
    match = VIDEO_OFFSET_RE.match(offset_timestamp.strip())
    if not match:
        raise ValueError(f"Invalid video offset timestamp: {offset_timestamp}")
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    fraction = match.group(4) or "0"
    millis = int(fraction.ljust(3, "0")[:3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def resolve_utc_timestamp(
    timestamp: str,
    camera_key: str,
    *,
    clip_start: datetime | None = None,
) -> datetime:
    """Map NOTEBK timestamp (offset or ISO) to UTC-aware datetime."""
    text = str(timestamp).strip()
    if ISO_DATETIME_RE.match(text):
        normalized = text.replace(" ", "T")
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    start = clip_start or parse_clip_start(camera_key)
    start_utc = start.replace(tzinfo=timezone.utc)
    delta = timedelta(seconds=_parse_video_offset_seconds(text))
    return start_utc + delta


def map_visitor_id(raw_visitor_id: Any) -> str:
    """Map NOTEBK numeric track id to VIS_* challenge pattern."""
    if isinstance(raw_visitor_id, str) and raw_visitor_id.startswith("VIS_"):
        return raw_visitor_id
    return f"VIS_{int(raw_visitor_id)}"


def map_camera_id(camera_key: str) -> str:
    return CAMERA_PURPPLE_IDS.get(camera_key, f"CAM_{camera_key.replace('CAM', '')}")


def map_zone_id(zone: Any, event_type: EventType) -> str | None:
    if event_type in (EventType.ENTRY, EventType.EXIT, EventType.REENTRY):
        return None
    if zone is None or str(zone).strip() == "":
        if event_type in (EventType.BILLING_QUEUE_JOIN, EventType.BILLING_QUEUE_ABANDON):
            return "BILLING"
        return None
    zone_name = str(zone)
    if zone_name in ZONE_ID_MAP:
        return ZONE_ID_MAP[zone_name]
    normalized = zone_name.upper().replace(" ", "_").replace("&", "AND")
    return normalized[:64]


def map_event_type(notbk_type: str) -> EventType:
    mapped = EVENT_TYPE_MAP.get(notbk_type)
    if mapped is None:
        raise ValueError(f"Unsupported NOTEBK event_type: {notbk_type}")
    return mapped


def resolve_dwell_ms(row: dict[str, Any], event_type: EventType) -> int:
    if event_type != EventType.ZONE_DWELL:
        return 0
    dwell_seconds = row.get("dwell_seconds")
    if dwell_seconds is None:
        return MIN_ZONE_DWELL_MS
    dwell_ms = int(float(dwell_seconds) * 1000)
    return max(dwell_ms, MIN_ZONE_DWELL_MS)


def build_metadata(row: dict[str, Any], event_type: EventType) -> EventMetadata:
    metadata = EventMetadata()
    zone = row.get("zone")
    if zone:
        metadata.sku_zone = str(zone)
    if event_type == EventType.BILLING_QUEUE_JOIN:
        metadata.queue_depth = int(row.get("queue_depth") or 1)
    return metadata


def notbk_event_to_event(
    row: dict[str, Any],
    *,
    store_id: str = DEFAULT_STORE_ID,
    clip_start: datetime | None = None,
    confidence: float = DEFAULT_CONFIDENCE,
    is_staff: bool = False,
) -> Event:
    """
    Convert a NOTEBK event dict to a Purpple_Vision Event.

    Expected NOTEBK keys: visitor_id, camera, event_type, timestamp;
    optional: zone, dwell_seconds, event_datetime, queue_depth.
    """
    camera_key = str(row["camera"])
    event_type = map_event_type(str(row["event_type"]))
    timestamp = resolve_utc_timestamp(
        str(row.get("event_datetime") or row["timestamp"]),
        camera_key,
        clip_start=clip_start,
    )
    dwell_ms = resolve_dwell_ms(row, event_type)
    if event_type == EventType.ZONE_DWELL and dwell_ms < MIN_ZONE_DWELL_MS:
        dwell_ms = MIN_ZONE_DWELL_MS

    zone_id = map_zone_id(row.get("zone"), event_type)

    return Event(
        event_id=uuid4(),
        store_id=store_id,
        camera_id=map_camera_id(camera_key),
        visitor_id=map_visitor_id(row["visitor_id"]),
        event_type=event_type,
        timestamp=timestamp,
        zone_id=zone_id,
        dwell_ms=dwell_ms,
        is_staff=is_staff,
        confidence=float(row.get("confidence", confidence)),
        metadata=build_metadata(row, event_type),
    )


def notbk_event_to_json_dict(
    row: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Serialize adapted event for JSONL (JSON-compatible dict)."""
    event = notbk_event_to_event(row, **kwargs)
    return event.model_dump(mode="json")
