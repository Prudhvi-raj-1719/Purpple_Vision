"""
Map ``StoreConfig`` → CAM5 runtime settings (zones, overlap, dwell, detection).

Migrated from NOTEBK ``events/cam5_events.py``; consumed by ``cam5_processor``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipeline.store_config import StoreConfig, get_store_config

CAMERA_KEY = "CAM5"
OUT_OF_ZONE = "OUT_OF_ZONE"
PAYMENT_ZONE = "PaymentArea"
QUEUE_ZONE = "BillingQueue"


@dataclass(frozen=True)
class Cam5ProcessorConfig:
    """Fully store-driven CAM5 settings from ``stores/*/cam5.json``."""

    store_key: str
    store_id: str
    camera_key: str
    competition_camera_id: str
    coordinate_system: str
    process_every_n_frames: int
    progress_log_every_n_frames: int
    confidence_threshold: float
    iou_threshold: float
    min_overlap_pct: float
    min_zone_stability_frames: int
    lost_track_frames: int
    min_dwell_seconds: float
    min_zone_dwell_ms: int
    zone_priority: tuple[str, ...]
    payment_zone: str
    queue_zone: str
    yolo_model_path: Path
    primary_video_path: Path | None
    default_events_output_path: Path
    pipeline_output_dir: Path


def build_cam5_processor_config(
    store: StoreConfig | None = None,
) -> Cam5ProcessorConfig:
    """Hydrate CAM5 config from active store (``PURPPLE_STORE`` when ``store`` omitted)."""
    resolved = store if store is not None else get_store_config()
    cam5 = resolved.cam5
    detection = cam5.detection
    overlap = cam5.overlap
    dwell = cam5.dwell

    priority = cam5.zone_priority or (PAYMENT_ZONE, QUEUE_ZONE)
    payment = PAYMENT_ZONE if PAYMENT_ZONE in cam5.zones else priority[0]
    queue = QUEUE_ZONE if QUEUE_ZONE in cam5.zones else (
        priority[1] if len(priority) > 1 else QUEUE_ZONE
    )

    return Cam5ProcessorConfig(
        store_key=resolved.store_key,
        store_id=resolved.store_id,
        camera_key=cam5.camera_key,
        competition_camera_id=cam5.competition_camera_id,
        coordinate_system=cam5.coordinate_system,
        process_every_n_frames=detection.process_every_n_frames,
        progress_log_every_n_frames=detection.progress_log_every_n_frames,
        confidence_threshold=detection.confidence_threshold,
        iou_threshold=detection.iou_threshold,
        min_overlap_pct=overlap.min_overlap_pct,
        min_zone_stability_frames=overlap.min_zone_stability_frames,
        lost_track_frames=overlap.lost_track_frames,
        min_dwell_seconds=dwell.min_dwell_seconds,
        min_zone_dwell_ms=dwell.min_zone_dwell_ms,
        zone_priority=priority,
        payment_zone=payment,
        queue_zone=queue,
        yolo_model_path=resolved.yolo_model_path,
        primary_video_path=resolved.videos.video_path(CAMERA_KEY),
        default_events_output_path=resolved.pipeline_output_dir / "cam5_events.jsonl",
        pipeline_output_dir=resolved.pipeline_output_dir,
    )
