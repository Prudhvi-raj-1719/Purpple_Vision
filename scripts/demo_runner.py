"""
One-command demo runner for the complete Store Intelligence workflow.

Goal: orchestrate existing modules end-to-end without changing business logic.

Pipeline:
  0) Reset active store intelligence DB (store_N_intelligence.db), clean pipeline outputs
  1) CAM1 processor
  2) CAM2 processor
  3) CAM3 processor (retail entry/exit via cam3_processor)
  4) CAM4 processor (robustness — detection only, no events)
  5) CAM5 processor (billing queue via cam5_processor)
  5) POS loader (aggregate Brigade CSV -> Purpple POS CSV)
  6) Purchase matching (offline)
  7) Bridge pipeline outputs -> store intelligence DB (ingest + analytics compute)
  8) Synthetic analytics validation (store_1 + store_2 validation DBs subprocess)

Outputs:
  - demo_run_report.md (repo root)
  - docs/reports/demo_run_report.md
  - prints STORE INTELLIGENCE DEMO SUMMARY

Usage:
    python scripts/demo_runner.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.demo_cleanup import (  # noqa: E402 — before app.db
    AGGREGATED_TRANSACTIONS_CSV,
    AGGREGATED_TRANSACTIONS_JSON,
    DEMO_RUN_REPORT_PATHS,
    assert_demo_database_path,
    clean_directory_files,
    clean_notbk_mirror_files,
    clean_report_files,
    delete_file_if_exists,
    delete_sqlite_database_for_cctv_run,
    force_database_url,
    intelligence_database_path,
    resolve_engine_database_path,
)

from pipeline.cam1_processor import CAMERA_KEY as CAM1_KEY, process_cam1_video  # noqa: E402
from pipeline.cam2_processor import CAMERA_KEY as CAM2_KEY, process_cam2_video  # noqa: E402
from pipeline.cam4_processor import CAMERA_KEY as CAM4_KEY, process_cam4_video  # noqa: E402
from pipeline.config import (  # noqa: E402
    DEFAULT_STORE_ID,
    OUTPUT_DIR,
    PIPELINE_DEMO_DIR,
    PURCHASE_MATCHES_JSON,
    PURPPLE_POS_CSV,
    emitter_clip_start_by_camera,
    get_active_store,
)
from pipeline.emit import EmitStats, PipelineEmitter  # noqa: E402
from pipeline.cam3_processor import CAMERA_KEY as CAM3_KEY, process_cam3_video  # noqa: E402
from pipeline.cam5_processor import CAMERA_KEY as CAM5_KEY, process_cam5_video  # noqa: E402
from pipeline.pos_loader import AggregationSummary, run_cli as run_pos_loader  # noqa: E402
from pipeline.purchase_matching import MatchingStats, run_cli as run_purchase_matching  # noqa: E402


@dataclass
class SyntheticValidationRun:
    exit_code: int
    events_ingested: int | None = None
    pos_ingested: int | None = None
    sessions: int | None = None
    visitors: int | None = None
    conversion_rate: float | None = None
    revenue_inr: float | None = None
    anomalies: int | None = None
    stdout: str = ""


def _init_intelligence_database(*, store_key: str, intelligence_db: Path) -> Path:
    """Reset schema on the active store intelligence DB; return verified path."""
    import importlib

    force_database_url(intelligence_db)
    delete_sqlite_database_for_cctv_run(
        intelligence_db,
        active_store_key=store_key,
    )

    import app.db as db_module

    importlib.reload(db_module)

    intelligence_db.parent.mkdir(parents=True, exist_ok=True)
    db_module.init_db()
    return assert_demo_database_path(
        db_module.engine,
        expected=intelligence_db,
        label="demo_runner",
    )


def _clean_pipeline_outputs() -> None:
    clean_directory_files(PIPELINE_DEMO_DIR)
    clean_notbk_mirror_files(PIPELINE_DEMO_DIR)
    print("[INFO] Pipeline outputs cleaned")


def _clean_pos_outputs() -> None:
    for path in (
        AGGREGATED_TRANSACTIONS_CSV,
        AGGREGATED_TRANSACTIONS_JSON,
        PURPPLE_POS_CSV,
    ):
        delete_file_if_exists(path)
    print("[INFO] POS outputs cleaned")


def _demo_camera_pipelines() -> list[tuple[str, str, Callable[..., object]]]:
    """Cameras to run for the active store (skips disabled or footage-less cameras)."""
    cfg = get_active_store()
    candidates: list[tuple[str, str, Callable[..., object]]] = [
        (CAM1_KEY, "cam1_events.jsonl", process_cam1_video),
        (CAM2_KEY, "cam2_events.jsonl", process_cam2_video),
        (CAM3_KEY, "cam3_events.jsonl", process_cam3_video),
        (CAM4_KEY, "cam4_events.jsonl", process_cam4_video),
        (CAM5_KEY, "cam5_events.jsonl", process_cam5_video),
    ]
    runnable = [item for item in candidates if cfg.is_pipeline_camera_runnable(item[0])]
    skipped = [item[0] for item in candidates if not cfg.is_pipeline_camera_runnable(item[0])]
    if skipped:
        print(f"[INFO] Skipping cameras for {cfg.store_key}: {', '.join(skipped)}")
    return runnable


def _clean_purchase_matching_outputs() -> None:
    delete_file_if_exists(PURCHASE_MATCHES_JSON)
    print("[INFO] Purchase matching outputs cleaned")


@dataclass
class CameraRun:
    camera_key: str
    output_path: Path
    emitter_stats: EmitStats = field(default_factory=EmitStats)
    event_counts: Counter[str] = field(default_factory=Counter)
    error: str | None = None
    elapsed_s: float = 0.0
    persons_detected: int | None = None


def _count_jsonl_event_types(path: Path) -> Counter[str]:
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


def _run_camera(
    camera_key: str,
    output_name: str,
    process_fn: Callable[..., object],
) -> CameraRun:
    out_path = PIPELINE_DEMO_DIR / output_name
    result = CameraRun(
        camera_key=camera_key,
        output_path=out_path,
    )

    t0 = time.perf_counter()
    try:
        clip_start_by_camera = emitter_clip_start_by_camera(camera_key)
        with PipelineEmitter(
            output_path=out_path,
            store_id=DEFAULT_STORE_ID,
            clip_start_by_camera=clip_start_by_camera,
        ) as emitter:
            proc_stats = process_fn(emitter=emitter, show_window=False)
            result.emitter_stats = emitter.stats
            if hasattr(proc_stats, "persons_detected"):
                result.persons_detected = int(proc_stats.persons_detected)
    except Exception as exc:  # noqa: BLE001 (demo orchestration)
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.elapsed_s = time.perf_counter() - t0

    result.event_counts = _count_jsonl_event_types(result.output_path)
    return result


def _format_inr(value: float) -> str:
    return f"{value:,.2f}"


def _write_report(
    *,
    store_key: str,
    database_used: Path,
    camera_runs: list[CameraRun],
    pos_summary: AggregationSummary | None,
    matching_stats: MatchingStats | None,
    matching_path: Path | None,
    bridge: Any | None,
    synthetic: SyntheticValidationRun | None,
    errors: list[str],
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines: list[str] = [
        "# Demo Run Report",
        "",
        f"**Generated:** {now}  ",
        f"**Store key:** `{store_key}`  ",
        f"**Store ID:** `{DEFAULT_STORE_ID}`  ",
        f"**Pipeline output dir:** `{PIPELINE_DEMO_DIR}`  ",
        "",
        "**Clean run:**",
        "YES",
        "",
        "**Intelligence database (real CCTV):**",
        f"`{database_used}`",
        "",
        "This report is generated by `scripts/demo_runner.py` and orchestrates the complete Store Intelligence workflow.",
        "",
        "## 1. Camera pipelines (events generated)",
        "",
        "| Camera | Status | Events written | Adapt errors | Output | Elapsed (s) |",
        "|--------|--------|----------------|-------------|--------|-------------|",
    ]

    total_events = 0
    total_adapt_errors = 0
    by_type: Counter[str] = Counter()
    for run in camera_runs:
        status = "OK" if not run.error else f"FAILED ({run.error})"
        lines.append(
            "| {cam} | {status} | {written} | {err} | `{out}` | {elapsed:.1f} |".format(
                cam=run.camera_key,
                status=status,
                written=run.emitter_stats.events_written,
                err=run.emitter_stats.adaptation_errors,
                out=run.output_path.relative_to(REPO_ROOT),
                elapsed=run.elapsed_s,
            )
        )
        total_events += run.emitter_stats.events_written
        total_adapt_errors += run.emitter_stats.adaptation_errors
        by_type.update(run.event_counts)

    lines.extend(
        [
            "",
            f"- Total events written: **{total_events}**",
            f"- Adaptation errors: **{total_adapt_errors}**",
            "",
            "Event types (all cameras):",
            "",
            "```",
            *[f"{k}: {v}" for k, v in sorted(by_type.items())],
            "```",
            "",
        ]
    )

    cam4_runs = [r for r in camera_runs if r.camera_key == CAM4_KEY]
    if cam4_runs:
        lines.extend(["### CAM4 robustness (detection only)", ""])
        for run in cam4_runs:
            persons = run.persons_detected if run.persons_detected is not None else 0
            events = sum(run.event_counts.values())
            status = f"FAILED ({run.error})" if run.error else "OK"
            lines.extend(
                [
                    "CAM4:",
                    f"- Persons detected: **{persons}**",
                    f"- Events generated: **{events}**",
                    f"- Status: **{status}**",
                    "",
                ]
            )

    lines.extend(["## 2. POS loader", ""])
    if pos_summary is None:
        lines.append("- POS loader not run or failed.")
    else:
        lines.extend(
            [
                f"- Source CSV: `{pos_summary.source_csv}`",
                f"- Line items: **{pos_summary.line_items}**",
                f"- Invoices: **{pos_summary.invoices}**",
                f"- Total revenue (INR): **{_format_inr(pos_summary.total_revenue_inr)}**",
                f"- Purpple POS CSV: `{(pos_summary.purpple_csv or PURPPLE_POS_CSV)}`",
            ]
        )

    lines.extend(["", "## 3. Purchase matching (offline)", ""])
    if matching_stats is None:
        lines.append("- Purchase matching not run or failed.")
    else:
        lines.extend(
            [
                f"- Total invoices: **{matching_stats.total_invoices}**",
                f"- Matched invoices: **{matching_stats.matched_invoices}**",
                f"- Unmatched invoices: **{matching_stats.unmatched_invoices}**",
                f"- Output: `{matching_path}`" if matching_path else "- Output: (unknown)",
            ]
        )

    lines.extend(
        ["", "## 4. Bridge pipeline → intelligence DB (ingest + analytics)", ""]
    )
    if bridge is None or bridge.metrics is None:
        lines.append("- Bridge validation not run or failed.")
    else:
        m = bridge.metrics
        anomalies_count = len(bridge.anomalies.anomalies) if bridge.anomalies else 0
        lines.extend(
            [
                f"- Metric date: `{bridge.metric_date.isoformat()}`",
                f"- Events ingested (new): **{bridge.ingest.events_ingested}**",
                f"- POS ingested (new): **{bridge.ingest.pos_ingested}**",
                f"- Sessions created: **{bridge.sessions_total}**",
                f"- Visitors: **{m.unique_visitors}**",
                f"- Revenue (INR): **{_format_inr(float(getattr(m, 'total_revenue_inr', 0.0)))}**",
                f"- Conversion rate: **{float(m.conversion_rate):.4f}**",
                f"- Matches (offline): **{matching_stats.matched_invoices if matching_stats else 0}**",
                f"- Anomalies: **{anomalies_count}**",
            ]
        )

    lines.extend(["", "## 5. Synthetic analytics validation (isolated)", ""])
    if synthetic is None:
        lines.append("- Synthetic validation not run or failed.")
    else:
        lines.extend(
            [
                f"- Exit code: **{synthetic.exit_code}**",
                f"- Events ingested: **{synthetic.events_ingested if synthetic.events_ingested is not None else '—'}**",
                f"- POS ingested: **{synthetic.pos_ingested if synthetic.pos_ingested is not None else '—'}**",
                f"- Sessions: **{synthetic.sessions if synthetic.sessions is not None else '—'}**",
                f"- Visitors: **{synthetic.visitors if synthetic.visitors is not None else '—'}**",
                f"- Revenue (INR): **{_format_inr(synthetic.revenue_inr) if synthetic.revenue_inr is not None else '—'}**",
                f"- Conversion rate: **{synthetic.conversion_rate:.4f}**"
                if synthetic.conversion_rate is not None
                else "- Conversion rate: **—**",
                f"- Anomalies: **{synthetic.anomalies if synthetic.anomalies is not None else '—'}**",
            ]
        )

    if errors:
        lines.extend(["", "## Errors", ""])
        lines.extend([f"- {e}" for e in errors])

    body = "\n".join(lines) + "\n"
    for report_path in DEMO_RUN_REPORT_PATHS:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(body, encoding="utf-8")


def main() -> int:
    cfg = get_active_store()
    intelligence_db = intelligence_database_path(cfg)
    database_used = _init_intelligence_database(
        store_key=cfg.store_key,
        intelligence_db=intelligence_db,
    )
    print(f"[INFO] Active store: {cfg.store_key}")
    print(f"[INFO] Intelligence DB reset: {database_used}")

    _clean_pipeline_outputs()

    PIPELINE_DEMO_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "pos").mkdir(parents=True, exist_ok=True)

    errors: list[str] = []

    camera_pipelines = _demo_camera_pipelines()
    camera_runs: list[CameraRun] = []
    for cam_key, output_name, fn in camera_pipelines:
        run = _run_camera(cam_key, output_name, fn)
        camera_runs.append(run)
        if run.error:
            errors.append(f"{cam_key} failed: {run.error}")

    _clean_pos_outputs()
    pos_summary: AggregationSummary | None = None
    try:
        pos_summary = run_pos_loader()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"POS loader failed: {type(exc).__name__}: {exc}")

    _clean_purchase_matching_outputs()
    matching_stats: MatchingStats | None = None
    matching_path: Path | None = None
    try:
        _, matching_stats, matching_path = run_purchase_matching(demo_dir=PIPELINE_DEMO_DIR)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Purchase matching failed: {type(exc).__name__}: {exc}")

    from app.db import engine as bridge_engine
    from scripts.bridge_pipeline_to_product import BridgeValidationResult, run_bridge

    assert_demo_database_path(
        bridge_engine,
        expected=intelligence_db,
        label="demo_runner bridge",
    )

    metric_date = date.fromisoformat(cfg.pos_sale_date)
    bridge_result: BridgeValidationResult | None = None
    try:
        bridge_result = run_bridge(
            demo_dir=PIPELINE_DEMO_DIR,
            store_id=cfg.store_id,
            metric_date=metric_date,
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Bridge failed: {type(exc).__name__}: {exc}")

    database_used = resolve_engine_database_path(bridge_engine)

    synthetic: SyntheticValidationRun | None = None
    try:
        script = REPO_ROOT / "scripts" / "demo_validation_run.py"
        completed = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        synthetic = SyntheticValidationRun(
            exit_code=int(completed.returncode),
            stdout=completed.stdout + completed.stderr,
        )
        for line in (completed.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("Events ingested"):
                parts = line.split(":", 1)[-1].strip().split("/", 1)[0].strip()
                synthetic.events_ingested = int(parts)
            elif line.startswith("POS ingested"):
                parts = line.split(":", 1)[-1].strip().split("/", 1)[0].strip()
                synthetic.pos_ingested = int(parts)
            elif line.startswith("Sessions"):
                synthetic.sessions = int(line.split(":", 1)[-1].strip())
            elif line.startswith("Unique visitors"):
                synthetic.visitors = int(line.split(":", 1)[-1].strip())
            elif line.startswith("Conversion rate"):
                raw = line.split(":", 1)[-1].strip().replace("%", "")
                synthetic.conversion_rate = float(raw) / 100.0
            elif line.startswith("Revenue (INR)"):
                raw = line.split(":", 1)[-1].strip().replace(",", "")
                synthetic.revenue_inr = float(raw)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Synthetic validation failed: {type(exc).__name__}: {exc}")

    clean_report_files(DEMO_RUN_REPORT_PATHS)
    _write_report(
        store_key=cfg.store_key,
        database_used=database_used,
        camera_runs=camera_runs,
        pos_summary=pos_summary,
        matching_stats=matching_stats,
        matching_path=matching_path,
        bridge=bridge_result,
        synthetic=synthetic,
        errors=errors,
    )

    events_generated = sum(r.emitter_stats.purpple_written for r in camera_runs)
    sessions_created = (
        int(getattr(bridge_result, "sessions_total", 0)) if bridge_result else 0
    )
    visitors = (
        int(getattr(getattr(bridge_result, "metrics", None), "unique_visitors", 0))
        if bridge_result and bridge_result.metrics
        else 0
    )
    revenue_inr = (
        float(getattr(getattr(bridge_result, "metrics", None), "total_revenue_inr", 0.0))
        if bridge_result and bridge_result.metrics
        else 0.0
    )
    conversion_rate = (
        float(getattr(getattr(bridge_result, "metrics", None), "conversion_rate", 0.0))
        if bridge_result and bridge_result.metrics
        else 0.0
    )
    matches = int(getattr(matching_stats, "matched_invoices", 0)) if matching_stats else 0
    anomalies = (
        len(bridge_result.anomalies.anomalies)
        if bridge_result and bridge_result.anomalies
        else 0
    )

    print("\n" + "=" * 33)
    print("STORE INTELLIGENCE DEMO SUMMARY")
    print("=" * 33)
    print(f"Events generated: {events_generated}")
    print(f"Sessions created: {sessions_created}")
    print(f"Visitors: {visitors}")
    print(f"Revenue (INR): {_format_inr(revenue_inr)}")
    print(f"Conversion rate: {conversion_rate:.4f}")
    print(f"Matches: {matches}")
    print(f"Anomalies: {anomalies}")
    print(f"Database used: {database_used}")
    print(f"\nReport: {DEMO_RUN_REPORT_PATHS[0]}")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
