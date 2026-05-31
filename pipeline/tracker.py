"""Multi-object tracking with ByteTrack."""

from __future__ import annotations

import supervision as sv


def create_byte_tracker() -> sv.ByteTrack:
    """Create a ByteTrack multi-object tracker."""
    return sv.ByteTrack()


def update_tracks(
    tracker: sv.ByteTrack,
    detections: sv.Detections,
) -> sv.Detections:
    """Associate detections with persistent track IDs."""
    return tracker.update_with_detections(detections)
