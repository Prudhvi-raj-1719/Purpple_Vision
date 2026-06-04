"""
Load per-store camera geometry and pipeline tuning from ``stores/{store_key}/``.

Set ``PURPPLE_STORE=store_1`` or ``store_2`` before import (or pass ``StoreConfig``
into processor functions) to select the active store.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
STORES_ROOT = REPO_ROOT / "stores"
SUPPORTED_STORE_KEYS = frozenset({"store_1", "store_2"})
CAMERA_CONFIG_FILES = ("cam1.json", "cam2.json", "cam3.json", "cam5.json")
EXPECTED_SCHEMA_VERSION = 1
ACTIVE_STORE_ENV = "PURPPLE_STORE"
DEFAULT_ACTIVE_STORE_KEY = "store_1"

Point = tuple[float, float]
Polygon = tuple[Point, ...]
ZoneMap = dict[str, Polygon]


def _repo_relative(path: str) -> Path:
    return (REPO_ROOT / path).resolve()


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: root must be a JSON object")
    return data


def _check_schema_version(data: Mapping[str, Any], path: Path) -> None:
    version = data.get("schema_version")
    if version != EXPECTED_SCHEMA_VERSION:
        raise ValueError(
            f"{path}: schema_version must be {EXPECTED_SCHEMA_VERSION}, got {version!r}"
        )


def _parse_polygon(raw: Sequence[Sequence[float]], *, context: str) -> Polygon:
    points: list[Point] = []
    for index, pair in enumerate(raw):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(f"{context}: point {index} must be [x, y]")
        points.append((float(pair[0]), float(pair[1])))
    if len(points) < 3:
        raise ValueError(f"{context}: polygon needs at least 3 points")
    return tuple(points)


def _parse_zones(
    raw: Mapping[str, Any] | None,
    *,
    context: str,
) -> ZoneMap:
    if not raw:
        return {}
    zones: ZoneMap = {}
    for name, coords in raw.items():
        if not isinstance(coords, list):
            raise ValueError(f"{context}.zones[{name!r}]: must be a list of points")
        zones[str(name)] = _parse_polygon(coords, context=f"{context}.zones[{name!r}]")
    return zones


@dataclass(frozen=True)
class OverlapConfig:
    min_overlap_pct: float
    min_zone_stability_frames: int
    lost_track_frames: int


@dataclass(frozen=True)
class DwellConfig:
    min_dwell_seconds: float
    min_zone_dwell_ms: int


@dataclass(frozen=True)
class DetectionConfig:
    confidence_threshold: float
    iou_threshold: float
    process_every_n_frames: int
    progress_log_every_n_frames: int = 100
    yolo_imgsz: int | None = None
    yolo_max_det: int | None = None


@dataclass(frozen=True)
class ShelfCameraConfig:
    """CAM1 / CAM2 zone-engagement settings."""

    camera_key: str
    enabled: bool
    competition_camera_id: str
    coordinate_system: str
    zones: ZoneMap
    zone_id_map: dict[str, str]
    overlap: OverlapConfig
    dwell: DwellConfig
    detection: DetectionConfig
    raw: dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class Cam3EntryConfig:
    line_polygon: Polygon
    store_ref: Point
    line_style: str
    entry_plane_y_norm: float
    invert_retail_semantics: bool


@dataclass(frozen=True)
class ByteTrackConfig:
    activation_threshold: float
    min_consecutive_frames: int
    max_time_lost: int
    disable_bytetrack_env: str


@dataclass(frozen=True)
class Cam3RecoveryConfig:
    entry_stability_frames: int
    exit_stability_frames: int
    enable_threshold_recovery: bool
    near_threshold_y_tolerance: float
    threshold_observation_frames: int
    threshold_motion_eps: float
    enable_track_loss_flush: bool
    track_loss_grace_frames: int
    track_loss_motion_eps: float
    track_loss_flush_require_stable_pending: bool
    enable_late_entry_recovery: bool
    late_entry_y_band_below: float
    late_entry_require_near_threshold: bool


@dataclass(frozen=True)
class ReentryConfig:
    time_window_seconds: float
    location_max_norm_dist: float
    entry_y_tolerance: float


@dataclass(frozen=True)
class ReidConfig:
    enabled: bool
    heuristic_fallback: bool
    debug: bool
    model_name: str
    device: str
    cosine_threshold: float
    exit_cache_seconds: float
    min_dwell_after_exit_seconds: float
    min_crop_area: int
    track_embed_history: int
    session_match_enabled: bool
    session_match_threshold: float
    session_margin_threshold: float
    area_ratio_min: float
    area_ratio_max: float
    session_max_age_seconds: float
    near_doorway_y_tolerance: float
    fragment_match_threshold: float
    fragment_margin_threshold: float
    osnet_market1501_url: str | None = None


@dataclass(frozen=True)
class EntryCameraConfig:
    """CAM3 entry / exit / reentry / reid settings."""

    camera_key: str
    enabled: bool
    competition_camera_id: str
    entry: Cam3EntryConfig
    detection: DetectionConfig
    byte_track: ByteTrackConfig
    recovery: Cam3RecoveryConfig
    reentry: ReentryConfig
    reid: ReidConfig
    raw: dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class StaffCameraConfig:
    """CAM4 detection-only robustness settings."""

    camera_key: str
    enabled: bool
    competition_camera_id: str
    emit_events: bool
    detection: DetectionConfig
    raw: dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class AnnotationCanvas:
    width: int
    height: int


@dataclass(frozen=True)
class BillingCameraConfig:
    """CAM5 queue and payment zone settings."""

    camera_key: str
    enabled: bool
    competition_camera_id: str
    coordinate_system: str
    zones: ZoneMap
    zone_priority: tuple[str, ...]
    zone_id_map: dict[str, str]
    zone_display_labels: dict[str, str]
    annotation_canvas: AnnotationCanvas | None
    overlap: OverlapConfig
    dwell: DwellConfig
    detection: DetectionConfig
    raw: dict[str, Any] = field(repr=False)
    brigade_annotation_fallback: AnnotationCanvas | None = None


@dataclass(frozen=True)
class CameraVideoSpec:
    camera_key: str
    video: str | None
    clip_start: str | None
    enabled: bool = True


@dataclass(frozen=True)
class Cam3ClipSpec:
    clip_id: str
    video: str
    clip_start: str
    output_events_basename: str | None = None
    process_every_n_frames: int | None = None


@dataclass(frozen=True)
class VideosConfig:
    cctv_dir: Path
    cameras: dict[str, CameraVideoSpec]
    cam3_clips: tuple[Cam3ClipSpec, ...]
    raw: dict[str, Any] = field(repr=False)

    def video_path(self, camera_key: str) -> Path | None:
        spec = self.cameras.get(camera_key)
        if spec is None or not spec.enabled or not spec.video:
            return None
        return self.cctv_dir / spec.video

    def clip_start_datetime(self, camera_key: str) -> datetime | None:
        spec = self.cameras.get(camera_key)
        if spec is None or not spec.clip_start:
            return None
        return datetime.strptime(spec.clip_start, "%Y-%m-%d %H:%M:%S")

    def cam3_clip_video_path(self, clip_id: str) -> Path:
        for clip in self.cam3_clips:
            if clip.clip_id == clip_id:
                return self.cctv_dir / clip.video
        known = ", ".join(c.clip_id for c in self.cam3_clips)
        raise KeyError(f"Unknown cam3 clip_id {clip_id!r}; choose: {known}")

    def cam3_clip_start_datetime(self, clip_id: str) -> datetime:
        for clip in self.cam3_clips:
            if clip.clip_id == clip_id:
                return datetime.strptime(clip.clip_start, "%Y-%m-%d %H:%M:%S")
        known = ", ".join(c.clip_id for c in self.cam3_clips)
        raise KeyError(f"Unknown cam3 clip_id {clip_id!r}; choose: {known}")

    def clip_start_strings(self) -> dict[str, str]:
        """Camera key or ``CAM3:{clip_id}`` → clip start string."""
        out: dict[str, str] = {}
        for camera_key, spec in self.cameras.items():
            if spec.clip_start:
                out[camera_key] = spec.clip_start
        for clip in self.cam3_clips:
            out[f"CAM3:{clip.clip_id}"] = clip.clip_start
        return out


@dataclass(frozen=True)
class StoreConfig:
    """Fully loaded store configuration (all JSON files under ``stores/{store_key}/``)."""

    store_key: str
    store_id: str
    display_name: str
    database_path: Path | None
    pos_csv_path: Path
    pos_store_code: str | None
    pos_sale_date: str
    yolo_model_path: Path
    output_subdir: str
    default_event_confidence: float
    camera_competition_ids: dict[str, str]
    store_dir: Path
    cam1: ShelfCameraConfig
    cam2: ShelfCameraConfig
    cam3: EntryCameraConfig
    cam4: StaffCameraConfig
    cam5: BillingCameraConfig
    videos: VideosConfig
    raw_store: dict[str, Any] = field(repr=False)

    @property
    def pipeline_output_dir(self) -> Path:
        return REPO_ROOT / "data" / "outputs" / "pipeline" / self.output_subdir

    def competition_camera_id(self, camera_key: str) -> str:
        try:
            return self.camera_competition_ids[camera_key]
        except KeyError as exc:
            raise KeyError(f"No competition camera id for {camera_key!r}") from exc

    def is_pipeline_camera_runnable(self, camera_key: str) -> bool:
        """True when the camera is enabled and has footage configured for the demo pipeline."""
        cam_by_key = {
            "CAM1": self.cam1,
            "CAM2": self.cam2,
            "CAM3": self.cam3,
            "CAM4": self.cam4,
            "CAM5": self.cam5,
        }
        cam = cam_by_key.get(camera_key)
        if cam is None or not cam.enabled:
            return False
        if camera_key == "CAM3" and self.videos.cam3_clips:
            return True
        return self.videos.video_path(camera_key) is not None


def _parse_overlap(data: Mapping[str, Any], *, context: str) -> OverlapConfig:
    return OverlapConfig(
        min_overlap_pct=float(data["min_overlap_pct"]),
        min_zone_stability_frames=int(data["min_zone_stability_frames"]),
        lost_track_frames=int(data["lost_track_frames"]),
    )


def _parse_dwell(data: Mapping[str, Any], *, context: str) -> DwellConfig:
    return DwellConfig(
        min_dwell_seconds=float(data["min_dwell_seconds"]),
        min_zone_dwell_ms=int(data["min_zone_dwell_ms"]),
    )


def _parse_detection(data: Mapping[str, Any], *, context: str) -> DetectionConfig:
    return DetectionConfig(
        confidence_threshold=float(data["confidence_threshold"]),
        iou_threshold=float(data["iou_threshold"]),
        process_every_n_frames=int(data["process_every_n_frames"]),
        progress_log_every_n_frames=int(data.get("progress_log_every_n_frames", 100)),
        yolo_imgsz=int(data["yolo_imgsz"]) if "yolo_imgsz" in data else None,
        yolo_max_det=int(data["yolo_max_det"]) if "yolo_max_det" in data else None,
    )


def _parse_shelf_camera(path: Path) -> ShelfCameraConfig:
    data = _load_json(path)
    _check_schema_version(data, path)
    entry_ctx = str(path)
    detection_raw = data.get("detection", {})
    return ShelfCameraConfig(
        camera_key=str(data["camera_key"]),
        enabled=bool(data.get("enabled", True)),
        competition_camera_id=str(data.get("competition_camera_id", "")),
        coordinate_system=str(data.get("coordinate_system", "normalized")),
        zones=_parse_zones(data.get("zones"), context=entry_ctx),
        zone_id_map={str(k): str(v) for k, v in (data.get("zone_id_map") or {}).items()},
        overlap=_parse_overlap(data["overlap"], context=entry_ctx),
        dwell=_parse_dwell(data["dwell"], context=entry_ctx),
        detection=_parse_detection(detection_raw, context=entry_ctx),
        raw=data,
    )


def _parse_entry_camera(path: Path) -> EntryCameraConfig:
    data = _load_json(path)
    _check_schema_version(data, path)
    ctx = str(path)
    entry_raw = data["entry"]
    line_polygon = _parse_polygon(
        entry_raw["line_polygon"],
        context=f"{ctx}.entry.line_polygon",
    )
    store_ref_raw = entry_raw["store_ref"]
    entry = Cam3EntryConfig(
        line_polygon=line_polygon,
        store_ref=(float(store_ref_raw[0]), float(store_ref_raw[1])),
        line_style=str(entry_raw.get("line_style", "polygon")),
        entry_plane_y_norm=float(entry_raw.get("entry_plane_y_norm", 0.54)),
        invert_retail_semantics=bool(entry_raw.get("invert_retail_semantics", False)),
    )
    recovery_raw = data["recovery"]
    reid_raw = data["reid"]
    return EntryCameraConfig(
        camera_key=str(data["camera_key"]),
        enabled=bool(data.get("enabled", True)),
        competition_camera_id=str(data.get("competition_camera_id", "")),
        entry=entry,
        detection=_parse_detection(data["detection"], context=ctx),
        byte_track=ByteTrackConfig(
            activation_threshold=float(data["byte_track"]["activation_threshold"]),
            min_consecutive_frames=int(data["byte_track"]["min_consecutive_frames"]),
            max_time_lost=int(data["byte_track"]["max_time_lost"]),
            disable_bytetrack_env=str(
                data["byte_track"].get("disable_bytetrack_env", "CAM3_DISABLE_BYTETRACK")
            ),
        ),
        recovery=Cam3RecoveryConfig(
            entry_stability_frames=int(recovery_raw["entry_stability_frames"]),
            exit_stability_frames=int(recovery_raw["exit_stability_frames"]),
            enable_threshold_recovery=bool(recovery_raw["enable_threshold_recovery"]),
            near_threshold_y_tolerance=float(recovery_raw["near_threshold_y_tolerance"]),
            threshold_observation_frames=int(recovery_raw["threshold_observation_frames"]),
            threshold_motion_eps=float(recovery_raw["threshold_motion_eps"]),
            enable_track_loss_flush=bool(recovery_raw["enable_track_loss_flush"]),
            track_loss_grace_frames=int(recovery_raw["track_loss_grace_frames"]),
            track_loss_motion_eps=float(recovery_raw["track_loss_motion_eps"]),
            track_loss_flush_require_stable_pending=bool(
                recovery_raw["track_loss_flush_require_stable_pending"]
            ),
            enable_late_entry_recovery=bool(recovery_raw["enable_late_entry_recovery"]),
            late_entry_y_band_below=float(recovery_raw["late_entry_y_band_below"]),
            late_entry_require_near_threshold=bool(
                recovery_raw["late_entry_require_near_threshold"]
            ),
        ),
        reentry=ReentryConfig(
            time_window_seconds=float(data["reentry"]["time_window_seconds"]),
            location_max_norm_dist=float(data["reentry"]["location_max_norm_dist"]),
            entry_y_tolerance=float(data["reentry"]["entry_y_tolerance"]),
        ),
        reid=ReidConfig(
            enabled=bool(reid_raw["enabled"]),
            heuristic_fallback=bool(reid_raw.get("heuristic_fallback", False)),
            debug=bool(reid_raw.get("debug", False)),
            model_name=str(reid_raw.get("model_name", "osnet_x1_0")),
            device=str(reid_raw.get("device", "cpu")),
            cosine_threshold=float(reid_raw.get("cosine_threshold", 0.8)),
            exit_cache_seconds=float(reid_raw.get("exit_cache_seconds", 180)),
            min_dwell_after_exit_seconds=float(
                reid_raw.get("min_dwell_after_exit_seconds", 2.0)
            ),
            min_crop_area=int(reid_raw.get("min_crop_area", 2000)),
            track_embed_history=int(reid_raw.get("track_embed_history", 10)),
            session_match_enabled=bool(reid_raw.get("session_match_enabled", False)),
            session_match_threshold=float(reid_raw.get("session_match_threshold", 0.85)),
            session_margin_threshold=float(reid_raw.get("session_margin_threshold", 0.1)),
            area_ratio_min=float(reid_raw.get("area_ratio_min", 0.5)),
            area_ratio_max=float(reid_raw.get("area_ratio_max", 2.0)),
            session_max_age_seconds=float(reid_raw.get("session_max_age_seconds", 180)),
            near_doorway_y_tolerance=float(reid_raw.get("near_doorway_y_tolerance", 0.1)),
            fragment_match_threshold=float(reid_raw.get("fragment_match_threshold", 0.76)),
            fragment_margin_threshold=float(reid_raw.get("fragment_margin_threshold", 0.05)),
            osnet_market1501_url=reid_raw.get("osnet_market1501_url"),
        ),
        raw=data,
    )


def _default_disabled_staff_camera() -> StaffCameraConfig:
    """Placeholder when a store has no ``cam4.json`` (no staff-camera footage)."""
    return StaffCameraConfig(
        camera_key="CAM4",
        enabled=False,
        competition_camera_id="CAM_STAFF_01",
        emit_events=False,
        detection=DetectionConfig(
            confidence_threshold=0.35,
            iou_threshold=0.5,
            process_every_n_frames=10,
            progress_log_every_n_frames=100,
        ),
        raw={"note": "cam4.json absent; CAM4 disabled for this store"},
    )


def _load_staff_camera(store_dir: Path) -> StaffCameraConfig:
    path = store_dir / "cam4.json"
    if path.is_file():
        return _parse_staff_camera(path)
    return _default_disabled_staff_camera()


def _parse_staff_camera(path: Path) -> StaffCameraConfig:
    data = _load_json(path)
    _check_schema_version(data, path)
    ctx = str(path)
    return StaffCameraConfig(
        camera_key=str(data["camera_key"]),
        enabled=bool(data.get("enabled", True)),
        competition_camera_id=str(data.get("competition_camera_id", "")),
        emit_events=bool(data.get("emit_events", False)),
        detection=_parse_detection(data["detection"], context=ctx),
        raw=data,
    )


def _parse_annotation_canvas(
    raw: Mapping[str, Any] | None,
) -> AnnotationCanvas | None:
    if raw is None:
        return None
    return AnnotationCanvas(width=int(raw["width"]), height=int(raw["height"]))


def _parse_billing_camera(path: Path) -> BillingCameraConfig:
    data = _load_json(path)
    _check_schema_version(data, path)
    ctx = str(path)
    priority = tuple(str(z) for z in data["zone_priority"])
    return BillingCameraConfig(
        camera_key=str(data["camera_key"]),
        enabled=bool(data.get("enabled", True)),
        competition_camera_id=str(data.get("competition_camera_id", "")),
        coordinate_system=str(data.get("coordinate_system", "normalized")),
        zones=_parse_zones(data.get("zones"), context=ctx),
        zone_priority=priority,
        zone_id_map={str(k): str(v) for k, v in (data.get("zone_id_map") or {}).items()},
        zone_display_labels={
            str(k): str(v) for k, v in (data.get("zone_display_labels") or {}).items()
        },
        annotation_canvas=_parse_annotation_canvas(data.get("annotation_canvas")),
        overlap=_parse_overlap(data["overlap"], context=ctx),
        dwell=_parse_dwell(data["dwell"], context=ctx),
        detection=_parse_detection(data["detection"], context=ctx),
        brigade_annotation_fallback=_parse_annotation_canvas(
            data.get("brigade_annotation_fallback")
        ),
        raw=data,
    )


def _parse_videos(path: Path) -> VideosConfig:
    data = _load_json(path)
    _check_schema_version(data, path)
    cctv_dir = _repo_relative(str(data["cctv_dir"]))
    cameras: dict[str, CameraVideoSpec] = {}
    for camera_key, spec in (data.get("cameras") or {}).items():
        if not isinstance(spec, dict):
            raise ValueError(f"{path}: cameras[{camera_key!r}] must be an object")
        cameras[str(camera_key)] = CameraVideoSpec(
            camera_key=str(camera_key),
            video=spec.get("video"),
            clip_start=spec.get("clip_start"),
            enabled=bool(spec.get("enabled", spec.get("video") is not None)),
        )
    clips: list[Cam3ClipSpec] = []
    for item in data.get("cam3_clips") or []:
        stride_raw = item.get("process_every_n_frames")
        clips.append(
            Cam3ClipSpec(
                clip_id=str(item["clip_id"]),
                video=str(item["video"]),
                clip_start=str(item["clip_start"]),
                output_events_basename=item.get("output_events_basename"),
                process_every_n_frames=int(stride_raw) if stride_raw is not None else None,
            )
        )
    return VideosConfig(
        cctv_dir=cctv_dir,
        cameras=cameras,
        cam3_clips=tuple(clips),
        raw=data,
    )


def _parse_store_meta(path: Path, store_key: str) -> dict[str, Any]:
    data = _load_json(path)
    _check_schema_version(data, path)
    if data.get("store_key") != store_key:
        raise ValueError(
            f"{path}: store_key {data.get('store_key')!r} does not match directory {store_key!r}"
        )
    return data


def load_store_config(store_key: str) -> StoreConfig:
    """
    Load ``stores/{store_key}/`` into a :class:`StoreConfig`.

    Args:
        store_key: ``store_1`` (Brigade) or ``store_2`` (Footage2).

    Raises:
        FileNotFoundError: Missing store directory or required JSON file.
        ValueError: Invalid schema or inconsistent store_key.
    """
    if store_key not in SUPPORTED_STORE_KEYS:
        supported = ", ".join(sorted(SUPPORTED_STORE_KEYS))
        raise ValueError(f"Unsupported store_key {store_key!r}; supported: {supported}")

    store_dir = STORES_ROOT / store_key
    if not store_dir.is_dir():
        raise FileNotFoundError(f"Store directory not found: {store_dir}")

    store_path = store_dir / "store.json"
    videos_path = store_dir / "videos.json"
    for name in CAMERA_CONFIG_FILES:
        cam_path = store_dir / name
        if not cam_path.is_file():
            raise FileNotFoundError(f"Missing camera config: {cam_path}")

    store_raw = _parse_store_meta(store_path, store_key)
    database_raw = store_raw.get("database_path")
    return StoreConfig(
        store_key=store_key,
        store_id=str(store_raw["store_id"]),
        display_name=str(store_raw["display_name"]),
        database_path=_repo_relative(database_raw) if database_raw else None,
        pos_csv_path=_repo_relative(str(store_raw["pos_csv_path"])),
        pos_store_code=store_raw.get("pos_store_code"),
        pos_sale_date=str(store_raw["pos_sale_date"]),
        yolo_model_path=_repo_relative(str(store_raw["yolo_model_path"])),
        output_subdir=str(store_raw["output_subdir"]),
        default_event_confidence=float(store_raw["default_event_confidence"]),
        camera_competition_ids={
            str(k): str(v) for k, v in store_raw["camera_competition_ids"].items()
        },
        store_dir=store_dir,
        cam1=_parse_shelf_camera(store_dir / "cam1.json"),
        cam2=_parse_shelf_camera(store_dir / "cam2.json"),
        cam3=_parse_entry_camera(store_dir / "cam3.json"),
        cam4=_load_staff_camera(store_dir),
        cam5=_parse_billing_camera(store_dir / "cam5.json"),
        videos=_parse_videos(videos_path),
        raw_store=store_raw,
    )


def list_store_keys() -> tuple[str, ...]:
    """Return supported store keys (fixed set in Phase 1)."""
    return tuple(sorted(SUPPORTED_STORE_KEYS))


def zones_as_legacy_dict(zones: ZoneMap) -> dict[str, list[tuple[float, float]]]:
    """Convert parsed zones to list-of-tuples dict used by dwell/zones modules."""
    return {name: [tuple(point) for point in polygon] for name, polygon in zones.items()}


def entry_line_as_legacy_list(entry: Cam3EntryConfig) -> list[tuple[float, float]]:
    return [tuple(point) for point in entry.line_polygon]


def get_active_store_key() -> str:
    """Resolve active store from ``PURPPLE_STORE`` (default ``store_1``)."""
    raw = os.getenv(ACTIVE_STORE_ENV, DEFAULT_ACTIVE_STORE_KEY).strip()
    if raw not in SUPPORTED_STORE_KEYS:
        supported = ", ".join(sorted(SUPPORTED_STORE_KEYS))
        raise ValueError(
            f"Invalid {ACTIVE_STORE_ENV}={raw!r}; supported: {supported}"
        )
    return raw


@lru_cache(maxsize=4)
def get_store_config(store_key: str | None = None) -> StoreConfig:
    """
    Cached loader; ``None`` uses :func:`get_active_store_key`.

    Prefer this over :func:`load_store_config` in processors.
    """
    key = store_key if store_key is not None else get_active_store_key()
    return load_store_config(key)


def resolve_store_config(store: StoreConfig | None = None) -> StoreConfig:
    """Use explicit ``store`` or fall back to the active cached config."""
    return store if store is not None else get_store_config()


def build_cam5_zone_polygons(
    cam5: BillingCameraConfig,
    video_width: int,
    video_height: int,
) -> dict[str, Any]:
    """Build pixel polygons for CAM5 (normalized or annotation-canvas pixel coords)."""
    import numpy as np

    if cam5.coordinate_system == "pixel":
        if cam5.annotation_canvas is None:
            raise ValueError("CAM5 pixel zones require annotation_canvas")
        canvas = cam5.annotation_canvas
        sx = video_width / canvas.width
        sy = video_height / canvas.height
        result: dict[str, np.ndarray] = {}
        for name, polygon in cam5.zones.items():
            scaled = np.empty((len(polygon), 2), dtype=np.float64)
            for index, (x, y) in enumerate(polygon):
                scaled[index, 0] = x * sx
                scaled[index, 1] = y * sy
            result[name] = np.round(scaled).astype(np.int32)
        return result

    result = {}
    for name, polygon in zones_as_legacy_dict(cam5.zones).items():
        result[name] = np.array(
            [(int(x * video_width), int(y * video_height)) for x, y in polygon],
            dtype=np.int32,
        )
    return result
