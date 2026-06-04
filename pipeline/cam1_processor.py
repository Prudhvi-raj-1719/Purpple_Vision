"""CAM1 shelf zone-engagement pipeline (YOLO11m + ByteTrack + polygon overlap)."""

from __future__ import annotations

import logging
from pathlib import Path

from pipeline.config import parse_clip_start, refresh_store_config
from pipeline.dwell import ZoneEngagementStats, process_zone_engagement_video
from pipeline.emit import PipelineEmitter
from pipeline.shelf_preview import shelf_tracking_output_path
from pipeline.store_config import (
    StoreConfig,
    resolve_store_config,
    zones_as_legacy_dict,
)

logger = logging.getLogger(__name__)

CAMERA_KEY = "CAM1"


def process_cam1_video(
    video_path: Path | None = None,
    *,
    emitter: PipelineEmitter | None = None,
    show_window: bool = False,
    store: StoreConfig | None = None,
) -> ZoneEngagementStats:
    """Process CAM1 footage and emit ZONE_ENTER / ZONE_EXIT / DWELL_COMPLETED."""
    cfg = resolve_store_config(store)
    if not cfg.cam1.enabled:
        raise RuntimeError(f"{cfg.store_key}: CAM1 is disabled in cam1.json")

    path = video_path or cfg.videos.video_path(CAMERA_KEY)
    if path is None:
        raise FileNotFoundError(f"{cfg.store_key}: no CAM1 video configured")

    tracking_path = shelf_tracking_output_path(cfg.pipeline_output_dir, CAMERA_KEY)
    return process_zone_engagement_video(
        camera_key=CAMERA_KEY,
        zone_definitions=zones_as_legacy_dict(cfg.cam1.zones),
        video_path=path,
        emitter=emitter,
        show_window=show_window,
        window_title=f"{cfg.display_name} CAM1 Zone Engagement",
        process_every_n=cfg.cam1.detection.process_every_n_frames,
        annotated_video_path=tracking_path,
        min_overlap_pct=cfg.cam1.overlap.min_overlap_pct,
    )


def run_cli(
    output_path: Path | None = None,
    *,
    show_window: bool = False,
    store: StoreConfig | None = None,
) -> None:
    """CLI: process CAM1 and write Purpple-schema JSONL via event_adapter."""
    cfg = resolve_store_config(store)
    refresh_store_config(cfg.store_key)
    out = output_path or (cfg.pipeline_output_dir / "cam1_events.jsonl")
    clip_start = parse_clip_start(CAMERA_KEY, store=cfg)
    with PipelineEmitter(
        output_path=out,
        store_id=cfg.store_id,
        clip_start_by_camera={CAMERA_KEY: clip_start},
    ) as emitter:
        process_cam1_video(emitter=emitter, show_window=show_window, store=cfg)
        logger.info(
            "Wrote %s events (%s adaptation errors)",
            emitter.stats.events_written,
            emitter.stats.adaptation_errors,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_cli(show_window=False)
