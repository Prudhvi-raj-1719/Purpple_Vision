"""
End-to-end demo: run CAM1, CAM2, CAM3, CAM4 (robustness), and CAM5 pipelines.

Orchestrates existing processors only (no business-logic changes).
Writes a summary report to data/outputs/pipeline/pipeline_demo_report.txt.
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cam1_processor import CAMERA_KEY as CAM1_KEY, process_cam1_video
from pipeline.cam2_processor import CAMERA_KEY as CAM2_KEY, process_cam2_video
from pipeline.cam4_processor import CAMERA_KEY as CAM4_KEY, process_cam4_video
from pipeline.config import (
    DEFAULT_STORE_ID,
    OUTPUT_DIR,
    emitter_clip_start_by_camera,
    get_active_store,
)
from pipeline.emit import EmitStats, PipelineEmitter
from pipeline.cam3_processor import CAMERA_KEY as CAM3_KEY, process_cam3_video
from pipeline.cam5_processor import CAMERA_KEY as CAM5_KEY, process_cam5_video

logger = logging.getLogger(__name__)

DEMO_OUTPUT_DIR = OUTPUT_DIR / "pipeline" / "pipeline_demo"
REPORT_PATH = OUTPUT_DIR / "pipeline" / "pipeline_demo_report.txt"

CAM1_CAM2_TYPES = ("ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL")
CAM3_TYPES = ("ENTRY", "EXIT", "REENTRY")
CAM5_TYPES = (
    "BILLING_QUEUE_JOIN",
    "BILLING_QUEUE_ABANDON",
    "ZONE_ENTER",
    "ZONE_EXIT",
    "ZONE_DWELL",
)


@dataclass
class CameraRunResult:
    camera_key: str
    output_path: Path
    emitter_stats: EmitStats
    event_counts: Counter[str] = field(default_factory=Counter)
    persons_detected: int | None = None
    error: str | None = None


def count_jsonl_events(path: Path) -> Counter[str]:
    """Count challenge-schema event_type values from a JSONL file."""
    counts: Counter[str] = Counter()
    if not path.is_file():
        return counts
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_type = row.get("event_type")
            if event_type:
                counts[str(event_type)] += 1
    return counts


def demo_camera_pipelines() -> list[tuple[str, str, Callable[..., object]]]:
    """Cameras to run for the active store."""
    cfg = get_active_store()
    candidates = [
        (CAM1_KEY, "cam1_events.jsonl", process_cam1_video),
        (CAM2_KEY, "cam2_events.jsonl", process_cam2_video),
        (CAM3_KEY, "cam3_events.jsonl", process_cam3_video),
        (CAM4_KEY, "cam4_events.jsonl", process_cam4_video),
        (CAM5_KEY, "cam5_events.jsonl", process_cam5_video),
    ]
    return [item for item in candidates if cfg.is_pipeline_camera_runnable(item[0])]


def run_camera_pipeline(
    camera_key: str,
    output_name: str,
    process_fn: Callable[..., object],
) -> CameraRunResult:
    """Run one camera processor with a dedicated PipelineEmitter."""
    out_path = DEMO_OUTPUT_DIR / output_name
    clip_start_by_camera = emitter_clip_start_by_camera(camera_key)
    result = CameraRunResult(
        camera_key=camera_key,
        output_path=out_path,
        emitter_stats=EmitStats(),
    )

    try:
        with PipelineEmitter(
            output_path=out_path,
            store_id=DEFAULT_STORE_ID,
            clip_start_by_camera=clip_start_by_camera,
        ) as emitter:
            proc_stats = process_fn(emitter=emitter, show_window=False)
            result.emitter_stats = emitter.stats
            if hasattr(proc_stats, "persons_detected"):
                result.persons_detected = int(proc_stats.persons_detected)
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        logger.exception("%s pipeline failed", camera_key)
        return result

    result.event_counts = count_jsonl_events(out_path)
    return result


def format_cam4_robustness_block(lines: list[str], result: CameraRunResult) -> None:
    """Report CAM4 detection-only metrics (no business events)."""
    persons = result.persons_detected if result.persons_detected is not None else 0
    events = sum(result.event_counts.values())
    status = f"FAILED — {result.error}" if result.error else "OK"
    lines.append("CAM4:")
    lines.append(f"  Persons detected: {persons}")
    lines.append(f"  Events generated: {events}")
    lines.append(f"  Status: {status}")
    lines.append("")


def format_type_block(
    lines: list[str],
    camera_label: str,
    type_names: tuple[str, ...],
    counts: Counter[str],
) -> None:
    lines.append(f"{camera_label}:")
    for name in type_names:
        lines.append(f"  {name}: {counts.get(name, 0)}")
    other = sum(
        count for key, count in counts.items() if key not in type_names
    )
    if other:
        lines.append(f"  (other): {other}")
    lines.append("")


def build_report(results: list[CameraRunResult]) -> str:
    lines: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines.append("Purpple_Vision Pipeline Demo Report")
    lines.append("=" * 50)
    lines.append(f"Generated: {now}")
    lines.append(f"Repo: {REPO_ROOT}")
    lines.append(f"Demo outputs: {DEMO_OUTPUT_DIR}")
    lines.append("")

    by_camera: dict[str, Counter[str]] = {}
    by_type: Counter[str] = Counter()
    total_events = 0
    adaptation_errors = 0

    for result in results:
        by_camera[result.camera_key] = result.event_counts
        by_type.update(result.event_counts)
        total_events += result.emitter_stats.events_written
        adaptation_errors += result.emitter_stats.adaptation_errors

    lines.append("Overall")
    lines.append("-" * 50)
    lines.append(f"Total events written: {total_events}")
    lines.append(f"Adaptation errors: {adaptation_errors}")
    lines.append("")
    lines.append("Events by camera:")
    for camera_key in (CAM1_KEY, CAM2_KEY, CAM3_KEY, CAM4_KEY, CAM5_KEY):
        cam_total = sum(by_camera.get(camera_key, Counter()).values())
        if cam_total or any(r.camera_key == camera_key for r in results):
            lines.append(f"  {camera_key}: {cam_total}")
    lines.append("")
    lines.append("Events by type (all cameras):")
    for event_type, count in sorted(by_type.items()):
        lines.append(f"  {event_type}: {count}")
    lines.append("")

    lines.append("Per-camera breakdown")
    lines.append("-" * 50)
    lines.append("")

    cam1 = by_camera.get(CAM1_KEY, Counter())
    format_type_block(lines, "CAM1", CAM1_CAM2_TYPES, cam1)

    cam2 = by_camera.get(CAM2_KEY, Counter())
    format_type_block(lines, "CAM2", CAM1_CAM2_TYPES, cam2)

    cam3 = by_camera.get(CAM3_KEY, Counter())
    format_type_block(lines, "CAM3", CAM3_TYPES, cam3)

    cam4_result = next((r for r in results if r.camera_key == CAM4_KEY), None)
    if cam4_result is not None:
        format_cam4_robustness_block(lines, cam4_result)

    cam5 = by_camera.get(CAM5_KEY, Counter())
    format_type_block(lines, "CAM5", CAM5_TYPES, cam5)

    lines.append("Output files")
    lines.append("-" * 50)
    for result in results:
        status = "OK" if not result.error else f"FAILED ({result.error})"
        lines.append(f"  {result.camera_key}: {result.output_path.name} [{status}]")
        lines.append(
            f"    emitter: written={result.emitter_stats.events_written} "
            f"adapt_errors={result.emitter_stats.adaptation_errors}"
        )
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    DEMO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results = [
        run_camera_pipeline(cam_key, output_name, process_fn)
        for cam_key, output_name, process_fn in demo_camera_pipelines()
    ]

    report = build_report(results)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nReport saved to: {REPORT_PATH}")


if __name__ == "__main__":
    main()
