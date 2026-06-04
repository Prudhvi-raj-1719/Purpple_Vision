"""
CAM3 retail entry/exit: YOLO11m + ByteTrack + half-plane RetailEntryEngine.

Store-driven via ``get_store_config()`` (``stores/*/cam3.json`` + ``videos.json``).
Production-capable via ``process_cam3_video()``; ``demo_runner`` / ``run_pipeline_demo``
use this module (Phase C). ``entry_exit`` remains for rollback.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO

from pipeline.cam3.reentry_session import parse_utc_from_iso
from pipeline.cam3.time_utils import video_offset_to_utc_iso
from pipeline.cam3_emitter import Cam3EventEmitter, build_cam3_event_emitter
from pipeline.cam3_layout import (
    CAMERA_KEY,
    ENTRY_POLYGON_COLOR,
    PERSON_CLASS_ID,
    Cam3ProcessorConfig,
    build_cam3_processor_config,
)
from pipeline.config import (
    emitter_clip_start_by_camera,
    parse_clip_start,
    refresh_store_config,
)
from pipeline.emit import PipelineEmitter
from pipeline.entry_retail import (
    STATE_INSIDE,
    STATE_OUTSIDE,
    build_entry_line_geometry,
    build_retail_entry_engine,
    format_video_timestamp,
)
from pipeline.reid.osnet_reid import OsnetEmbedder
from pipeline.reid.reid_manager import ReIDManager
from pipeline.reid.settings import activate_reid_settings
from pipeline.store_config import StoreConfig, resolve_store_config

logger = logging.getLogger(__name__)


@dataclass
class Cam3Stats:
    """Entry/exit counts (same shape as ``entry_exit.EntryExitStats``)."""

    entry_count: int = 0
    exit_count: int = 0
    video_writer: Any | None = None


def denormalize_polygon(
    points: List[Tuple[float, float]],
    width: int,
    height: int,
) -> np.ndarray:
    return np.array(
        [(int(x * width), int(y * height)) for x, y in points],
        dtype=np.int32,
    )


def load_cam3_processor_config(
    store: StoreConfig | None = None,
) -> Cam3ProcessorConfig:
    """Load CAM3 settings from active store (``PURPPLE_STORE`` when ``store`` is None)."""
    return build_cam3_processor_config(store)


def create_byte_tracker(config: Cam3ProcessorConfig) -> sv.ByteTrack | None:
    if os.getenv(config.byte_track_disable_env, "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return None
    tracker = sv.ByteTrack()
    if hasattr(tracker, "track_activation_threshold"):
        tracker.track_activation_threshold = config.byte_track_activation_threshold
    if hasattr(tracker, "minimum_consecutive_frames"):
        tracker.minimum_consecutive_frames = config.byte_track_min_consecutive_frames
    if hasattr(tracker, "max_time_lost"):
        tracker.max_time_lost = config.byte_track_max_time_lost
    if hasattr(tracker, "det_thresh"):
        tracker.det_thresh = config.confidence_threshold
    return tracker


def detect_persons(
    frame_bgr: np.ndarray,
    yolo_model: YOLO,
    config: Cam3ProcessorConfig,
) -> sv.Detections:
    results = yolo_model.predict(
        source=frame_bgr,
        conf=config.confidence_threshold,
        iou=config.iou_threshold,
        imgsz=config.yolo_imgsz,
        max_det=config.yolo_max_det,
        classes=[PERSON_CLASS_ID],
        verbose=False,
    )[0]
    return sv.Detections.from_ultralytics(results)


def build_reid_manager(
    config: Cam3ProcessorConfig,
    entry_geometry: Any,
) -> ReIDManager | None:
    activate_reid_settings(config.reid)
    if not config.reid.enabled:
        return None
    embedder = OsnetEmbedder(device=config.reid.device)
    return ReIDManager(
        embedder=embedder,
        entry_geometry=entry_geometry,
        cosine_threshold=config.reid.cosine_threshold,
        exit_cache_seconds=config.reid.exit_cache_seconds,
        min_dwell_after_exit_seconds=config.reid.min_dwell_after_exit_seconds,
        min_crop_area=config.reid.min_crop_area,
        embed_history=config.reid.track_embed_history,
        session_match_enabled=config.reid.session_match_enabled,
        session_match_threshold=config.reid.session_match_threshold,
        session_margin_threshold=config.reid.session_margin_threshold,
        area_ratio_min=config.reid.area_ratio_min,
        area_ratio_max=config.reid.area_ratio_max,
        session_max_age_seconds=config.reid.session_max_age_seconds,
        fragment_match_threshold=config.reid.fragment_match_threshold,
        fragment_margin_threshold=config.reid.fragment_margin_threshold,
        near_doorway_y_tolerance=config.reid.near_doorway_y_tolerance,
    )


def match_utc_for_frame(
    config: Cam3ProcessorConfig,
    frame_index: int,
    fps: float,
    *,
    clip_id: str | None = None,
) -> Any:
    offset = format_video_timestamp(frame_index, fps)
    utc_iso = video_offset_to_utc_iso(
        config.camera_key,
        offset,
        clip_id=clip_id,
        clip_start_by_key=config.clip_start_by_key,
    )
    return parse_utc_from_iso(utc_iso)


def draw_entry_polygon(
    frame_bgr: np.ndarray,
    polygon: np.ndarray,
    label: str = "ENTRY_LINE",
) -> np.ndarray:
    annotated = frame_bgr.copy()
    pts = polygon.reshape((-1, 1, 2)).astype(np.int32)
    cv2.polylines(
        annotated,
        [pts],
        isClosed=True,
        color=ENTRY_POLYGON_COLOR,
        thickness=2,
    )
    for vertex in polygon:
        cv2.circle(
            annotated,
            (int(vertex[0]), int(vertex[1])),
            5,
            ENTRY_POLYGON_COLOR,
            -1,
            cv2.LINE_AA,
        )
    centroid = polygon.mean(axis=0).astype(int)
    cv2.putText(
        annotated,
        label,
        (int(centroid[0]), int(centroid[1])),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        ENTRY_POLYGON_COLOR,
        2,
        cv2.LINE_AA,
    )
    return annotated


def draw_stats_overlay(
    frame_bgr: np.ndarray,
    entry_count: int,
    exit_count: int,
    active_tracks: int,
    frame_idx: int,
) -> np.ndarray:
    annotated = frame_bgr.copy()
    lines = [
        f"Entry Count: {entry_count}",
        f"Exit Count: {exit_count}",
        f"Active Tracks: {active_tracks}",
        f"Frame: {frame_idx}",
    ]
    x, y0, line_height = 20, 30, 28
    panel_h = line_height * len(lines) + 16
    cv2.rectangle(annotated, (10, 10), (320, 10 + panel_h), (0, 0, 0), -1)
    for i, text in enumerate(lines):
        cv2.putText(
            annotated,
            text,
            (x, y0 + i * line_height),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
    return annotated


def annotate_detections(
    frame_bgr: np.ndarray,
    detections: sv.Detections,
    track_states: Dict[int, Tuple[str, Tuple[int, int]]],
) -> np.ndarray:
    annotated = frame_bgr.copy()
    box_annotator = sv.BoxAnnotator(thickness=2)
    label_annotator = sv.LabelAnnotator(text_scale=0.5, text_thickness=1)

    labels: List[str] = []
    if detections.tracker_id is not None:
        for track_id in detections.tracker_id:
            tid = int(track_id)
            state, _ = track_states.get(tid, (STATE_OUTSIDE, (0, 0)))
            labels.append(f"ID {tid} | {state}")
    else:
        labels = ["ID ?"] * len(detections)

    annotated = box_annotator.annotate(scene=annotated, detections=detections)
    annotated = label_annotator.annotate(scene=annotated, detections=detections, labels=labels)

    if detections.tracker_id is not None:
        for track_id in detections.tracker_id:
            tid = int(track_id)
            _, center = track_states.get(tid, (STATE_OUTSIDE, (0, 0)))
            cv2.circle(annotated, center, 5, (0, 255, 255), -1, cv2.LINE_AA)

    return annotated


def process_frame_updates(
    engine: Any,
    event_emitter: Cam3EventEmitter,
    detections: sv.Detections,
    original_frame: int,
    camera_key: str,
    reid_manager: Any | None = None,
    match_utc: Any | None = None,
) -> Dict[int, Tuple[str, Tuple[int, int]]]:
    track_states: Dict[int, Tuple[str, Tuple[int, int]]] = {}
    active_ids: set[int] = set()

    if detections.tracker_id is not None and len(detections) > 0:
        for track_id, xyxy in zip(detections.tracker_id, detections.xyxy):
            tid = int(track_id)
            active_ids.add(tid)
            x1, y1, x2, y2 = xyxy
            center = (int((x1 + x2) / 2), int((y1 + y2) / 2))
            if reid_manager is not None:
                reid_manager.apply_pending_retail_restore(
                    engine, tid, center, original_frame
                )
            result = engine.update(tid, center, original_frame=original_frame)
            track_states[tid] = (result.store_state, center)
            if result.init_debug is not None:
                event_emitter.log_init_terminal(result.init_debug.to_dict())
            if result.transition is not None:
                event_emitter.emit_transition(
                    result.transition.to_event_row(camera_key),
                    center=center,
                    bbox=[float(x1), float(y1), float(x2), float(y2)],
                    adjust_engine=engine,
                )
            if reid_manager is not None:
                reid_manager.sync_retail_snapshot_from_engine(
                    engine,
                    tid,
                    match_utc=match_utc,
                    bbox=[float(x1), float(y1), float(x2), float(y2)],
                )

    if not engine.enable_track_loss_flush:
        return track_states

    for transition in engine.flush_removed_tracks(active_ids, original_frame):
        centroid = transition.debug.get("centroid")
        center = (
            (int(centroid[0]), int(centroid[1]))
            if isinstance(centroid, (list, tuple)) and len(centroid) >= 2
            else (0, 0)
        )
        event_emitter.emit_transition(
            transition.to_event_row(camera_key),
            center=center,
            bbox=transition.debug.get("bbox"),
            adjust_engine=engine,
        )

    return track_states


def print_converted_coordinates(
    entry_polygon: np.ndarray,
    video_width: int,
    video_height: int,
) -> None:
    coords = [(int(x), int(y)) for x, y in entry_polygon]
    print(f"\nConverted ENTRY_LINE_POLYGON ({video_width} x {video_height}):")
    print(f"  ENTRY_LINE: {coords}")


def _env_int(name: str, default: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _resolve_start_frame(
    *,
    cli_start_frame: int | None = None,
    env_name: str = "CAM3_START_FRAME",
) -> int:
    if cli_start_frame is not None:
        return max(0, cli_start_frame)
    return _env_int(env_name)


def _seek_to_frame(
    capture: cv2.VideoCapture,
    frame_index: int,
    fps: float,
) -> int:
    """Seek to frame_index; return the frame index used for original_frame."""
    if frame_index <= 0:
        return 0

    ms = (frame_index / max(fps, 1e-6)) * 1000.0
    capture.set(cv2.CAP_PROP_POS_MSEC, ms)
    actual = int(capture.get(cv2.CAP_PROP_POS_FRAMES))
    if actual < frame_index - 2:
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        actual = int(capture.get(cv2.CAP_PROP_POS_FRAMES))

    if actual >= frame_index - 2:
        return frame_index

    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
    for grabbed in range(frame_index):
        if not capture.grab():
            return grabbed
    return frame_index


def print_startup_config(
    config: Cam3ProcessorConfig,
    *,
    video_path: Path,
    output_path: Path,
    start_frame: int = 0,
    fps: float = 30.0,
) -> None:
    style = config.layout.get("ENTRY_LINE_STYLE", "")
    print(f"Store: {config.store_key} ({config.store_id})")
    print(f"Entry line style: {style}")
    print(f"invert_retail_semantics: {config.layout.get('INVERT_RETAIL_SEMANTICS')}")
    print(f"Multi-clip configured: {config.has_multi_clip}")
    print(f"Video: {video_path.name}")
    print(f"Output: {output_path.name}")
    print(f"Video path: {video_path.resolve()}")
    print(f"Output path: {output_path.resolve()}")
    print(f"Process every N frames: {config.process_every_n_frames}")
    if start_frame > 0:
        print(
            f"Start frame: {start_frame} (~{start_frame / max(fps, 1e-6):.1f}s, "
            f"set CAM3_START_FRAME=0 to run from beginning)"
        )
    if os.getenv("CAM3_CROSSING_DEBUG") == "1":
        print("CAM3_CROSSING_DEBUG: enabled")


def print_cam3_clip_inventory(config: Cam3ProcessorConfig) -> None:
    """Log configured multi-clip entries."""
    print(f"Store {config.store_key}: CAM3 multi-clip mode ({len(config.cam3_clips)} clips)")
    for clip in config.cam3_clips:
        print(
            f"  {clip.clip_id}: video={clip.video_path.name} "
            f"clip_start={clip.clip_start} "
            f"output={clip.output_events_path.name}"
        )


def _hydrate_emitter_clip_starts(
    emitter: PipelineEmitter,
    store: StoreConfig,
    *,
    camera_key: str,
) -> None:
    """Register ``CAM3`` and ``CAM3:{clip_id}`` anchors on the shared ``PipelineEmitter``."""
    for clip in store.videos.cam3_clips:
        clip_key = f"{camera_key}:{clip.clip_id}"
        emitter.clip_start_by_camera[clip_key] = parse_clip_start(
            camera_key,
            store=store,
            clip_id=clip.clip_id,
        ).replace(tzinfo=timezone.utc)
    try:
        emitter.clip_start_by_camera[camera_key] = parse_clip_start(
            camera_key,
            store=store,
        ).replace(tzinfo=timezone.utc)
    except KeyError:
        pass


def process_video(
    video_path: Path,
    yolo_model: YOLO,
    config: Cam3ProcessorConfig,
    *,
    window_name: str,
    show_window: bool,
    clip_id: str | None = None,
    start_frame: int | None = None,
    pipeline_emitter: PipelineEmitter | None = None,
    events_output_path: Path | None = None,
    annotated_video_path: Path | None = None,
    video_writer: Any | None = None,
) -> Tuple[int, int, Any | None]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise FileNotFoundError(f"Unable to open video: {video_path}")

    video_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS)) or 30.0
    requested_start = _resolve_start_frame(cli_start_frame=start_frame)
    start_frame = _seek_to_frame(capture, requested_start, fps)
    if requested_start > 0 and start_frame != requested_start:
        print(
            f"Warning: requested start frame {requested_start}, "
            f"decoder ready at {start_frame}"
        )

    emit_target = (
        pipeline_emitter.output_path
        if pipeline_emitter is not None
        else (events_output_path or config.default_events_output_path)
    )
    print_startup_config(
        config,
        video_path=video_path,
        output_path=emit_target,
        start_frame=start_frame,
        fps=fps,
    )
    print(f"Video resolution: {video_width} x {video_height}")

    entry_polygon = denormalize_polygon(
        config.layout["ENTRY_LINE_POLYGON"],
        video_width,
        video_height,
    )
    print_converted_coordinates(entry_polygon, video_width, video_height)

    engine = build_retail_entry_engine(
        config.layout,
        video_width,
        video_height,
        timestamp_fn=lambda frame_idx, f=fps: format_video_timestamp(frame_idx, f),
    )
    entry_geometry = build_entry_line_geometry(
        config.layout,
        video_width,
        video_height,
    )
    reid_manager = build_reid_manager(config, entry_geometry)
    if reid_manager is not None:
        print(
            f"CAM3 OSNet Re-ID: enabled (threshold={reid_manager.cosine_threshold}, "
            f"exit_cache={reid_manager.exit_cache_seconds}s, "
            f"session_match={reid_manager.session_match_enabled}, "
            f"session_threshold={reid_manager.session_match_threshold}, "
            f"fragment_threshold={reid_manager.fragment_match_threshold}, "
            f"heuristic_fallback={config.reid.heuristic_fallback})"
        )
    else:
        print("CAM3 OSNet Re-ID: disabled (cam3.json reid.enabled=false)")

    direct_jsonl = events_output_path if pipeline_emitter is None else None
    event_emitter = build_cam3_event_emitter(
        config,
        output_path=direct_jsonl,
        clip_id=clip_id,
        video_width=video_width,
        video_height=video_height,
        reid_manager=reid_manager,
        pipeline_emitter=pipeline_emitter,
    )
    tracker = create_byte_tracker(config)

    if show_window:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    from pipeline.shelf_preview import open_mp4_writer

    writer = video_writer
    if annotated_video_path is not None and writer is None:
        writer = open_mp4_writer(annotated_video_path, video_width, video_height, fps)

    last_annotated: np.ndarray | None = None
    original_frame = start_frame
    try:
        while True:
            success, frame = capture.read()
            if not success:
                break

            run_inference = original_frame % config.process_every_n_frames == 0
            if run_inference:
                detections = detect_persons(frame, yolo_model, config)
                if tracker is not None:
                    detections = tracker.update_with_detections(detections)
                match_utc = None
                if reid_manager is not None:
                    match_utc = match_utc_for_frame(
                        config,
                        original_frame,
                        fps,
                        clip_id=clip_id,
                    )
                    reid_manager.update_tracks(frame, detections, match_utc=match_utc)
                track_states = process_frame_updates(
                    engine,
                    event_emitter,
                    detections,
                    original_frame,
                    config.camera_key,
                    reid_manager,
                    match_utc=match_utc,
                )
                active_tracks = len(detections) if detections.tracker_id is not None else 0
                last_annotated = draw_entry_polygon(frame, entry_polygon)
                last_annotated = annotate_detections(
                    last_annotated, detections, track_states
                )
                last_annotated = draw_stats_overlay(
                    last_annotated,
                    engine.entry_count,
                    engine.exit_count,
                    active_tracks,
                    original_frame,
                )
                del frame, detections, track_states
            else:
                last_annotated = draw_entry_polygon(frame, entry_polygon)
                del frame

            if writer is not None and last_annotated is not None:
                writer.write(last_annotated)

            if show_window and last_annotated is not None:
                cv2.imshow(window_name, last_annotated)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break

            original_frame += 1

        if engine.enable_track_loss_flush:
            last_frame = max(0, original_frame - 1)
            for transition in engine.flush_removed_tracks(set(), last_frame):
                centroid = transition.debug.get("centroid")
                center = (
                    (int(centroid[0]), int(centroid[1]))
                    if isinstance(centroid, (list, tuple)) and len(centroid) >= 2
                    else (0, 0)
                )
                event_emitter.emit_transition(
                    transition.to_event_row(config.camera_key),
                    center=center,
                    adjust_engine=engine,
                )
    finally:
        capture.release()
        if show_window:
            cv2.destroyAllWindows()

    print(f"\nFinal Entry Count: {engine.entry_count}")
    print(f"Final Exit Count: {engine.exit_count}")
    rs = engine.recovery_stats
    print(
        f"Recovery stats: recovered_entries={rs.recovered_entries} "
        f"recovered_exits={rs.recovered_exits} "
        f"born_inside_tracks={rs.born_inside_tracks} "
        f"born_near_threshold_tracks={rs.born_near_threshold_tracks}"
    )
    event_emitter.print_summary_cam3()
    return engine.entry_count, engine.exit_count, writer


def _process_cam3_video_once(
    path: Path,
    *,
    config: Cam3ProcessorConfig,
    yolo_model: YOLO,
    emitter: PipelineEmitter | None = None,
    events_output_path: Path | None = None,
    show_window: bool = False,
    clip_id: str | None = None,
    start_frame: int | None = None,
    annotated_video_path: Path | None = None,
    video_writer: Any | None = None,
) -> Cam3Stats:
    """Run retail CAM3 engine on one video file."""
    if not path.exists():
        raise FileNotFoundError(f"Missing CAM3 video: {path}")

    window = f"CAM3 Entry Exit ({clip_id})" if clip_id else "CAM3 Entry Exit"
    entry_count, exit_count, writer = process_video(
        path,
        yolo_model,
        config,
        window_name=window,
        show_window=show_window,
        clip_id=clip_id,
        start_frame=start_frame,
        pipeline_emitter=emitter,
        events_output_path=events_output_path,
        annotated_video_path=annotated_video_path,
        video_writer=video_writer,
    )
    return Cam3Stats(
        entry_count=entry_count,
        exit_count=exit_count,
        video_writer=writer,
    )


def process_cam3_video(
    video_path: Path | None = None,
    *,
    emitter: PipelineEmitter | None = None,
    show_window: bool = False,
    store: StoreConfig | None = None,
    camera_id: str | None = None,
    output_path: Path | None = None,
) -> Cam3Stats:
    """
    Run CAM3 entry/exit on configured video(s).

    Matches ``entry_exit.process_cam3_video`` for orchestration (``PipelineEmitter``).
    When ``videos.json`` defines ``cam3_clips`` (store_2), processes entry1/entry2
    sequentially into the same emitter.

    Extra kwargs (vs ``entry_exit``): ``camera_id``, ``output_path`` for standalone JSONL.
    """
    cfg = resolve_store_config(store)
    if not cfg.cam3.enabled:
        raise RuntimeError(f"{cfg.store_key}: CAM3 is disabled in cam3.json")

    config = build_cam3_processor_config(cfg)
    if camera_id is not None:
        config = replace(config, camera_key=camera_id)

    if emitter is not None:
        _hydrate_emitter_clip_starts(emitter, cfg, camera_key=config.camera_key)

    yolo_model = YOLO(str(config.yolo_model_path))
    logger.info("CAM3 YOLO loaded: %s", config.yolo_model_path)

    from pipeline.shelf_preview import shelf_tracking_output_path

    tracking_path = shelf_tracking_output_path(cfg.pipeline_output_dir, CAMERA_KEY)

    if config.has_multi_clip:
        combined = Cam3Stats()
        shared_writer = None
        for clip in config.cam3_clips:
            clip_path = video_path or clip.video_path
            stride = clip.process_every_n_frames or config.process_every_n_frames
            clip_config = replace(config, process_every_n_frames=stride)
            logger.info(
                "CAM3 clip %s: %s (process_every_n_frames=%s)",
                clip.clip_id,
                clip_path,
                stride,
            )
            clip_out = None if emitter is not None else (
                output_path or clip.output_events_path
            )
            clip_stats = _process_cam3_video_once(
                clip_path,
                config=clip_config,
                yolo_model=yolo_model,
                emitter=emitter,
                events_output_path=clip_out,
                show_window=show_window,
                clip_id=clip.clip_id,
                start_frame=None,
                annotated_video_path=tracking_path,
                video_writer=shared_writer,
            )
            combined.entry_count += clip_stats.entry_count
            combined.exit_count += clip_stats.exit_count
            shared_writer = clip_stats.video_writer
        if shared_writer is not None:
            shared_writer.release()
            logger.info("Wrote annotated tracking video: %s", tracking_path)
        return combined

    path = video_path or config.primary_video_path
    if path is None:
        raise FileNotFoundError(f"{cfg.store_key}: no CAM3 video configured")

    standalone_out = None if emitter is not None else (
        output_path or config.default_events_output_path
    )
    stats = _process_cam3_video_once(
        path,
        config=config,
        yolo_model=yolo_model,
        emitter=emitter,
        events_output_path=standalone_out,
        show_window=show_window,
        start_frame=None,
        annotated_video_path=tracking_path,
    )
    if stats.video_writer is not None:
        stats.video_writer.release()
        logger.info("Wrote annotated tracking video: %s", tracking_path)
    return stats


def run_cli(
    output_path: Path | None = None,
    *,
    show_window: bool = False,
    store: StoreConfig | None = None,
) -> None:
    """CLI: process CAM3 and write Purpple-schema JSONL via ``PipelineEmitter``."""
    cfg = resolve_store_config(store)
    refresh_store_config(cfg.store_key)
    out = output_path or (cfg.pipeline_output_dir / "cam3_events.jsonl")
    clip_starts = emitter_clip_start_by_camera(CAMERA_KEY, store=cfg)
    with PipelineEmitter(
        output_path=out,
        store_id=cfg.store_id,
        clip_start_by_camera=clip_starts,
    ) as emitter:
        stats = process_cam3_video(emitter=emitter, show_window=show_window, store=cfg)
        logger.info(
            "CAM3 complete: entries=%s exits=%s; wrote %s events "
            "(%s adaptation errors)",
            stats.entry_count,
            stats.exit_count,
            emitter.stats.events_written,
            emitter.stats.adaptation_errors,
        )


def run_cli_legacy() -> None:
    """Backward alias for ``run_cli()``."""
    run_cli()


def _parse_cli_args() -> Tuple[int | None, str | None]:
    import argparse

    parser = argparse.ArgumentParser(description="CAM3 entry/exit event generator")
    parser.add_argument(
        "--start-frame",
        type=int,
        default=None,
        help="First video frame to process (overrides CAM3_START_FRAME env)",
    )
    parser.add_argument(
        "--clip",
        choices=["entry1", "entry2"],
        default=None,
        help="Footage2 clip only (overrides CAM3_FOOTAGE2_CLIP env)",
    )
    args = parser.parse_args()
    return args.start_frame, args.clip


def main() -> None:
    log_level = (
        logging.DEBUG
        if os.getenv("CAM3_DEBUG", "").lower() in ("1", "true", "yes")
        else logging.INFO
    )
    logging.basicConfig(level=log_level, format="%(message)s")
    cli_start_frame, cli_clip = _parse_cli_args()
    cfg = resolve_store_config()
    if not cfg.cam3.enabled:
        raise RuntimeError(f"{cfg.store_key}: CAM3 is disabled in cam3.json")

    config = load_cam3_processor_config(cfg)
    if cli_clip and config.has_multi_clip:
        clips = [c for c in config.cam3_clips if c.clip_id.lower() == cli_clip.lower()]
        if not clips:
            known = ", ".join(c.clip_id for c in config.cam3_clips)
            raise ValueError(f"Unknown CAM3 clip {cli_clip!r}; choose: {known}")
        yolo_model = YOLO(str(config.yolo_model_path))
        for clip in clips:
            _process_cam3_video_once(
                clip.video_path,
                config=config,
                yolo_model=yolo_model,
                events_output_path=clip.output_events_path,
                show_window=os.getenv("CAM3_EVENTS_HEADLESS") != "1",
                clip_id=clip.clip_id,
                start_frame=cli_start_frame,
            )
        return

    if config.has_multi_clip:
        out = config.pipeline_output_dir / "cam3_events.jsonl"
        with PipelineEmitter(
            output_path=out,
            store_id=config.store_id,
            clip_start_by_camera={
                f"{CAMERA_KEY}:{clip.clip_id}": parse_clip_start(
                    CAMERA_KEY, store=cfg, clip_id=clip.clip_id
                )
                for clip in cfg.videos.cam3_clips
            },
        ) as emitter:
            show_window = os.getenv("CAM3_EVENTS_HEADLESS") != "1"
            if show_window:
                print("CAM3 preview window: enabled (press Q or Esc to stop current clip)")
            stats = process_cam3_video(
                emitter=emitter, show_window=show_window, store=cfg
            )
            print(
                f"CAM3 JSONL: {emitter.output_path} "
                f"({emitter.stats.events_written} events, "
                f"{emitter.stats.adaptation_errors} adaptation errors)"
            )
            print(f"Final Entry Count: {stats.entry_count}, Exit Count: {stats.exit_count}")
        return

    video_path = config.primary_video_path
    if video_path is None or not video_path.exists():
        raise FileNotFoundError(f"Missing CAM3 video for {config.store_key}")

    yolo_model = YOLO(str(config.yolo_model_path))
    process_video(
        video_path,
        yolo_model,
        config,
        window_name="CAM3 Entry Exit",
        show_window=os.getenv("CAM3_EVENTS_HEADLESS") != "1",
        start_frame=cli_start_frame,
        events_output_path=config.default_events_output_path,
    )[0:2]


if __name__ == "__main__":
    main()
