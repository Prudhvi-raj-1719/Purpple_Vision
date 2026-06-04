"""
CAM4 empty-camera robustness processor.

Runs YOLO person detection + ByteTrack only. Counts persons seen in frame;
does not emit zone, queue, entry/exit, or staff events.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2

from pipeline.config import (
    CAMERA_VIDEO_FILES,
    DEFAULT_STORE_ID,
    OUTPUT_DIR,
    PROCESS_EVERY_N_FRAMES,
    PROGRESS_LOG_EVERY_N_FRAMES,
    parse_clip_start,
)
from pipeline.detect import detect_persons, load_yolo_model
from pipeline.emit import PipelineEmitter
from pipeline.tracker import create_byte_tracker, update_tracks

logger = logging.getLogger(__name__)

CAMERA_KEY = "CAM4"


@dataclass
class Cam4RobustnessStats:
    """Detection-only stats for CAM4 (no business events)."""

    frames_processed: int = 0
    max_persons_in_frame: int = 0
    unique_track_ids: int = 0

    @property
    def persons_detected(self) -> int:
        """Peak concurrent persons observed on any processed frame."""
        return self.max_persons_in_frame


def process_cam4_video(
    video_path: Path | None = None,
    *,
    emitter: PipelineEmitter | None = None,
    show_window: bool = False,
) -> Cam4RobustnessStats:
    """
    Process CAM4 footage: detect and track persons only.

    ``emitter`` is accepted for orchestrator compatibility but this processor
    never calls ``emit_notbk`` (output JSONL files remain empty).
    """
    del emitter  # orchestrators pass emitter; CAM4 does not emit events

    path = video_path or CAMERA_VIDEO_FILES[CAMERA_KEY]
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise FileNotFoundError(f"Unable to open video: {path}")

    video_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    logger.info(
        "%s robustness scan %sx%s @ %.2f fps, %s frames, inference every %s",
        CAMERA_KEY,
        video_width,
        video_height,
        fps,
        total_frames,
        PROCESS_EVERY_N_FRAMES,
    )

    yolo_model = load_yolo_model()
    tracker = create_byte_tracker()
    stats = Cam4RobustnessStats()
    seen_track_ids: set[int] = set()

    window_title = "CAM4 Robustness"
    if show_window:
        cv2.namedWindow(window_title, cv2.WINDOW_NORMAL)

    original_frame = 0
    try:
        while capture.isOpened():
            try:
                success, frame = capture.read()
            except cv2.error as exc:
                logger.warning("OpenCV read error: %s", exc)
                break

            if not success or frame is None:
                break

            if original_frame % PROCESS_EVERY_N_FRAMES != 0:
                original_frame += 1
                if original_frame % PROGRESS_LOG_EVERY_N_FRAMES == 0:
                    pct = 100.0 * original_frame / total_frames if total_frames > 0 else 0.0
                    logger.info(
                        "[PROGRESS] %s frame=%s processed=%s (%.1f%%) "
                        "max_persons=%s unique_tracks=%s",
                        CAMERA_KEY,
                        original_frame,
                        stats.frames_processed,
                        pct,
                        stats.max_persons_in_frame,
                        len(seen_track_ids),
                    )
                del frame
                continue

            detections = detect_persons(frame, yolo_model)
            detections = update_tracks(tracker, detections)

            persons_this_frame = 0
            if detections.tracker_id is not None and len(detections) > 0:
                for track_id in detections.tracker_id:
                    tid = int(track_id)
                    seen_track_ids.add(tid)
                    persons_this_frame += 1

            stats.max_persons_in_frame = max(
                stats.max_persons_in_frame, persons_this_frame
            )
            stats.frames_processed += 1

            if show_window:
                cv2.imshow(window_title, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break

            del frame, detections
            original_frame += 1
            if original_frame % PROGRESS_LOG_EVERY_N_FRAMES == 0:
                pct = 100.0 * original_frame / total_frames if total_frames > 0 else 0.0
                logger.info(
                    "[PROGRESS] %s frame=%s processed=%s (%.1f%%) "
                    "max_persons=%s unique_tracks=%s",
                    CAMERA_KEY,
                    original_frame,
                    stats.frames_processed,
                    pct,
                    stats.max_persons_in_frame,
                    len(seen_track_ids),
                )
    finally:
        capture.release()
        if show_window:
            cv2.destroyAllWindows()

    stats.unique_track_ids = len(seen_track_ids)
    logger.info(
        "%s robustness complete: frames_processed=%s max_persons_in_frame=%s "
        "unique_track_ids=%s (no events emitted)",
        CAMERA_KEY,
        stats.frames_processed,
        stats.max_persons_in_frame,
        stats.unique_track_ids,
    )
    return stats


def run_cli(
    output_path: Path | None = None,
    *,
    show_window: bool = False,
) -> Cam4RobustnessStats:
    """CLI: scan CAM4 and write empty JSONL files via PipelineEmitter."""
    out = output_path or (OUTPUT_DIR / "pipeline" / "pipeline_demo" / "cam4_events.jsonl")
    clip_start = parse_clip_start(CAMERA_KEY)
    with PipelineEmitter(
        output_path=out,
        store_id=DEFAULT_STORE_ID,
        clip_start_by_camera={CAMERA_KEY: clip_start},
    ) as emitter:
        stats = process_cam4_video(emitter=emitter, show_window=show_window)
        logger.info(
            "CAM4 persons_detected=%s events_written=%s",
            stats.persons_detected,
            emitter.stats.purpple_written,
        )
        return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_cli(show_window=False)
