"""
Map ``StoreConfig`` → CAM3 runtime (layout, detection, clips, Re-ID).

All CAM3 behavior is driven by ``get_store_config()`` / ``stores/*/cam3.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.reid.settings import ReidSettings, reid_settings_from_config
from pipeline.store_config import StoreConfig, get_store_config

CAMERA_KEY = "CAM3"
PERSON_CLASS_ID = 0
ENTRY_POLYGON_COLOR: tuple[int, int, int] = (0, 0, 255)


def _line_style_to_notbk(style: str) -> str:
    if style == "horizontal_y":
        return "horizontal_y"
    if style == "polygon":
        return "quad_lr"
    return style


def build_cam3_layout(store: StoreConfig) -> dict[str, Any]:
    """Layout dict for ``build_retail_entry_engine()`` / ``build_entry_line_geometry()``."""
    cam3 = store.cam3
    entry = cam3.entry
    recovery = cam3.recovery
    detection = cam3.detection
    byte_track = cam3.byte_track

    polygon = [(float(x), float(y)) for x, y in entry.line_polygon]

    return {
        "ENTRY_LINE_POLYGON": polygon,
        "STORE_REF": tuple(entry.store_ref),
        "ENTRY_LINE_STYLE": _line_style_to_notbk(entry.line_style),
        "ENTRY_PLANE_Y_NORM": entry.entry_plane_y_norm,
        "INVERT_RETAIL_SEMANTICS": entry.invert_retail_semantics,
        "PROCESS_EVERY_N_FRAMES": detection.process_every_n_frames,
        "CONFIDENCE_THRESHOLD": detection.confidence_threshold,
        "IOU_THRESHOLD": detection.iou_threshold,
        "YOLO_IMGSZ": detection.yolo_imgsz or 960,
        "YOLO_MAX_DET": detection.yolo_max_det or 50,
        "ENTRY_STABILITY_FRAMES": recovery.entry_stability_frames,
        "EXIT_STABILITY_FRAMES": recovery.exit_stability_frames,
        "ENABLE_THRESHOLD_RECOVERY": recovery.enable_threshold_recovery,
        "NEAR_THRESHOLD_Y_TOLERANCE": recovery.near_threshold_y_tolerance,
        "THRESHOLD_OBSERVATION_FRAMES": recovery.threshold_observation_frames,
        "THRESHOLD_MOTION_EPS": recovery.threshold_motion_eps,
        "ENABLE_TRACK_LOSS_FLUSH": recovery.enable_track_loss_flush,
        "TRACK_LOSS_GRACE_FRAMES": recovery.track_loss_grace_frames,
        "TRACK_LOSS_MOTION_EPS": recovery.track_loss_motion_eps,
        "TRACK_LOSS_FLUSH_REQUIRE_STABLE_PENDING": (
            recovery.track_loss_flush_require_stable_pending
        ),
        "ENABLE_LATE_ENTRY_RECOVERY": recovery.enable_late_entry_recovery,
        "LATE_ENTRY_Y_BAND_BELOW": recovery.late_entry_y_band_below,
        "LATE_ENTRY_REQUIRE_NEAR_THRESHOLD": recovery.late_entry_require_near_threshold,
        "BYTE_TRACK_ACTIVATION_THRESHOLD": byte_track.activation_threshold,
        "BYTE_TRACK_MIN_CONSECUTIVE_FRAMES": byte_track.min_consecutive_frames,
        "BYTE_TRACK_MAX_TIME_LOST": byte_track.max_time_lost,
    }


def clip_start_strings(store: StoreConfig) -> dict[str, str]:
    """``CAM3`` and ``CAM3:{clip_id}`` → clip start strings from ``videos.json``."""
    return store.videos.clip_start_strings()


@dataclass(frozen=True)
class Cam3ClipDescriptor:
    """One CAM3 clip from ``videos.json`` ``cam3_clips`` (readable; processing optional)."""

    clip_id: str
    video_path: Path
    clip_start: str
    output_events_path: Path
    process_every_n_frames: int | None = None


def list_cam3_clips(store: StoreConfig) -> tuple[Cam3ClipDescriptor, ...]:
    """Enumerate configured multi-clip entries (e.g. store_2 entry1 / entry2)."""
    out: list[Cam3ClipDescriptor] = []
    for clip in store.videos.cam3_clips:
        basename = clip.output_events_basename or f"cam3_{clip.clip_id}_events.jsonl"
        out.append(
            Cam3ClipDescriptor(
                clip_id=clip.clip_id,
                video_path=store.videos.cam3_clip_video_path(clip.clip_id),
                clip_start=clip.clip_start,
                output_events_path=store.pipeline_output_dir / basename,
                process_every_n_frames=clip.process_every_n_frames,
            )
        )
    return tuple(out)


@dataclass(frozen=True)
class Cam3ProcessorConfig:
    """Fully store-driven CAM3 processor settings (inactive until Phase C wiring)."""

    store_key: str
    store_id: str
    camera_key: str
    competition_camera_id: str
    layout: dict[str, Any]
    process_every_n_frames: int
    progress_log_every_n_frames: int
    confidence_threshold: float
    iou_threshold: float
    yolo_imgsz: int
    yolo_max_det: int
    byte_track_activation_threshold: float
    byte_track_min_consecutive_frames: int
    byte_track_max_time_lost: int
    byte_track_disable_env: str
    entry_plane_y_norm: float
    reentry_time_window_seconds: float
    reentry_location_max_norm_dist: float
    reentry_entry_y_tolerance: float
    reid: ReidSettings
    default_event_confidence: float
    clip_start_by_key: dict[str, str]
    cam3_clips: tuple[Cam3ClipDescriptor, ...]
    has_multi_clip: bool
    primary_video_path: Path | None
    default_events_output_path: Path
    yolo_model_path: Path
    pipeline_output_dir: Path


def build_cam3_processor_config(
    store: StoreConfig | None = None,
) -> Cam3ProcessorConfig:
    """Hydrate processor config from active store (``PURPPLE_STORE`` when ``store`` omitted)."""
    resolved = store if store is not None else get_store_config()
    cam3 = resolved.cam3
    detection = cam3.detection
    byte_track = cam3.byte_track
    reentry = cam3.reentry
    clips = list_cam3_clips(resolved)
    reid = reid_settings_from_config(cam3.reid)

    return Cam3ProcessorConfig(
        store_key=resolved.store_key,
        store_id=resolved.store_id,
        camera_key=cam3.camera_key,
        competition_camera_id=cam3.competition_camera_id,
        layout=build_cam3_layout(resolved),
        process_every_n_frames=detection.process_every_n_frames,
        progress_log_every_n_frames=detection.progress_log_every_n_frames,
        confidence_threshold=detection.confidence_threshold,
        iou_threshold=detection.iou_threshold,
        yolo_imgsz=detection.yolo_imgsz or 960,
        yolo_max_det=detection.yolo_max_det or 50,
        byte_track_activation_threshold=byte_track.activation_threshold,
        byte_track_min_consecutive_frames=byte_track.min_consecutive_frames,
        byte_track_max_time_lost=byte_track.max_time_lost,
        byte_track_disable_env=byte_track.disable_bytetrack_env,
        entry_plane_y_norm=cam3.entry.entry_plane_y_norm,
        reentry_time_window_seconds=reentry.time_window_seconds,
        reentry_location_max_norm_dist=reentry.location_max_norm_dist,
        reentry_entry_y_tolerance=reentry.entry_y_tolerance,
        reid=reid,
        default_event_confidence=resolved.default_event_confidence,
        clip_start_by_key=clip_start_strings(resolved),
        cam3_clips=clips,
        has_multi_clip=len(clips) > 0,
        primary_video_path=resolved.videos.video_path(CAMERA_KEY),
        default_events_output_path=resolved.pipeline_output_dir / "cam3_events.jsonl",
        yolo_model_path=resolved.yolo_model_path,
        pipeline_output_dir=resolved.pipeline_output_dir,
    )
