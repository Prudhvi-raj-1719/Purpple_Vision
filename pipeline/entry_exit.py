"""Entry/exit line-crossing detection and REENTRY event generation."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple, TypedDict

import cv2
import numpy as np
import supervision as sv

from pipeline.config import (
    CAM3_ENTRY_LINE_POLYGON,
    CAMERA_VIDEO_FILES,
    DEFAULT_STORE_ID,
    OUTPUT_DIR,
    PROCESS_EVERY_N_FRAMES,
    PROGRESS_LOG_EVERY_N_FRAMES,
    parse_clip_start,
)
from pipeline.detect import detect_persons, load_yolo_model
from pipeline.emit import PipelineEmitter
from pipeline.sink import EventSink
from pipeline.tracker import create_byte_tracker, update_tracks
from pipeline.video_time import format_video_offset
from pipeline.zones import denormalize_polygon

logger = logging.getLogger(__name__)

CAMERA_KEY = "CAM3"
# Set CAM3_DISABLE_BYTETRACK=1 to bypass ByteTrack (raw detections only, for hang diagnosis).
DISABLE_BYTETRACK = os.getenv("CAM3_DISABLE_BYTETRACK", "").lower() in ("1", "true", "yes")
INSIDE_DOORWAY = "INSIDE_DOORWAY"
OUTSIDE_DOORWAY = "OUTSIDE_DOORWAY"
ENTRY_POLYGON_COLOR: Tuple[int, int, int] = (0, 0, 255)


class TrackRecord(TypedDict):
    previous_state: str
    current_state: str
    counted: bool


def get_bbox_center(x1: float, y1: float, x2: float, y2: float) -> Tuple[int, int]:
    return ((int(x1) + int(x2)) // 2, (int(y1) + int(y2)) // 2)


def classify_doorway_state(
    center: Tuple[int, int],
    entry_polygon: np.ndarray,
) -> str:
    inside_polygon = cv2.pointPolygonTest(entry_polygon, center, False)
    if inside_polygon >= 0:
        return INSIDE_DOORWAY
    return OUTSIDE_DOORWAY


@dataclass
class EntryExitStats:
    entry_count: int = 0
    exit_count: int = 0


class EntryExitCounter:
    """Count doorway entry/exit transitions per track without double counting."""

    def __init__(
        self,
        *,
        camera_key: str = CAMERA_KEY,
        fps: float = 30.0,
        event_sink: EventSink | None = None,
    ) -> None:
        self.camera_key = camera_key
        self.fps = fps if fps > 0 else 30.0
        self.event_sink = event_sink
        self.track_history: Dict[int, TrackRecord] = {}
        self.stats = EntryExitStats()

    def update_track(
        self,
        track_id: int,
        center: Tuple[int, int],
        entry_polygon: np.ndarray,
        frame_idx: int,
    ) -> str:
        current_state = classify_doorway_state(center, entry_polygon)

        if track_id not in self.track_history:
            self.track_history[track_id] = {
                "previous_state": current_state,
                "current_state": current_state,
                "counted": False,
            }
            return current_state

        record = self.track_history[track_id]
        previous_state = record["current_state"]
        record["previous_state"] = previous_state
        record["current_state"] = current_state

        if previous_state != current_state:
            if previous_state == OUTSIDE_DOORWAY and current_state == INSIDE_DOORWAY:
                self.stats.entry_count += 1
                record["counted"] = True
                self._emit_transition(track_id, "ENTRY", frame_idx)
                logger.info("ENTRY detected -> track %s frame %s", track_id, frame_idx)
            elif previous_state == INSIDE_DOORWAY and current_state == OUTSIDE_DOORWAY:
                self.stats.exit_count += 1
                record["counted"] = True
                self._emit_transition(track_id, "EXIT", frame_idx)
                logger.info("EXIT detected -> track %s frame %s", track_id, frame_idx)
            else:
                record["counted"] = False
        else:
            record["counted"] = False

        return current_state

    def _emit_transition(self, track_id: int, event_type: str, frame_idx: int) -> None:
        if self.event_sink is None:
            return
        logger.debug(
            "Emitting %s event track=%s frame=%s",
            event_type,
            track_id,
            frame_idx,
        )
        self.event_sink.emit_notbk(
            {
                "visitor_id": track_id,
                "camera": self.camera_key,
                "event_type": event_type,
                "timestamp": format_video_offset(frame_idx, self.fps),
            }
        )

    def process_detections(
        self,
        detections: sv.Detections,
        entry_polygon: np.ndarray,
        frame_idx: int,
    ) -> Dict[int, Tuple[str, Tuple[int, int]]]:
        track_states: Dict[int, Tuple[str, Tuple[int, int]]] = {}
        if detections.tracker_id is None or len(detections) == 0:
            return track_states

        for track_id, xyxy in zip(detections.tracker_id, detections.xyxy):
            tid = int(track_id)
            x1, y1, x2, y2 = xyxy
            center = get_bbox_center(x1, y1, x2, y2)
            state = self.update_track(tid, center, entry_polygon, frame_idx)
            track_states[tid] = (state, center)

        return track_states


def _assign_raw_track_ids(detections: sv.Detections) -> sv.Detections:
    """Use detection index as track ID when ByteTrack is disabled for debugging."""
    if len(detections) == 0:
        detections.tracker_id = np.array([], dtype=int)
    else:
        detections.tracker_id = np.arange(len(detections), dtype=int)
    return detections


def process_cam3_video(
    video_path: Path | None = None,
    *,
    emitter: PipelineEmitter | None = None,
    show_window: bool = False,
) -> EntryExitStats:
    """
    Run CAM3 entry/exit pipeline on a video file.

    When ``emitter`` is provided, writes Purpple-schema JSONL via event_adapter.
    """
    path = video_path or CAMERA_VIDEO_FILES[CAMERA_KEY]
    logger.info("[DEBUG] Opening video: %s", path)
    t_open = time.perf_counter()
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise FileNotFoundError(f"Unable to open video: {path}")
    logger.info("[DEBUG] Video opened in %.2fs", time.perf_counter() - t_open)

    video_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    logger.info(
        "CAM3 resolution %sx%s @ %.2f fps (%s frames, ~%.1f min clip)",
        video_width,
        video_height,
        fps,
        total_frames,
        (total_frames / fps / 60.0) if fps > 0 else 0.0,
    )

    logger.info("[DEBUG] Loading YOLO model …")
    t_yolo_load = time.perf_counter()
    yolo_model = load_yolo_model()
    logger.info("[DEBUG] YOLO model loaded in %.2fs", time.perf_counter() - t_yolo_load)

    entry_polygon = denormalize_polygon(
        CAM3_ENTRY_LINE_POLYGON,
        video_width,
        video_height,
    )
    logger.info("[DEBUG] Entry polygon denormalized (%s vertices)", len(entry_polygon))

    sink: EventSink | None = emitter
    counter = EntryExitCounter(camera_key=CAMERA_KEY, fps=fps, event_sink=sink)
    tracker = None if DISABLE_BYTETRACK else create_byte_tracker()
    if DISABLE_BYTETRACK:
        logger.warning(
            "[DEBUG] ByteTrack DISABLED (CAM3_DISABLE_BYTETRACK=1) — using raw detection IDs"
        )
    else:
        logger.info("[DEBUG] ByteTrack tracker created")

    window_name = "CAM3 Entry Exit"
    if show_window:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    logger.info(
        "CAM3 inference stride: every %s frames (same as CAM1/CAM2)",
        PROCESS_EVERY_N_FRAMES,
    )

    frame_idx = 0
    processed_count = 0
    read_failures = 0
    detect_ms = 0.0
    try:
        while capture.isOpened():
            if frame_idx == 0:
                logger.info("[DEBUG] Reading first frame …")
            try:
                t_read = time.perf_counter()
                success, frame = capture.read()
                read_ms = (time.perf_counter() - t_read) * 1000.0
            except cv2.error as exc:
                logger.warning("OpenCV read error at frame %s: %s", frame_idx, exc)
                break

            if frame_idx == 0:
                logger.info(
                    "[DEBUG] First frame read in %.0fms: success=%s shape=%s",
                    read_ms,
                    success,
                    frame.shape if success and frame is not None else None,
                )

            if not success or frame is None:
                read_failures += 1
                logger.info(
                    "[DEBUG] End of video at frame_idx=%s (read success=%s)",
                    frame_idx,
                    success,
                )
                break

            if frame_idx % PROCESS_EVERY_N_FRAMES != 0:
                frame_idx += 1
                if frame_idx % PROGRESS_LOG_EVERY_N_FRAMES == 0:
                    pct = 100.0 * frame_idx / total_frames if total_frames > 0 else 0.0
                    logger.info(
                        "[PROGRESS] frame=%s processed=%s (%.1f%% complete) "
                        "entries=%s exits=%s",
                        frame_idx,
                        processed_count,
                        pct,
                        counter.stats.entry_count,
                        counter.stats.exit_count,
                    )
                del frame
                continue

            logger.debug("[DEBUG] Frame %s: starting YOLO inference …", frame_idx)
            t_detect = time.perf_counter()
            detections = detect_persons(frame, yolo_model)
            detect_ms = (time.perf_counter() - t_detect) * 1000.0
            processed_count += 1
            if processed_count == 1:
                logger.info(
                    "[DEBUG] Frame %s YOLO inference done in %.0fms (%s persons)",
                    frame_idx,
                    detect_ms,
                    len(detections),
                )

            logger.debug(
                "[DEBUG] Frame %s: ByteTrack update (%s detections) …",
                frame_idx,
                len(detections),
            )
            t_track = time.perf_counter()
            if DISABLE_BYTETRACK:
                detections = _assign_raw_track_ids(detections)
            else:
                detections = update_tracks(tracker, detections)
            if processed_count == 1:
                logger.info(
                    "[DEBUG] Frame %s tracking done in %.0fms (ByteTrack=%s)",
                    frame_idx,
                    (time.perf_counter() - t_track) * 1000.0,
                    not DISABLE_BYTETRACK,
                )

            logger.debug("[DEBUG] Frame %s: line crossing check …", frame_idx)
            track_states = counter.process_detections(detections, entry_polygon, frame_idx)
            if processed_count == 1:
                logger.info(
                    "[DEBUG] Frame %s line crossing check done (%s active tracks)",
                    frame_idx,
                    len(track_states),
                )

            frame_idx += 1
            if frame_idx % PROGRESS_LOG_EVERY_N_FRAMES == 0:
                pct = 100.0 * frame_idx / total_frames if total_frames > 0 else 0.0
                logger.info(
                    "[PROGRESS] frame=%s processed=%s (%.1f%% complete) "
                    "entries=%s exits=%s last_yolo=%.0fms",
                    frame_idx,
                    processed_count,
                    pct,
                    counter.stats.entry_count,
                    counter.stats.exit_count,
                    detect_ms,
                )

            if show_window:
                cv2.imshow(window_name, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    logger.info("[DEBUG] User quit at frame %s", frame_idx)
                    break

            del frame, detections, track_states
    finally:
        capture.release()
        if show_window:
            cv2.destroyAllWindows()

    pct = 100.0 * frame_idx / total_frames if total_frames > 0 else 0.0
    logger.info(
        "CAM3 complete: frames=%s processed=%s (%.1f%%) read_failures=%s "
        "entries=%s exits=%s inference_stride=%s",
        frame_idx,
        processed_count,
        pct,
        read_failures,
        counter.stats.entry_count,
        counter.stats.exit_count,
        PROCESS_EVERY_N_FRAMES,
    )
    return counter.stats


def run_cli(
    output_path: Path | None = None,
    *,
    show_window: bool = False,
) -> None:
    """CLI entry: process CAM3 and write adapted events JSONL."""
    out = output_path or (OUTPUT_DIR / "cam3_events.jsonl")
    clip_start = parse_clip_start(CAMERA_KEY)
    with PipelineEmitter(
        output_path=out,
        store_id=DEFAULT_STORE_ID,
        clip_start_by_camera={CAMERA_KEY: clip_start},
    ) as emitter:
        process_cam3_video(emitter=emitter, show_window=show_window)
        logger.info(
            "Wrote %s Purpple events (%s adapted, %s errors)",
            emitter.stats.purpple_written,
            emitter.stats.notbk_received,
            emitter.stats.adaptation_errors,
        )


if __name__ == "__main__":
    log_level = logging.DEBUG if os.getenv("CAM3_DEBUG", "").lower() in ("1", "true", "yes") else logging.INFO
    logging.basicConfig(level=log_level, format="%(message)s")
    run_cli(show_window=False)
