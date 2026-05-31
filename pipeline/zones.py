"""Zone mapping from bounding-box positions using polygon overlap."""

from __future__ import annotations

from typing import Dict, List, Tuple

import cv2
import numpy as np
import supervision as sv

from pipeline.config import MIN_OVERLAP_PCT, OUT_OF_ZONE


def denormalize_polygon(
    points: List[Tuple[float, float]],
    width: int,
    height: int,
) -> np.ndarray:
    """Convert normalized polygon vertices to pixel coordinates."""
    return np.array(
        [(int(x * width), int(y * height)) for x, y in points],
        dtype=np.int32,
    )


def build_zone_polygons(
    zone_definitions: Dict[str, List[Tuple[float, float]]],
    video_width: int,
    video_height: int,
) -> Dict[str, np.ndarray]:
    """Denormalize all zone polygons for a camera layout."""
    return {
        name: denormalize_polygon(points, video_width, video_height)
        for name, points in zone_definitions.items()
    }


def bbox_polygon_overlap_pct(
    xyxy: np.ndarray,
    polygon: np.ndarray,
    frame_width: int,
    frame_height: int,
) -> float:
    """Return percentage of bbox area overlapping the polygon."""
    x1, y1, x2, y2 = xyxy
    bbox_area = max(0.0, float(x2 - x1)) * max(0.0, float(y2 - y1))
    if bbox_area == 0:
        return 0.0

    ix1 = max(0, int(x1))
    iy1 = max(0, int(y1))
    ix2 = min(frame_width, int(x2))
    iy2 = min(frame_height, int(y2))
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0

    crop_w = ix2 - ix1
    crop_h = iy2 - iy1
    bbox_mask = np.full((crop_h, crop_w), 255, dtype=np.uint8)

    poly_shifted = polygon.copy()
    poly_shifted[:, 0] -= ix1
    poly_shifted[:, 1] -= iy1
    poly_mask = np.zeros((crop_h, crop_w), dtype=np.uint8)
    cv2.fillPoly(poly_mask, [poly_shifted.reshape(-1, 1, 2)], 255)

    overlap_pixels = cv2.countNonZero(cv2.bitwise_and(bbox_mask, poly_mask))
    return (float(overlap_pixels) / bbox_area) * 100.0


def resolve_zone_by_overlap(
    xyxy: np.ndarray,
    zone_polygons: Dict[str, np.ndarray],
    frame_width: int,
    frame_height: int,
    *,
    min_overlap_pct: float = MIN_OVERLAP_PCT,
) -> Tuple[str, int]:
    """Assign zone with highest bbox overlap percentage above threshold."""
    best_zone = OUT_OF_ZONE
    best_pct = 0.0
    for zone_name, polygon in zone_polygons.items():
        overlap_pct = bbox_polygon_overlap_pct(
            xyxy, polygon, frame_width, frame_height
        )
        if overlap_pct > best_pct:
            best_pct = overlap_pct
            best_zone = zone_name

    rounded_pct = int(round(best_pct))
    if best_pct < min_overlap_pct:
        return OUT_OF_ZONE, rounded_pct
    return best_zone, rounded_pct


def assign_track_zones(
    detections: sv.Detections,
    zone_polygons: Dict[str, np.ndarray],
    frame_width: int,
    frame_height: int,
    *,
    min_overlap_pct: float = MIN_OVERLAP_PCT,
) -> Dict[int, Tuple[str, int]]:
    """Map each tracked person to a zone and overlap percentage."""
    if detections.tracker_id is None or len(detections) == 0:
        return {}

    track_zones: Dict[int, Tuple[str, int]] = {}
    for track_id, xyxy in zip(detections.tracker_id, detections.xyxy):
        tid = int(track_id)
        track_zones[tid] = resolve_zone_by_overlap(
            xyxy,
            zone_polygons,
            frame_width,
            frame_height,
            min_overlap_pct=min_overlap_pct,
        )
    return track_zones
