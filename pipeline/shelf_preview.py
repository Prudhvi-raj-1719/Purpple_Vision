"""Annotated shelf-camera preview frames (zones + shopper boxes) for dashboards."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np
import supervision as sv

from pipeline.config import MIN_OVERLAP_PCT
from pipeline.detect import detect_persons, load_yolo_model
from pipeline.tracker import create_byte_tracker, update_tracks
from pipeline.store_config import StoreConfig, resolve_store_config, zones_as_legacy_dict
from pipeline.zones import assign_track_zones, build_zone_polygons

# BGR palette for zone overlays
_ZONE_COLORS: List[Tuple[int, int, int]] = [
    (180, 120, 60),
    (60, 180, 90),
    (90, 90, 220),
    (60, 160, 220),
    (200, 120, 200),
    (80, 200, 200),
    (140, 140, 60),
    (200, 160, 80),
    (100, 100, 200),
]


def _friendly_zone_label(zone_id: str) -> str:
    return zone_id.replace("_", " ").strip().title()


def draw_zone_overlays(
    frame_bgr: np.ndarray,
    zone_polygons: Dict[str, np.ndarray],
) -> np.ndarray:
    """Draw semi-transparent zone polygons with labels (validation-style overlay)."""
    out = frame_bgr.copy()
    for idx, (zone_id, polygon) in enumerate(zone_polygons.items()):
        color = _ZONE_COLORS[idx % len(_ZONE_COLORS)]
        pts = polygon.reshape((-1, 1, 2)).astype(np.int32)
        overlay = out.copy()
        cv2.fillPoly(overlay, [pts], color)
        cv2.addWeighted(overlay, 0.28, out, 0.72, 0, out)
        cv2.polylines(out, [pts], isClosed=True, color=color, thickness=2, lineType=cv2.LINE_AA)
        centroid = polygon.mean(axis=0).astype(int)
        label = _friendly_zone_label(zone_id)
        cv2.putText(
            out,
            label,
            (int(centroid[0]) - 40, int(centroid[1])),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
    return out


def annotate_shoppers(
    frame_bgr: np.ndarray,
    detections: sv.Detections,
    track_zones: Dict[int, Tuple[str, int]],
) -> np.ndarray:
    """Draw bounding boxes and shopper IDs with current aisle/brand zone."""
    annotated = frame_bgr.copy()
    if len(detections) == 0:
        return annotated

    box_annotator = sv.BoxAnnotator(thickness=2, color=sv.Color.from_hex("#22c55e"))
    label_annotator = sv.LabelAnnotator(
        text_scale=0.55,
        text_thickness=1,
        text_color=sv.Color.from_hex("#FFFFFF"),
    )

    labels: List[str] = []
    if detections.tracker_id is not None:
        for track_id in detections.tracker_id:
            tid = int(track_id)
            zone_name, overlap = track_zones.get(tid, ("—", 0))
            zone_display = _friendly_zone_label(zone_name) if zone_name != "—" else "Aisle"
            labels.append(f"Shopper {tid} · {zone_display} ({overlap}%)")
    else:
        labels = ["Shopper"] * len(detections)

    annotated = box_annotator.annotate(scene=annotated, detections=detections)
    return label_annotator.annotate(scene=annotated, detections=detections, labels=labels)


def compose_tracking_frame(
    frame_bgr: np.ndarray,
    zone_polygons: Dict[str, np.ndarray],
    detections: sv.Detections,
    track_zones: Dict[int, Tuple[str, int]],
) -> np.ndarray:
    """Combine zone polygons and shopper boxes on one BGR frame (no inference)."""
    out = draw_zone_overlays(frame_bgr, zone_polygons)
    return annotate_shoppers(out, detections, track_zones)


def draw_tracking_hud(
    frame_bgr: np.ndarray,
    *,
    camera_label: str,
    aisle_visits: int,
    frame_idx: int,
) -> np.ndarray:
    """Small on-screen summary for recorded / live validation video."""
    out = frame_bgr.copy()
    lines = [
        camera_label,
        f"Aisle visits: {aisle_visits}",
        f"Frame: {frame_idx}",
    ]
    panel_h = 12 + 26 * len(lines)
    cv2.rectangle(out, (8, 8), (300, 8 + panel_h), (0, 0, 0), -1)
    for i, text in enumerate(lines):
        cv2.putText(
            out,
            text,
            (16, 32 + i * 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 120),
            2,
            cv2.LINE_AA,
        )
    return out


def open_mp4_writer(path: Path, width: int, height: int, fps: float) -> cv2.VideoWriter:
    """
    Write annotated shelf tracking MP4.

    Prefer ``mp4v`` on Windows — OpenCV's H.264/OpenH264 writer often fails
    (see ``Failed to initialize VideoWriter``). Dashboard converts to browser
    H.264 via FFmpeg when available (``*_web.mp4``).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    for fourcc_str in ("mp4v", "XVID", "MJPG"):
        fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
        writer = cv2.VideoWriter(str(path), fourcc, max(1.0, fps), (width, height))
        if writer.isOpened():
            return writer
    raise RuntimeError(f"Unable to open video writer: {path}")


def shelf_tracking_output_path(store_output_dir: Path, camera_key: str) -> Path:
    """Standard annotated MP4 path next to camN_events.jsonl (e.g. cam1_tracking.mp4)."""
    return store_output_dir / f"{camera_key.lower()}_tracking.mp4"


def render_shelf_preview_frame(
    frame_bgr: np.ndarray,
    *,
    zone_definitions: Dict[str, List[Tuple[float, float]]],
    min_overlap_pct: float = MIN_OVERLAP_PCT,
) -> np.ndarray:
    """Run detection on one frame and return zones + shopper overlay."""
    height, width = frame_bgr.shape[:2]
    zone_polygons = build_zone_polygons(zone_definitions, width, height)
    yolo = load_yolo_model()
    tracker = create_byte_tracker()
    detections = detect_persons(frame_bgr, yolo)
    detections = update_tracks(tracker, detections)
    track_zones = assign_track_zones(
        detections,
        zone_polygons,
        width,
        height,
        min_overlap_pct=min_overlap_pct,
    )
    return compose_tracking_frame(frame_bgr, zone_polygons, detections, track_zones)


def read_video_frame(video_path: Path, frame_index: int) -> np.ndarray | None:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return None
    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_index))
        success, frame = capture.read()
        if not success or frame is None:
            return None
        return frame
    finally:
        capture.release()


def capture_tracking_mp4_preview_png(
    video_path: Path,
    *,
    frame_fraction: float = 0.45,
) -> bytes | None:
    """
    PNG from an existing ``*_tracking.mp4`` without re-running YOLO.

    The pipeline already burned zones and shopper boxes into the MP4; the dashboard
    only grabs one representative frame (lightweight, safe when RAM is tight).
    """
    if not video_path.is_file():
        return None
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return None
    try:
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        idx = int(total * frame_fraction) if total > 0 else 0
        capture.set(cv2.CAP_PROP_POS_FRAMES, idx)
        success, frame = capture.read()
        if not success or frame is None:
            return None
        ok, buf = cv2.imencode(".png", frame)
        if not ok:
            return None
        return buf.tobytes()
    finally:
        capture.release()


def capture_shelf_preview_png(
    video_path: Path,
    *,
    store: StoreConfig | None = None,
    camera_key: str = "CAM1",
    frame_fraction: float = 0.45,
) -> bytes | None:
    """
    Return one annotated PNG (zones + boxes) from a representative video frame.

    Re-runs YOLO on a raw frame. Prefer :func:`capture_tracking_mp4_preview_png`
    when ``*_tracking.mp4`` already exists.
    """
    cfg = resolve_store_config(store)
    cam_cfg = cfg.cam1 if camera_key == "CAM1" else cfg.cam2
    if not cam_cfg.enabled:
        return None

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return None
    try:
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        idx = int(total * frame_fraction) if total > 0 else 0
        capture.set(cv2.CAP_PROP_POS_FRAMES, idx)
        success, frame = capture.read()
        if not success or frame is None:
            return None
        annotated = render_shelf_preview_frame(
            frame,
            zone_definitions=zones_as_legacy_dict(cam_cfg.zones),
            min_overlap_pct=cam_cfg.overlap.min_overlap_pct,
        )
        ok, buf = cv2.imencode(".png", annotated)
        if not ok:
            return None
        return buf.tobytes()
    finally:
        capture.release()
