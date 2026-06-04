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
from pipeline.config import DEFAULT_STORE_ID, OUTPUT_DIR, parse_clip_start
from pipeline.emit import EmitStats, PipelineEmitter
from pipeline.entry_exit import CAMERA_KEY as CAM3_KEY, process_cam3_video
from pipeline.queue import CAMERA_KEY as CAM5_KEY, process_cam5_video

logger = logging.getLogger(__name__)

DEMO_OUTPUT_DIR = OUTPUT_DIR / "pipeline" / "pipeline_demo"
REPORT_PATH = OUTPUT_DIR / "pipeline" / "pipeline_demo_report.txt"

CAM1_CAM2_TYPES = ("ZONE_ENTER", "ZONE_EXIT", "DWELL_COMPLETED")
CAM3_TYPES = ("ENTRY", "EXIT")
CAM5_TYPES = (
    "QUEUE_ENTER",
    "QUEUE_EXIT",
    "PAYMENT_ENTER",
    "PAYMENT_EXIT",
    "DWELL_COMPLETED",
)


@dataclass
class CameraRunResult:
    camera_key: str
    output_path: Path
    notbk_mirror_path: Path
    emitter_stats: EmitStats
    event_counts: Counter[str] = field(default_factory=Counter)
    persons_detected: int | None = None
    error: str | None = None


def count_jsonl_events(path: Path) -> Counter[str]:
    """Count NOTEBK event_type values from a JSONL file."""
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


def count_purpple_jsonl_by_type(path: Path) -> Counter[str]:
    """Count Purpple-schema event_type values (fallback if mirror missing)."""
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


def run_camera_pipeline(
    camera_key: str,
    output_name: str,
    process_fn: Callable[..., object],
) -> CameraRunResult:
    """Run one camera processor with a dedicated PipelineEmitter."""
    out_path = DEMO_OUTPUT_DIR / output_name
    clip_start = parse_clip_start(camera_key)
    result = CameraRunResult(
        camera_key=camera_key,
        output_path=out_path,
        notbk_mirror_path=out_path.with_suffix(".notbk.jsonl"),
        emitter_stats=EmitStats(),
    )

    try:
        with PipelineEmitter(
            output_path=out_path,
            store_id=DEFAULT_STORE_ID,
            clip_start_by_camera={camera_key: clip_start},
        ) as emitter:
            proc_stats = process_fn(emitter=emitter, show_window=False)
            result.emitter_stats = emitter.stats
            result.notbk_mirror_path = emitter.notbk_mirror_path
            if hasattr(proc_stats, "persons_detected"):
                result.persons_detected = int(proc_stats.persons_detected)
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        logger.exception("%s pipeline failed", camera_key)
        return result

    result.event_counts = count_jsonl_events(result.notbk_mirror_path)
    if not result.event_counts and out_path.is_file():
        result.event_counts = count_purpple_jsonl_by_type(out_path)
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
    total_notbk = 0
    total_purpple = 0
    total_errors = 0
    adaptation_errors = 0

    for result in results:
        by_camera[result.camera_key] = result.event_counts
        by_type.update(result.event_counts)
        total_notbk += result.emitter_stats.notbk_received
        total_purpple += result.emitter_stats.purpple_written
        adaptation_errors += result.emitter_stats.adaptation_errors

    lines.append("Overall")
    lines.append("-" * 50)
    lines.append(f"Total events generated (NOTEBK rows): {total_notbk}")
    lines.append(f"Total Purpple events written: {total_purpple}")
    lines.append(f"Adaptation errors: {adaptation_errors}")
    lines.append("")
    lines.append("Events by camera:")
    for camera_key in (CAM1_KEY, CAM2_KEY, CAM3_KEY, CAM4_KEY, CAM5_KEY):
        cam_total = sum(by_camera.get(camera_key, Counter()).values())
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

    lines.append("Run details")
    lines.append("-" * 50)
    for result in results:
        lines.append(f"{result.camera_key}:")
        lines.append(f"  output: {result.output_path}")
        lines.append(f"  mirror: {result.notbk_mirror_path}")
        lines.append(
            f"  emitter: received={result.emitter_stats.notbk_received} "
            f"written={result.emitter_stats.purpple_written} "
            f"errors={result.emitter_stats.adaptation_errors}"
        )
        if result.camera_key == CAM4_KEY and result.persons_detected is not None:
            lines.append(f"  persons_detected: {result.persons_detected}")
        if result.error:
            total_errors += 1
            lines.append(f"  status: FAILED — {result.error}")
        else:
            lines.append("  status: OK")
        lines.append("")

    if total_errors:
        lines.append(f"Cameras failed: {total_errors} / {len(results)}")
    else:
        lines.append("All camera pipelines completed successfully.")

    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    DEMO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    pipelines: list[tuple[str, str, Callable[..., object]]] = [
        (CAM1_KEY, "cam1_events.jsonl", process_cam1_video),
        (CAM2_KEY, "cam2_events.jsonl", process_cam2_video),
        (CAM3_KEY, "cam3_events.jsonl", process_cam3_video),
        (CAM4_KEY, "cam4_events.jsonl", process_cam4_video),
        (CAM5_KEY, "cam5_events.jsonl", process_cam5_video),
    ]

    results: list[CameraRunResult] = []
    for camera_key, output_name, process_fn in pipelines:
        logger.info("Starting %s pipeline …", camera_key)
        result = run_camera_pipeline(camera_key, output_name, process_fn)
        results.append(result)
        if result.error:
            logger.error("%s failed: %s", camera_key, result.error)
        elif camera_key == CAM4_KEY:
            logger.info(
                "%s done: persons_detected=%s events=%s",
                camera_key,
                result.persons_detected,
                sum(result.event_counts.values()),
            )
        else:
            logger.info(
                "%s done: %s events (%s Purpple written)",
                camera_key,
                sum(result.event_counts.values()),
                result.emitter_stats.purpple_written,
            )

    report = build_report(results)
    print(report)
    REPORT_PATH.write_text(report, encoding="utf-8")
    logger.info("Report saved to %s", REPORT_PATH)

    failed = [r for r in results if r.error]
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.info("Interrupted")
        raise SystemExit(130)
