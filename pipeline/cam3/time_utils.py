"""
CAM3 UTC helpers (ported from NOTEBK events/event_time.py).

Phase B will route clip anchors through store_config / parse_clip_start.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

VIDEO_OFFSET_RE = re.compile(
    r"^(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$"
)


def parse_offset_seconds(offset_timestamp: str) -> float:
    match = VIDEO_OFFSET_RE.match(offset_timestamp.strip())
    if not match:
        raise ValueError(f"Invalid video offset: {offset_timestamp}")
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    fraction = match.group(4) or "0"
    millis = int(fraction.ljust(3, "0")[:3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def _parse_anchor(anchor: str) -> datetime:
    return datetime.strptime(anchor, "%Y-%m-%d %H:%M:%S")


def resolve_recording_start(
    notbk_camera_id: str,
    *,
    clip_id: Optional[str] = None,
    clip_start_by_key: Optional[dict[str, str]] = None,
) -> datetime:
    """
    Resolve wall-clock anchor for a camera or CAM3 clip.

    Phase A: optional ``clip_start_by_key`` from caller; Phase B uses store videos.
    """
    if clip_id and clip_start_by_key:
        clip_key = f"CAM3:{clip_id}"
        raw = clip_start_by_key.get(clip_key) or clip_start_by_key.get(clip_id)
        if raw:
            return _parse_anchor(raw)

    if clip_start_by_key and notbk_camera_id in clip_start_by_key:
        return _parse_anchor(clip_start_by_key[notbk_camera_id])

    # Fallback until Phase B wires store_config exclusively.
    from pipeline.config import CAMERA_CLIP_START, parse_clip_start

    if clip_id:
        return parse_clip_start(notbk_camera_id, clip_id=clip_id)
    return parse_clip_start(notbk_camera_id)


def video_offset_to_utc_iso(
    notbk_camera_id: str,
    video_offset: str,
    *,
    clip_id: Optional[str] = None,
    clip_start_by_key: Optional[dict[str, str]] = None,
) -> str:
    """Convert HH:MM:SS.mmm offset to ISO8601 UTC (naive UTC, suffixed with Z)."""
    start = resolve_recording_start(
        notbk_camera_id,
        clip_id=clip_id,
        clip_start_by_key=clip_start_by_key,
    )
    delta = timedelta(seconds=parse_offset_seconds(video_offset))
    dt = start + delta
    millis = int(dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utc_iso_to_datetime(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
