"""
Regenerate cam3_tracking.mp4 and cam5_tracking.mp4 for store_2 (no full demo_runner).

Re-processes footage and appends to existing JSONL via PipelineEmitter (idempotent
UUIDs on re-bridge). Safe to run after demo_runner when only tracking MP4s are missing.

Usage:
    $env:PURPPLE_STORE = "store_2"
    python scripts/regenerate_store2_tracking_videos.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cam3_processor import process_cam3_video
from pipeline.cam5_processor import process_cam5_video
from pipeline.config import emitter_clip_start_by_camera, refresh_store_config
from pipeline.emit import PipelineEmitter
from pipeline.store_config import get_store_config

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = get_store_config("store_2")
    refresh_store_config("store_2")

    cam3_out = cfg.pipeline_output_dir / "cam3_events.jsonl"
    clip_starts = emitter_clip_start_by_camera("CAM3", store=cfg)
    logger.info("CAM3 → %s + cam3_tracking.mp4", cam3_out)
    with PipelineEmitter(
        output_path=cam3_out,
        store_id=cfg.store_id,
        clip_start_by_camera=clip_starts,
    ) as emitter:
        stats = process_cam3_video(emitter=emitter, store=cfg)
        logger.info("CAM3 entries=%s exits=%s", stats.entry_count, stats.exit_count)

    cam5_out = cfg.pipeline_output_dir / "cam5_events.jsonl"
    cam5_start = emitter_clip_start_by_camera("CAM5", store=cfg)
    logger.info("CAM5 → %s + cam5_tracking.mp4", cam5_out)
    with PipelineEmitter(
        output_path=cam5_out,
        store_id=cfg.store_id,
        clip_start_by_camera=cam5_start,
    ) as emitter:
        stats = process_cam5_video(emitter=emitter, store=cfg)
        logger.info("CAM5 events=%s", stats.total)

    logger.info("Done. Refresh Streamlit store2_real (install FFmpeg for playback).")


if __name__ == "__main__":
    main()
