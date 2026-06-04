"""Pipeline paths and tuning — hydrated from ``stores/{PURPPLE_STORE}/`` JSON."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from pipeline.store_config import (
    ACTIVE_STORE_ENV,
    DEFAULT_ACTIVE_STORE_KEY,
    StoreConfig,
    entry_line_as_legacy_list,
    get_active_store_key,
    get_store_config,
    zones_as_legacy_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = Path(os.getenv("PIPELINE_OUTPUT_DIR", DATA_DIR / "outputs"))

# Populated by apply_store_config() at import and via refresh_store_config().
ACTIVE_STORE_KEY: str = DEFAULT_ACTIVE_STORE_KEY
_ACTIVE_STORE: StoreConfig | None = None

CCTV_DIR: Path = DATA_DIR / "cctv" / "Brigade_Bangalore"
MODEL_PATH: Path = REPO_ROOT / "models" / "yolo11m.pt"
DEFAULT_STORE_ID: str = "STORE_BLR_002"

POS_DIR: Path = DATA_DIR / "pos"
BRIGADE_POS_CSV_PATH: Path = POS_DIR / "Brigade_Bangalore_10_April_26.csv"
BRIGADE_POS_STORE_CODE: str | None = "ST1008"
AGGREGATED_POS_DIR: Path = OUTPUT_DIR / "pos"
AGGREGATED_TRANSACTIONS_JSON: Path = AGGREGATED_POS_DIR / "aggregated_transactions.json"
AGGREGATED_TRANSACTIONS_CSV: Path = AGGREGATED_POS_DIR / "aggregated_transactions.csv"
PURPPLE_POS_CSV: Path = AGGREGATED_POS_DIR / "purpple_pos_transactions.csv"
PIPELINE_DEMO_DIR: Path = OUTPUT_DIR / "pipeline" / "pipeline_demo"
PURCHASE_MATCHES_JSON: Path = OUTPUT_DIR / "purchase_matching" / "purchase_matches.json"

CAMERA_CLIP_START: Dict[str, str] = {}
CAMERA_VIDEO_FILES: Dict[str, Path] = {}
CAMERA_PURPPLE_IDS: Dict[str, str] = {}
CAM3_ENTRY_LINE_POLYGON: List[Tuple[float, float]] = []
CAM5_ZONES: Dict[str, List[Tuple[float, float]]] = {}
CAM5_ZONE_PRIORITY: Tuple[str, ...] = ("PaymentArea", "BillingQueue")

PERSON_CLASS_ID = 0
DEFAULT_CONFIDENCE = 0.85
MIN_ZONE_DWELL_MS = 30_000
OUT_OF_ZONE = "OUT_OF_ZONE"
CONFIDENCE_THRESHOLD = 0.35
IOU_THRESHOLD = 0.5
MIN_OVERLAP_PCT = 10
LOST_TRACK_FRAMES = 30
MIN_ZONE_STABILITY_FRAMES = 15
MIN_DWELL_SECONDS = 2.0
PROCESS_EVERY_N_FRAMES = 10
PROGRESS_LOG_EVERY_N_FRAMES = 100

CAM1_ZONES: Dict[str, List[Tuple[float, float]]] = {}
CAM2_ZONES: Dict[str, List[Tuple[float, float]]] = {}


def apply_store_config(cfg: StoreConfig) -> None:
    """Copy store JSON values into module-level constants (backward-compatible shim)."""
    global ACTIVE_STORE_KEY, _ACTIVE_STORE
    global CCTV_DIR, MODEL_PATH, DEFAULT_STORE_ID
    global BRIGADE_POS_CSV_PATH, BRIGADE_POS_STORE_CODE, PIPELINE_DEMO_DIR
    global CAMERA_CLIP_START, CAMERA_VIDEO_FILES, CAMERA_PURPPLE_IDS
    global CAM3_ENTRY_LINE_POLYGON, CAM5_ZONES, CAM5_ZONE_PRIORITY
    global DEFAULT_CONFIDENCE, MIN_ZONE_DWELL_MS
    global CONFIDENCE_THRESHOLD, IOU_THRESHOLD, MIN_OVERLAP_PCT
    global LOST_TRACK_FRAMES, MIN_ZONE_STABILITY_FRAMES, MIN_DWELL_SECONDS
    global PROCESS_EVERY_N_FRAMES, PROGRESS_LOG_EVERY_N_FRAMES
    global CAM1_ZONES, CAM2_ZONES

    ACTIVE_STORE_KEY = cfg.store_key
    _ACTIVE_STORE = cfg

    CCTV_DIR = cfg.videos.cctv_dir
    MODEL_PATH = (
        Path(os.getenv("YOLO_MODEL_PATH", cfg.yolo_model_path))
        if os.getenv("YOLO_MODEL_PATH")
        else cfg.yolo_model_path
    )
    DEFAULT_STORE_ID = os.getenv("STORE_ID", cfg.store_id)

    BRIGADE_POS_CSV_PATH = Path(
        os.getenv("BRIGADE_POS_CSV_PATH", cfg.pos_csv_path)
    )
    BRIGADE_POS_STORE_CODE = cfg.pos_store_code
    PIPELINE_DEMO_DIR = cfg.pipeline_output_dir

    CAMERA_CLIP_START = cfg.videos.clip_start_strings()
    CAMERA_VIDEO_FILES = {}
    for camera_key in ("CAM1", "CAM2", "CAM3", "CAM4", "CAM5"):
        video_path = cfg.videos.video_path(camera_key)
        if video_path is not None:
            CAMERA_VIDEO_FILES[camera_key] = video_path

    CAMERA_PURPPLE_IDS = dict(cfg.camera_competition_ids)
    CAM3_ENTRY_LINE_POLYGON = entry_line_as_legacy_list(cfg.cam3.entry)
    CAM5_ZONES = zones_as_legacy_dict(cfg.cam5.zones)
    CAM5_ZONE_PRIORITY = cfg.cam5.zone_priority

    DEFAULT_CONFIDENCE = cfg.default_event_confidence
    MIN_ZONE_DWELL_MS = cfg.cam1.dwell.min_zone_dwell_ms

    CONFIDENCE_THRESHOLD = cfg.cam1.detection.confidence_threshold
    IOU_THRESHOLD = cfg.cam1.detection.iou_threshold
    MIN_OVERLAP_PCT = cfg.cam1.overlap.min_overlap_pct
    LOST_TRACK_FRAMES = cfg.cam1.overlap.lost_track_frames
    MIN_ZONE_STABILITY_FRAMES = cfg.cam1.overlap.min_zone_stability_frames
    MIN_DWELL_SECONDS = cfg.cam1.dwell.min_dwell_seconds
    PROCESS_EVERY_N_FRAMES = cfg.cam1.detection.process_every_n_frames
    PROGRESS_LOG_EVERY_N_FRAMES = cfg.cam1.detection.progress_log_every_n_frames

    CAM1_ZONES = zones_as_legacy_dict(cfg.cam1.zones)
    CAM2_ZONES = zones_as_legacy_dict(cfg.cam2.zones)


def refresh_store_config(store_key: str | None = None) -> StoreConfig:
    """Reload constants from ``stores/`` (clears config cache when key changes)."""
    key = store_key if store_key is not None else get_active_store_key()
    get_store_config.cache_clear()
    cfg = get_store_config(key)
    apply_store_config(cfg)
    return cfg


def get_active_store() -> StoreConfig:
    """Return the StoreConfig backing current module-level constants."""
    if _ACTIVE_STORE is None:
        return refresh_store_config()
    return _ACTIVE_STORE


def parse_clip_start(
    camera_key: str,
    *,
    store: StoreConfig | None = None,
    clip_id: str | None = None,
) -> datetime:
    """Return naive UTC clip start for a camera (or CAM3 multi-clip id)."""
    cfg = store if store is not None else get_active_store()
    if clip_id is not None:
        return cfg.videos.cam3_clip_start_datetime(clip_id)
    parsed = cfg.videos.clip_start_datetime(camera_key)
    if parsed is None:
        raise KeyError(f"No clip start configured for {camera_key} in {cfg.store_key}")
    return parsed


def _utc_aware_clip_start(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def emitter_clip_start_by_camera(
    camera_key: str,
    *,
    store: StoreConfig | None = None,
) -> dict[str, datetime]:
    """
    Build ``PipelineEmitter.clip_start_by_camera`` for demo/CLI orchestration.

    For store_2-style CAM3, registers ``CAM3:{clip_id}`` anchors from ``cam3_clips``
    and omits a top-level ``CAM3`` key when only per-clip starts exist.
    """
    cfg = store if store is not None else get_active_store()
    if camera_key == "CAM3" and cfg.videos.cam3_clips:
        out: dict[str, datetime] = {}
        try:
            out[camera_key] = _utc_aware_clip_start(
                parse_clip_start(camera_key, store=cfg)
            )
        except KeyError:
            pass
        for clip in cfg.videos.cam3_clips:
            clip_key = f"{camera_key}:{clip.clip_id}"
            out[clip_key] = _utc_aware_clip_start(
                parse_clip_start(camera_key, store=cfg, clip_id=clip.clip_id)
            )
        return out
    return {
        camera_key: _utc_aware_clip_start(parse_clip_start(camera_key, store=cfg))
    }


# Import-time: honour PURPPLE_STORE (default store_1).
apply_store_config(get_store_config(get_active_store_key()))
