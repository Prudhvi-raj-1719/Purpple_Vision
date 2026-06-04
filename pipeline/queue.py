"""Billing queue depth tracking, BILLING_QUEUE_JOIN and ABANDON events."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO

from pipeline.config import MODEL_PATH, PERSON_CLASS_ID, parse_clip_start, refresh_store_config
from pipeline.store_config import (
    StoreConfig,
    build_cam5_zone_polygons,
    resolve_store_config,
)
from pipeline.emit import PipelineEmitter
from pipeline.sink import EventSink
from pipeline.video_time import format_video_offset, video_seconds

logger = logging.getLogger(__name__)

CAMERA_KEY = "CAM5"
OUT_OF_ZONE = "OUT_OF_ZONE"
PAYMENT_ZONE = "PaymentArea"
QUEUE_ZONE = "BillingQueue"
CONFIDENCE_THRESHOLD = 0.35
IOU_THRESHOLD = 0.5
MIN_OVERLAP_PCT = 10
LOST_TRACK_FRAMES = 30
MIN_ZONE_STABILITY_FRAMES = 15
MIN_DWELL_SECONDS = 2.0


@dataclass
class TrackState:
    current_zone: str = OUT_OF_ZONE
    zone_enter_time: Optional[float] = None
    last_seen_frame: int = 0
    pending_zone: Optional[str] = None
    pending_zone_start_frame: Optional[int] = None
    pending_consecutive_frames: int = 0


@dataclass
class QueueEventStats:
    queue_enter: int = 0
    queue_exit: int = 0
    payment_enter: int = 0
    payment_exit: int = 0
    dwell_completed: int = 0

    @property
    def total(self) -> int:
        return (
            self.queue_enter
            + self.queue_exit
            + self.payment_enter
            + self.payment_exit
            + self.dwell_completed
        )


@dataclass
class StabilizationStats:
    ignored_zone_transitions: int = 0
    ignored_short_dwells: int = 0


class PaymentQueueEngine:
    """CAM5 queue and payment zone event engine (NOTEBK event shapes)."""

    def __init__(
        self,
        event_sink: EventSink,
        fps: float,
        camera_key: str = CAMERA_KEY,
    ) -> None:
        self.event_sink = event_sink
        self.fps = fps if fps > 0 else 30.0
        self.camera_key = camera_key
        self.track_states: Dict[int, TrackState] = {}
        self.stabilization = StabilizationStats()
        self.stats = QueueEventStats()

    def _clear_pending(self, state: TrackState) -> None:
        state.pending_zone = None
        state.pending_zone_start_frame = None
        state.pending_consecutive_frames = 0

    def _reject_pending(
        self,
        track_id: int,
        state: TrackState,
        frame_idx: int,
    ) -> None:
        if state.pending_zone is None:
            return
        logger.debug(
            "Zone candidate rejected track=%s committed=%s candidate=%s frames=%s frame=%s",
            track_id,
            state.current_zone,
            state.pending_zone,
            state.pending_consecutive_frames,
            frame_idx,
        )
        self.stabilization.ignored_zone_transitions += 1
        self._clear_pending(state)

    def frame_timestamp(self, frame_idx: int) -> str:
        return format_video_offset(frame_idx, self.fps)

    def frame_time_seconds(self, frame_idx: int) -> float:
        return video_seconds(frame_idx, self.fps)

    def _emit(self, event: Dict[str, Any]) -> None:
        event_type = str(event.get("event_type", ""))
        if event_type == "QUEUE_ENTER":
            self.stats.queue_enter += 1
        elif event_type == "QUEUE_EXIT":
            self.stats.queue_exit += 1
        elif event_type == "PAYMENT_ENTER":
            self.stats.payment_enter += 1
        elif event_type == "PAYMENT_EXIT":
            self.stats.payment_exit += 1
        elif event_type == "DWELL_COMPLETED":
            self.stats.dwell_completed += 1
        self.event_sink.emit_notbk(event)

    def _emit_queue_enter(self, track_id: int, frame_idx: int) -> None:
        self._emit(
            {
                "visitor_id": track_id,
                "camera": self.camera_key,
                "event_type": "QUEUE_ENTER",
                "timestamp": self.frame_timestamp(frame_idx),
            }
        )

    def _emit_queue_exit(self, track_id: int, frame_idx: int) -> None:
        self._emit(
            {
                "visitor_id": track_id,
                "camera": self.camera_key,
                "event_type": "QUEUE_EXIT",
                "timestamp": self.frame_timestamp(frame_idx),
            }
        )

    def _emit_payment_enter(self, track_id: int, frame_idx: int) -> None:
        self._emit(
            {
                "visitor_id": track_id,
                "camera": self.camera_key,
                "event_type": "PAYMENT_ENTER",
                "zone": PAYMENT_ZONE,
                "timestamp": self.frame_timestamp(frame_idx),
            }
        )

    def _emit_payment_exit(self, track_id: int, frame_idx: int) -> None:
        self._emit(
            {
                "visitor_id": track_id,
                "camera": self.camera_key,
                "event_type": "PAYMENT_EXIT",
                "zone": PAYMENT_ZONE,
                "timestamp": self.frame_timestamp(frame_idx),
            }
        )

    def _emit_payment_dwell_completed(
        self,
        track_id: int,
        zone_enter_time: Optional[float],
        exit_time: float,
        frame_idx: int,
    ) -> None:
        dwell_seconds = 0.0
        if zone_enter_time is not None:
            dwell_seconds = max(0.0, exit_time - zone_enter_time)

        if dwell_seconds < MIN_DWELL_SECONDS:
            self.stabilization.ignored_short_dwells += 1
            logger.debug(
                "Ignored short dwell track=%s zone=%s dwell=%.1fs",
                track_id,
                PAYMENT_ZONE,
                dwell_seconds,
            )
            return

        self._emit(
            {
                "visitor_id": track_id,
                "camera": self.camera_key,
                "event_type": "DWELL_COMPLETED",
                "zone": PAYMENT_ZONE,
                "dwell_seconds": round(dwell_seconds, 1),
                "timestamp": self.frame_timestamp(frame_idx),
            }
        )

    def _leave_payment_area(
        self,
        track_id: int,
        state: TrackState,
        frame_idx: int,
    ) -> None:
        exit_time = self.frame_time_seconds(frame_idx)
        self._emit_payment_exit(track_id, frame_idx)
        self._emit_payment_dwell_completed(
            track_id,
            state.zone_enter_time,
            exit_time,
            frame_idx,
        )

    def _leave_zone(
        self,
        track_id: int,
        state: TrackState,
        frame_idx: int,
    ) -> None:
        if state.current_zone == OUT_OF_ZONE:
            return

        previous_zone = state.current_zone
        if previous_zone == QUEUE_ZONE:
            self._emit_queue_exit(track_id, frame_idx)
        elif previous_zone == PAYMENT_ZONE:
            self._leave_payment_area(track_id, state, frame_idx)

        state.current_zone = OUT_OF_ZONE
        state.zone_enter_time = None

    def _handle_zone_change(
        self,
        track_id: int,
        previous_zone: str,
        current_zone: str,
        frame_idx: int,
    ) -> None:
        state = self.track_states[track_id]
        enter_time = self.frame_time_seconds(frame_idx)

        if previous_zone == QUEUE_ZONE:
            self._emit_queue_exit(track_id, frame_idx)
        elif previous_zone == PAYMENT_ZONE:
            self._leave_payment_area(track_id, state, frame_idx)

        if current_zone == QUEUE_ZONE and previous_zone == OUT_OF_ZONE:
            self._emit_queue_enter(track_id, frame_idx)
            state.zone_enter_time = enter_time
        elif current_zone == PAYMENT_ZONE and previous_zone in (OUT_OF_ZONE, QUEUE_ZONE):
            self._emit_payment_enter(track_id, frame_idx)
            state.zone_enter_time = enter_time
        elif current_zone != OUT_OF_ZONE:
            state.zone_enter_time = enter_time
        else:
            state.zone_enter_time = None

        state.current_zone = current_zone
        self._clear_pending(state)

    def _commit_zone_change(
        self,
        track_id: int,
        previous_zone: str,
        new_zone: str,
        frame_idx: int,
    ) -> None:
        logger.debug(
            "Zone confirmed track=%s %s -> %s frame=%s",
            track_id,
            previous_zone,
            new_zone,
            frame_idx,
        )
        self._handle_zone_change(track_id, previous_zone, new_zone, frame_idx)

    def _process_detected_zone(
        self,
        track_id: int,
        detected_zone: str,
        frame_idx: int,
    ) -> None:
        state = self.track_states[track_id]
        committed_zone = state.current_zone

        if detected_zone == committed_zone:
            self._reject_pending(track_id, state, frame_idx)
            return

        if state.pending_zone != detected_zone:
            state.pending_zone = detected_zone
            state.pending_zone_start_frame = frame_idx
            state.pending_consecutive_frames = 1
            logger.debug(
                "Zone candidate track=%s %s -> %s frame=%s",
                track_id,
                committed_zone,
                detected_zone,
                frame_idx,
            )
            return

        state.pending_consecutive_frames += 1
        if state.pending_consecutive_frames >= MIN_ZONE_STABILITY_FRAMES:
            self._commit_zone_change(
                track_id,
                committed_zone,
                detected_zone,
                frame_idx,
            )

    def update_active_tracks(
        self,
        frame_idx: int,
        track_zones: Dict[int, str],
    ) -> None:
        active_ids = set(track_zones.keys())

        for track_id, detected_zone in track_zones.items():
            if track_id not in self.track_states:
                self.track_states[track_id] = TrackState(last_seen_frame=frame_idx)

            state = self.track_states[track_id]
            self._process_detected_zone(track_id, detected_zone, frame_idx)
            state.last_seen_frame = frame_idx

        lost_track_ids = [
            track_id
            for track_id, state in self.track_states.items()
            if track_id not in active_ids
            and frame_idx - state.last_seen_frame > LOST_TRACK_FRAMES
        ]
        for track_id in lost_track_ids:
            state = self.track_states[track_id]
            self._clear_pending(state)
            self._leave_zone(track_id, state, frame_idx)
            del self.track_states[track_id]

    def finalize(self, frame_idx: int) -> None:
        remaining_ids = list(self.track_states.keys())
        for track_id in remaining_ids:
            state = self.track_states[track_id]
            self._clear_pending(state)
            self._leave_zone(track_id, state, frame_idx)
            del self.track_states[track_id]


def denormalize_polygon(
    points: List[Tuple[float, float]],
    width: int,
    height: int,
) -> np.ndarray:
    return np.array(
        [(int(x * width), int(y * height)) for x, y in points],
        dtype=np.int32,
    )


def build_zone_polygons(
    video_width: int,
    video_height: int,
    *,
    store: StoreConfig | None = None,
) -> Dict[str, np.ndarray]:
    cfg = resolve_store_config(store)
    return build_cam5_zone_polygons(cfg.cam5, video_width, video_height)


def create_byte_tracker() -> sv.ByteTrack:
    return sv.ByteTrack()


def detect_persons(
    frame_bgr: np.ndarray,
    yolo_model: YOLO,
    conf: float = CONFIDENCE_THRESHOLD,
    iou: float = IOU_THRESHOLD,
) -> sv.Detections:
    results = yolo_model.predict(
        source=frame_bgr,
        conf=conf,
        iou=iou,
        classes=[PERSON_CLASS_ID],
        verbose=False,
        stream=False,
    )
    detections = sv.Detections.from_ultralytics(results[0])
    del results
    return detections


def bbox_polygon_overlap_pct(
    xyxy: np.ndarray,
    polygon: np.ndarray,
    frame_width: int,
    frame_height: int,
) -> float:
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


def resolve_zone_by_priority(
    xyxy: np.ndarray,
    zone_polygons: Dict[str, np.ndarray],
    frame_width: int,
    frame_height: int,
) -> str:
    inside_payment = (
        bbox_polygon_overlap_pct(
            xyxy, zone_polygons[PAYMENT_ZONE], frame_width, frame_height
        )
        >= MIN_OVERLAP_PCT
    )
    inside_queue = (
        bbox_polygon_overlap_pct(
            xyxy, zone_polygons[QUEUE_ZONE], frame_width, frame_height
        )
        >= MIN_OVERLAP_PCT
    )

    if inside_payment:
        return PAYMENT_ZONE
    if inside_queue:
        return QUEUE_ZONE
    return OUT_OF_ZONE


def assign_track_zones(
    detections: sv.Detections,
    zone_polygons: Dict[str, np.ndarray],
    frame_width: int,
    frame_height: int,
) -> Dict[int, str]:
    if detections.tracker_id is None or len(detections) == 0:
        return {}

    track_zones: Dict[int, str] = {}
    for track_id, xyxy in zip(detections.tracker_id, detections.xyxy):
        tid = int(track_id)
        track_zones[tid] = resolve_zone_by_priority(
            xyxy, zone_polygons, frame_width, frame_height
        )
    return track_zones


def process_cam5_video(
    video_path: Path | None = None,
    *,
    emitter: PipelineEmitter | None = None,
    show_window: bool = False,
    model_path: Path | None = None,
    store: StoreConfig | None = None,
) -> QueueEventStats:
    """Run CAM5 queue/payment pipeline; optional Purpple JSONL via emitter."""
    if emitter is None:
        raise ValueError("emitter is required for CAM5 pipeline output")

    cfg = resolve_store_config(store)
    if not cfg.cam5.enabled:
        raise RuntimeError(f"{cfg.store_key}: CAM5 is disabled in cam5.json")

    path = video_path or cfg.videos.video_path(CAMERA_KEY)
    if path is None:
        raise FileNotFoundError(f"{cfg.store_key}: no CAM5 video configured")

    weights = model_path or Path(os.getenv("YOLO_MODEL_PATH", cfg.yolo_model_path))
    process_every_n = cfg.cam5.detection.process_every_n_frames
    progress_every_n = cfg.cam5.detection.progress_log_every_n_frames
    confidence_threshold = cfg.cam5.detection.confidence_threshold
    iou_threshold = cfg.cam5.detection.iou_threshold
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise FileNotFoundError(f"Unable to open video: {path}")

    video_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    logger.info(
        "CAM5 resolution %sx%s @ %.2f fps, %s frames, inference every %s",
        video_width,
        video_height,
        fps,
        total_frames,
        process_every_n,
    )

    yolo_model = YOLO(str(weights))
    zone_polygons = build_zone_polygons(
        video_width, video_height, store=cfg
    )
    engine = PaymentQueueEngine(event_sink=emitter, fps=fps)
    tracker = create_byte_tracker()

    original_frame = 0
    processed_count = 0
    try:
        while capture.isOpened():
            try:
                success, frame = capture.read()
            except cv2.error as exc:
                logger.warning("OpenCV read error: %s", exc)
                break

            if not success or frame is None:
                break

            if original_frame % process_every_n != 0:
                original_frame += 1
                if original_frame % progress_every_n == 0:
                    pct = 100.0 * original_frame / total_frames if total_frames > 0 else 0.0
                    logger.info(
                        "[PROGRESS] CAM5 frame=%s processed=%s (%.1f%% complete) "
                        "queue_enter=%s queue_exit=%s payment_enter=%s payment_exit=%s",
                        original_frame,
                        processed_count,
                        pct,
                        engine.stats.queue_enter,
                        engine.stats.queue_exit,
                        engine.stats.payment_enter,
                        engine.stats.payment_exit,
                    )
                del frame
                continue

            detections = detect_persons(
                frame,
                yolo_model,
                conf=confidence_threshold,
                iou=iou_threshold,
            )
            detections = tracker.update_with_detections(detections)
            track_zones = assign_track_zones(
                detections, zone_polygons, video_width, video_height
            )
            engine.update_active_tracks(original_frame, track_zones)
            processed_count += 1
            del frame, detections, track_zones
            original_frame += 1
            if original_frame % progress_every_n == 0:
                pct = 100.0 * original_frame / total_frames if total_frames > 0 else 0.0
                logger.info(
                    "[PROGRESS] CAM5 frame=%s processed=%s (%.1f%% complete) "
                    "queue_enter=%s queue_exit=%s payment_enter=%s payment_exit=%s",
                    original_frame,
                    processed_count,
                    pct,
                    engine.stats.queue_enter,
                    engine.stats.queue_exit,
                    engine.stats.payment_enter,
                    engine.stats.payment_exit,
                )
    finally:
        engine.finalize(original_frame)
        capture.release()

    pct = 100.0 * original_frame / total_frames if total_frames > 0 else 0.0
    logger.info(
        "CAM5 complete: frames=%s processed=%s (%.1f%%) events=%s",
        original_frame,
        processed_count,
        pct,
        engine.stats.total,
    )
    return engine.stats


def run_cli(
    output_path: Path | None = None,
    *,
    show_window: bool = False,
    store: StoreConfig | None = None,
) -> None:
    cfg = resolve_store_config(store)
    refresh_store_config(cfg.store_key)
    out = output_path or (cfg.pipeline_output_dir / "cam5_events.jsonl")
    clip_start = parse_clip_start(CAMERA_KEY, store=cfg)
    with PipelineEmitter(
        output_path=out,
        store_id=cfg.store_id,
        clip_start_by_camera={CAMERA_KEY: clip_start},
    ) as emitter:
        process_cam5_video(emitter=emitter, show_window=show_window, store=cfg)
        logger.info(
            "Wrote %s Purpple events (%s NOTEBK rows, %s errors)",
            emitter.stats.purpple_written,
            emitter.stats.notbk_received,
            emitter.stats.adaptation_errors,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_cli(show_window=False)
