"""Zone dwell tracking: stability frames, ZONE_ENTER/EXIT, DWELL_COMPLETED."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import supervision as sv

from pipeline.config import (
    LOST_TRACK_FRAMES,
    MIN_DWELL_SECONDS,
    MIN_ZONE_STABILITY_FRAMES,
    OUT_OF_ZONE,
    PROCESS_EVERY_N_FRAMES,
    PROGRESS_LOG_EVERY_N_FRAMES,
)
from pipeline.detect import detect_persons, load_yolo_model
from pipeline.emit import PipelineEmitter
from pipeline.sink import EventSink
from pipeline.tracker import create_byte_tracker, update_tracks
from pipeline.video_time import format_video_offset, video_seconds
from pipeline.zones import assign_track_zones, build_zone_polygons

logger = logging.getLogger(__name__)


@dataclass
class TrackState:
    current_zone: str = OUT_OF_ZONE
    zone_enter_time: Optional[float] = None
    last_seen_frame: int = 0
    pending_zone: Optional[str] = None
    pending_zone_start_frame: Optional[int] = None
    pending_consecutive_frames: int = 0


@dataclass
class ZoneEngagementStats:
    zone_enter: int = 0
    zone_exit: int = 0
    dwell_completed: int = 0
    ignored_zone_transitions: int = 0
    ignored_short_dwells: int = 0

    @property
    def total(self) -> int:
        return self.zone_enter + self.zone_exit + self.dwell_completed


class ZoneEngagementEngine:
    """
    Per-track zone stability and dwell events (NOTEBK cam1/cam2 semantics).

    Emits ZONE_ENTER, ZONE_EXIT, DWELL_COMPLETED via ``EventSink.emit_notbk``.
    """

    def __init__(
        self,
        *,
        camera_key: str,
        fps: float,
        event_sink: EventSink | None = None,
    ) -> None:
        self.camera_key = camera_key
        self.fps = fps if fps > 0 else 30.0
        self.event_sink = event_sink
        self.track_states: Dict[int, TrackState] = {}
        self.stats = ZoneEngagementStats()

    def _clear_pending(self, state: TrackState) -> None:
        state.pending_zone = None
        state.pending_zone_start_frame = None
        state.pending_consecutive_frames = 0

    def _reject_pending(self, track_id: int, state: TrackState, frame_idx: int) -> None:
        if state.pending_zone is None:
            return
        logger.debug(
            "Zone candidate rejected: track=%s committed=%s candidate=%s frames=%s frame=%s",
            track_id,
            state.current_zone,
            state.pending_zone,
            state.pending_consecutive_frames,
            frame_idx,
        )
        self.stats.ignored_zone_transitions += 1
        self._clear_pending(state)

    def frame_timestamp(self, frame_idx: int) -> str:
        return format_video_offset(frame_idx, self.fps)

    def frame_time_seconds(self, frame_idx: int) -> float:
        return video_seconds(frame_idx, self.fps)

    def _emit_notbk(self, row: dict) -> None:
        if self.event_sink is None:
            return
        event_type = row.get("event_type", "")
        if event_type == "ZONE_ENTER":
            self.stats.zone_enter += 1
        elif event_type == "ZONE_EXIT":
            self.stats.zone_exit += 1
        elif event_type == "DWELL_COMPLETED":
            self.stats.dwell_completed += 1
        self.event_sink.emit_notbk(row)

    def _emit_zone_exit(self, track_id: int, zone: str, frame_idx: int) -> float:
        exit_time = self.frame_time_seconds(frame_idx)
        self._emit_notbk(
            {
                "visitor_id": track_id,
                "camera": self.camera_key,
                "event_type": "ZONE_EXIT",
                "zone": zone,
                "timestamp": self.frame_timestamp(frame_idx),
            }
        )
        return exit_time

    def _emit_dwell_completed(
        self,
        track_id: int,
        zone: str,
        zone_enter_time: Optional[float],
        exit_time: float,
        frame_idx: int,
    ) -> None:
        dwell_seconds = 0.0
        if zone_enter_time is not None:
            dwell_seconds = max(0.0, exit_time - zone_enter_time)

        if dwell_seconds < MIN_DWELL_SECONDS:
            self.stats.ignored_short_dwells += 1
            logger.debug(
                "Ignored short dwell: track=%s zone=%s dwell=%.1fs min=%ss",
                track_id,
                zone,
                dwell_seconds,
                MIN_DWELL_SECONDS,
            )
            return

        self._emit_notbk(
            {
                "visitor_id": track_id,
                "camera": self.camera_key,
                "event_type": "DWELL_COMPLETED",
                "zone": zone,
                "dwell_seconds": round(dwell_seconds, 1),
                "timestamp": self.frame_timestamp(frame_idx),
            }
        )

    def _emit_zone_enter(self, track_id: int, zone: str, frame_idx: int) -> float:
        enter_time = self.frame_time_seconds(frame_idx)
        self._emit_notbk(
            {
                "visitor_id": track_id,
                "camera": self.camera_key,
                "event_type": "ZONE_ENTER",
                "zone": zone,
                "timestamp": self.frame_timestamp(frame_idx),
            }
        )
        return enter_time

    def _leave_zone(self, track_id: int, state: TrackState, frame_idx: int) -> None:
        if state.current_zone == OUT_OF_ZONE:
            return

        exit_time = self._emit_zone_exit(track_id, state.current_zone, frame_idx)
        self._emit_dwell_completed(
            track_id,
            state.current_zone,
            state.zone_enter_time,
            exit_time,
            frame_idx,
        )
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

        if previous_zone != OUT_OF_ZONE:
            exit_time = self._emit_zone_exit(track_id, previous_zone, frame_idx)
            self._emit_dwell_completed(
                track_id,
                previous_zone,
                state.zone_enter_time,
                exit_time,
                frame_idx,
            )

        if current_zone != OUT_OF_ZONE:
            state.zone_enter_time = self._emit_zone_enter(
                track_id, current_zone, frame_idx
            )
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
            "Zone confirmed: track=%s %s -> %s frame=%s",
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
                "Zone candidate: track=%s %s -> %s frame=%s",
                track_id,
                committed_zone,
                detected_zone,
                frame_idx,
            )
            return

        state.pending_consecutive_frames += 1
        if state.pending_consecutive_frames >= MIN_ZONE_STABILITY_FRAMES:
            self._commit_zone_change(
                track_id, committed_zone, detected_zone, frame_idx
            )

    def update_active_tracks(
        self,
        frame_idx: int,
        track_zones: Dict[int, Tuple[str, int]],
    ) -> None:
        active_ids = set(track_zones.keys())

        for track_id, (detected_zone, _) in track_zones.items():
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

    def get_dwell_seconds(self, track_id: int, frame_idx: int) -> float:
        state = self.track_states.get(track_id)
        if state is None or state.current_zone == OUT_OF_ZONE:
            return 0.0
        if state.zone_enter_time is None:
            return 0.0
        return max(0.0, self.frame_time_seconds(frame_idx) - state.zone_enter_time)


def process_zone_engagement_video(
    *,
    camera_key: str,
    zone_definitions: dict[str, list[tuple[float, float]]],
    video_path: Path,
    emitter: PipelineEmitter | None = None,
    show_window: bool = False,
    window_title: str | None = None,
    process_every_n: int = PROCESS_EVERY_N_FRAMES,
    annotated_video_path: Path | None = None,
    min_overlap_pct: float | None = None,
) -> ZoneEngagementStats:
    """
    Run YOLO11m + ByteTrack zone-engagement on a CCTV clip.

    Detection/tracking/zones are shared pipeline modules; events go through emitter.
    """
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise FileNotFoundError(f"Unable to open video: {video_path}")

    video_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    logger.info(
        "%s resolution %sx%s @ %.2f fps, %s zones, %s frames, inference every %s",
        camera_key,
        video_width,
        video_height,
        fps,
        len(zone_definitions),
        total_frames,
        process_every_n,
    )

    yolo_model = load_yolo_model()
    zone_polygons = build_zone_polygons(zone_definitions, video_width, video_height)
    sink: EventSink | None = emitter
    engine = ZoneEngagementEngine(
        camera_key=camera_key,
        fps=fps,
        event_sink=sink,
    )
    tracker = create_byte_tracker()
    overlap_pct = (
        float(min_overlap_pct)
        if min_overlap_pct is not None
        else float(MIN_OVERLAP_PCT)
    )

    from pipeline.shelf_preview import (
        compose_tracking_frame,
        draw_tracking_hud,
        draw_zone_overlays,
        open_mp4_writer,
    )

    title = window_title or f"{camera_key} Zone Engagement"
    if show_window:
        cv2.namedWindow(title, cv2.WINDOW_NORMAL)

    writer: cv2.VideoWriter | None = None
    if annotated_video_path is not None:
        writer = open_mp4_writer(annotated_video_path, video_width, video_height, fps)

    last_detections: sv.Detections | None = None
    last_track_zones: dict[int, tuple[str, int]] = {}

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

            run_inference = original_frame % process_every_n == 0
            if run_inference:
                detections = detect_persons(frame, yolo_model)
                detections = update_tracks(tracker, detections)
                track_zones = assign_track_zones(
                    detections,
                    zone_polygons,
                    video_width,
                    video_height,
                    min_overlap_pct=overlap_pct,
                )
                engine.update_active_tracks(original_frame, track_zones)
                last_detections = detections
                last_track_zones = track_zones
                processed_count += 1
            else:
                track_zones = last_track_zones

            if writer is not None or show_window:
                if last_detections is not None and len(last_detections) > 0:
                    display = compose_tracking_frame(
                        frame,
                        zone_polygons,
                        last_detections,
                        last_track_zones,
                    )
                else:
                    display = draw_zone_overlays(frame, zone_polygons)
                display = draw_tracking_hud(
                    display,
                    camera_label=f"{camera_key} · shelf tracking",
                    aisle_visits=engine.stats.zone_enter,
                    frame_idx=original_frame,
                )
                if writer is not None:
                    writer.write(display)
                if show_window:
                    cv2.imshow(title, display)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), 27):
                        break

            if not run_inference:
                original_frame += 1
                if original_frame % PROGRESS_LOG_EVERY_N_FRAMES == 0:
                    pct = 100.0 * original_frame / total_frames if total_frames > 0 else 0.0
                    logger.info(
                        "[PROGRESS] %s frame=%s processed=%s (%.1f%% complete) "
                        "zone_enter=%s zone_exit=%s dwell_completed=%s",
                        camera_key,
                        original_frame,
                        processed_count,
                        pct,
                        engine.stats.zone_enter,
                        engine.stats.zone_exit,
                        engine.stats.dwell_completed,
                    )
                del frame
                continue

            del frame, detections, track_zones
            original_frame += 1
            if original_frame % PROGRESS_LOG_EVERY_N_FRAMES == 0:
                pct = 100.0 * original_frame / total_frames if total_frames > 0 else 0.0
                logger.info(
                    "[PROGRESS] %s frame=%s processed=%s (%.1f%% complete) "
                    "zone_enter=%s zone_exit=%s dwell_completed=%s",
                    camera_key,
                    original_frame,
                    processed_count,
                    pct,
                    engine.stats.zone_enter,
                    engine.stats.zone_exit,
                    engine.stats.dwell_completed,
                )
    finally:
        engine.finalize(original_frame)
        capture.release()
        if writer is not None:
            writer.release()
            logger.info("Wrote annotated tracking video: %s", annotated_video_path)
        if show_window:
            cv2.destroyAllWindows()

    pct = 100.0 * original_frame / total_frames if total_frames > 0 else 0.0
    logger.info(
        "%s complete: frames=%s processed=%s (%.1f%%) "
        "enters=%s exits=%s dwells=%s ignored_trans=%s ignored_short=%s",
        camera_key,
        original_frame,
        processed_count,
        pct,
        engine.stats.zone_enter,
        engine.stats.zone_exit,
        engine.stats.dwell_completed,
        engine.stats.ignored_zone_transitions,
        engine.stats.ignored_short_dwells,
    )
    return engine.stats
