"""
CAM2 validation — live tracking window and recorded MP4 with zone + shopper overlays.

Writes:
  data/outputs/pipeline/pipeline_demo_store_N/cam2_tracking.mp4

Usage:
    python scripts/cam2_validation.py
    python scripts/cam2_validation.py --show
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cam2_processor import process_cam2_video  # noqa: E402
from pipeline.config import refresh_store_config  # noqa: E402
from pipeline.shelf_preview import shelf_tracking_output_path  # noqa: E402
from pipeline.store_config import get_store_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="CAM2 shelf validation (zones + tracking video)")
    parser.add_argument("--show", action="store_true", help="Open live OpenCV window")
    parser.add_argument(
        "--store",
        default=os.getenv("PURPPLE_STORE", "store_1"),
        help="Store key (default: PURPPLE_STORE or store_1)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    refresh_store_config(args.store)
    cfg = get_store_config(args.store)

    stats = process_cam2_video(show_window=args.show, store=cfg)
    tracking = shelf_tracking_output_path(cfg.pipeline_output_dir, "CAM2")
    print(f"Tracking video: {tracking}")
    print(
        f"Aisle enters={stats.zone_enter} exits={stats.zone_exit} "
        f"dwells={stats.dwell_completed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
