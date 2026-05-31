"""CAM1 shelf zone-engagement pipeline (YOLO11m + ByteTrack + polygon overlap)."""

from __future__ import annotations

import logging
from pathlib import Path

from pipeline.config import (
    CAM1_ZONES,
    CAMERA_VIDEO_FILES,
    DEFAULT_STORE_ID,
    OUTPUT_DIR,
    parse_clip_start,
)
from pipeline.dwell import ZoneEngagementStats, process_zone_engagement_video
from pipeline.emit import PipelineEmitter

logger = logging.getLogger(__name__)

CAMERA_KEY = "CAM1"


def process_cam1_video(
    video_path: Path | None = None,
    *,
    emitter: PipelineEmitter | None = None,
    show_window: bool = False,
) -> ZoneEngagementStats:
    """Process CAM1 footage and emit ZONE_ENTER / ZONE_EXIT / DWELL_COMPLETED."""
    path = video_path or CAMERA_VIDEO_FILES[CAMERA_KEY]
    return process_zone_engagement_video(
        camera_key=CAMERA_KEY,
        zone_definitions=CAM1_ZONES,
        video_path=path,
        emitter=emitter,
        show_window=show_window,
        window_title="CAM1 Zone Engagement",
    )


def run_cli(
    output_path: Path | None = None,
    *,
    show_window: bool = False,
) -> None:
    """CLI: process CAM1 and write Purpple-schema JSONL via event_adapter."""
    out = output_path or (OUTPUT_DIR / "cam1_events.jsonl")
    clip_start = parse_clip_start(CAMERA_KEY)
    with PipelineEmitter(
        output_path=out,
        store_id=DEFAULT_STORE_ID,
        clip_start_by_camera={CAMERA_KEY: clip_start},
    ) as emitter:
        process_cam1_video(emitter=emitter, show_window=show_window)
        logger.info(
            "Wrote %s Purpple events (%s NOTEBK rows, %s adaptation errors)",
            emitter.stats.purpple_written,
            emitter.stats.notbk_received,
            emitter.stats.adaptation_errors,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_cli(show_window=False)
