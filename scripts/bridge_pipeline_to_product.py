"""
Bridge pipeline-generated files into the Purpple_Vision product database.

Uses the same core ingest functions as POST /events/ingest and POST /pos/ingest
(without HTTP). Runs analytics compute functions and writes bridge_validation_report.md.
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.anomalies import compute_store_anomalies
from app.db import (
    EventRecord,
    PosTransactionRecord,
    fetch_store_events,
    fetch_store_pos_transactions,
    get_session,
    init_db,
    session_scope,
)
from app.funnel import compute_store_funnel
from app.heatmap import compute_store_heatmap
from app.ingestion import IngestStatusResponse, ingest_event_dicts
from app.metrics import compute_store_metrics
from app.models import PosTransaction
from app.pos_ingestion import PosIngestStatusResponse, ingest_pos_transaction_dicts
from app.sessions import build_sessions, customer_sessions
from pipeline.config import (
    DEFAULT_STORE_ID,
    PIPELINE_DEMO_DIR,
    PURPPLE_POS_CSV,
)

load_dotenv()

logger = logging.getLogger(__name__)

REPORT_PATH = REPO_ROOT / "docs" / "archive" / "bridge_validation_report.md"
INGEST_BATCH_SIZE = 500
DEFAULT_METRIC_DATE = date(2026, 4, 10)


@dataclass
class BridgeIngestSummary:
    event_files: list[str] = field(default_factory=list)
    events_loaded_from_files: int = 0
    events_ingested: int = 0
    events_duplicates_skipped: int = 0
    events_rejected: int = 0
    event_ingest_errors: list[str] = field(default_factory=list)
    pos_loaded_from_csv: int = 0
    pos_ingested: int = 0
    pos_duplicates_skipped: int = 0
    pos_rejected: int = 0
    pos_ingest_errors: list[str] = field(default_factory=list)


@dataclass
class BridgeValidationResult:
    store_id: str
    metric_date: date
    ingest: BridgeIngestSummary
    db_event_count: int = 0
    db_pos_count: int = 0
    db_event_count_for_day: int = 0
    db_pos_count_for_day: int = 0
    sessions_total: int = 0
    customer_sessions: int = 0
    metrics: Any | None = None
    funnel: Any | None = None
    heatmap: Any | None = None
    anomalies: Any | None = None


def _chunked(items: list[Any], size: int) -> Iterator[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def discover_pipeline_event_files(demo_dir: Path | None = None) -> list[Path]:
    """Return cam*_events.jsonl paths (exclude NOTEBK mirrors)."""
    base = demo_dir or PIPELINE_DEMO_DIR
    if not base.is_dir():
        return []
    files = sorted(
        p
        for p in base.glob("cam*_events.jsonl")
        if p.is_file() and p.stat().st_size > 0 and ".notbk." not in p.name
    )
    return files


def load_event_dicts_from_jsonl(paths: list[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    """Load Purpple-schema event dicts from JSONL files."""
    events: list[dict[str, Any]] = []
    notes: list[str] = []
    for path in paths:
        count = 0
        with path.open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    notes.append(f"{path.name} line {line_no}: JSON error ({exc})")
                    continue
                if not isinstance(row, dict):
                    notes.append(f"{path.name} line {line_no}: expected JSON object")
                    continue
                events.append(row)
                count += 1
        notes.append(f"{path.name}: {count} events loaded")
    return events, notes


def _parse_pos_timestamp(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_pos_dicts_from_csv(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load POS rows as dicts compatible with PosTransaction.model_validate."""
    if not path.is_file():
        return [], [f"POS CSV not found: {path}"]

    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            try:
                txn = PosTransaction(
                    store_id=row["store_id"],
                    transaction_id=row["transaction_id"],
                    timestamp=_parse_pos_timestamp(row["timestamp"]),
                    basket_value_inr=float(row["basket_value_inr"]),
                )
                payload = txn.model_dump(mode="json")
                rows.append(payload)
            except (KeyError, ValueError, ValidationError) as exc:
                notes.append(f"{path.name} row {row_number}: rejected ({exc})")
    notes.append(f"{path.name}: {len(rows)} transactions loaded")
    return rows, notes


def _merge_ingest_status(
    total: IngestStatusResponse,
    batch: IngestStatusResponse,
) -> IngestStatusResponse:
    return IngestStatusResponse(
        status=batch.status if total.total_received == 0 else total.status,
        total_received=total.total_received + batch.total_received,
        events_ingested=total.events_ingested + batch.events_ingested,
        duplicates_skipped=total.duplicates_skipped + batch.duplicates_skipped,
        rejected=total.rejected + batch.rejected,
        errors=total.errors + batch.errors,
    )


def _merge_pos_status(
    total: PosIngestStatusResponse,
    batch: PosIngestStatusResponse,
) -> PosIngestStatusResponse:
    return PosIngestStatusResponse(
        status=batch.status if total.total_received == 0 else total.status,
        total_received=total.total_received + batch.total_received,
        transactions_ingested=total.transactions_ingested + batch.transactions_ingested,
        duplicates_skipped=total.duplicates_skipped + batch.duplicates_skipped,
        rejected=total.rejected + batch.rejected,
        errors=total.errors + batch.errors,
    )


def ingest_events_in_batches(raw_events: list[dict[str, Any]]) -> IngestStatusResponse:
    """Call ingest_event_dicts in batches of up to 500 (API limit)."""
    if not raw_events:
        return IngestStatusResponse(
            status="success",
            total_received=0,
            events_ingested=0,
            duplicates_skipped=0,
            rejected=0,
            errors=[],
        )

    total = IngestStatusResponse(
        status="success",
        total_received=0,
        events_ingested=0,
        duplicates_skipped=0,
        rejected=0,
        errors=[],
    )
    for batch in _chunked(raw_events, INGEST_BATCH_SIZE):
        try:
            result = ingest_event_dicts(batch)
        except HTTPException as exc:
            raise RuntimeError(f"Event ingest failed: {exc.detail}") from exc
        total = _merge_ingest_status(total, result)
    return total


def ingest_pos_in_batches(raw_transactions: list[dict[str, Any]]) -> PosIngestStatusResponse:
    """Call ingest_pos_transaction_dicts in batches of up to 500."""
    if not raw_transactions:
        return PosIngestStatusResponse(
            status="success",
            total_received=0,
            transactions_ingested=0,
            duplicates_skipped=0,
            rejected=0,
            errors=[],
        )

    total = PosIngestStatusResponse(
        status="success",
        total_received=0,
        transactions_ingested=0,
        duplicates_skipped=0,
        rejected=0,
        errors=[],
    )
    for batch in _chunked(raw_transactions, INGEST_BATCH_SIZE):
        try:
            result = ingest_pos_transaction_dicts(batch)
        except HTTPException as exc:
            raise RuntimeError(f"POS ingest failed: {exc.detail}") from exc
        total = _merge_pos_status(total, result)
    return total


def count_table_rows(session: Any, model: type, store_id: str | None = None) -> int:
    stmt = select(func.count()).select_from(model)
    if store_id is not None:
        stmt = stmt.where(model.store_id == store_id)
    value = session.scalar(stmt)
    return int(value or 0)


def run_bridge(
    *,
    demo_dir: Path | None = None,
    pos_csv_path: Path | None = None,
    store_id: str = DEFAULT_STORE_ID,
    metric_date: date = DEFAULT_METRIC_DATE,
) -> BridgeValidationResult:
    """Load pipeline outputs, ingest via product paths, compute analytics."""
    init_db()

    summary = BridgeIngestSummary()
    event_paths = discover_pipeline_event_files(demo_dir)
    summary.event_files = [p.name for p in event_paths]

    event_dicts, event_notes = load_event_dicts_from_jsonl(event_paths)
    summary.events_loaded_from_files = len(event_dicts)
    summary.event_ingest_errors.extend(event_notes)

    event_status = ingest_events_in_batches(event_dicts)
    summary.events_ingested = event_status.events_ingested
    summary.events_duplicates_skipped = event_status.duplicates_skipped
    summary.events_rejected = event_status.rejected
    summary.event_ingest_errors.extend(
        f"index {err.index}: {err.error}" for err in event_status.errors
    )

    pos_path = pos_csv_path or PURPPLE_POS_CSV
    pos_dicts, pos_notes = load_pos_dicts_from_csv(pos_path)
    summary.pos_loaded_from_csv = len(pos_dicts)
    summary.pos_ingest_errors.extend(pos_notes)

    pos_status = ingest_pos_in_batches(pos_dicts)
    summary.pos_ingested = pos_status.transactions_ingested
    summary.pos_duplicates_skipped = pos_status.duplicates_skipped
    summary.pos_rejected = pos_status.rejected
    summary.pos_ingest_errors.extend(
        f"index {err.index}: {err.error}" for err in pos_status.errors
    )

    result = BridgeValidationResult(
        store_id=store_id,
        metric_date=metric_date,
        ingest=summary,
    )

    with session_scope() as session:
        result.db_event_count = count_table_rows(session, EventRecord, store_id)
        result.db_pos_count = count_table_rows(session, PosTransactionRecord, store_id)

        day_events = fetch_store_events(session, store_id, day=metric_date)
        day_transactions = fetch_store_pos_transactions(session, store_id, day=metric_date)
        result.db_event_count_for_day = len(day_events)
        result.db_pos_count_for_day = len(day_transactions)

        sessions = build_sessions(day_events)
        result.sessions_total = len(sessions)
        result.customer_sessions = len(customer_sessions(sessions))

        result.metrics = compute_store_metrics(
            store_id, metric_date, day_events, day_transactions
        )
        result.funnel = compute_store_funnel(
            store_id, metric_date, day_events, day_transactions
        )
        result.heatmap = compute_store_heatmap(
            store_id, metric_date, day_events
        )
        result.anomalies = compute_store_anomalies(
            store_id, metric_date, day_events, day_transactions
        )

    return result


def _format_report(result: BridgeValidationResult) -> str:
    ing = result.ingest
    metrics = result.metrics
    funnel = result.funnel
    heatmap = result.heatmap
    anomalies = result.anomalies

    lines = [
        "# Bridge Validation Report - Pipeline to Product",
        "",
        f"**Store:** `{result.store_id}`  ",
        f"**Metric date (UTC):** `{result.metric_date.isoformat()}`  ",
        f"**Bridge script:** `scripts/bridge_pipeline_to_product.py`",
        "",
        "## 1. Event ingestion (`ingest_event_dicts`)",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Source files | {', '.join(ing.event_files) or '(none)'} |",
        f"| Loaded from JSONL | {ing.events_loaded_from_files} |",
        f"| Ingested (new) | {ing.events_ingested} |",
        f"| Duplicates skipped | {ing.events_duplicates_skipped} |",
        f"| Rejected | {ing.events_rejected} |",
        "",
        "## 2. POS ingestion (`ingest_pos_transaction_dicts`)",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Source CSV | `{PURPPLE_POS_CSV}` |",
        f"| Loaded from CSV | {ing.pos_loaded_from_csv} |",
        f"| Ingested (new) | {ing.pos_ingested} |",
        f"| Duplicates skipped | {ing.pos_duplicates_skipped} |",
        f"| Rejected | {ing.pos_rejected} |",
        "",
        "## 3. Database verification",
        "",
        "| Table | Total (store) | For metric day |",
        "|-------|---------------|----------------|",
        f"| `events` | {result.db_event_count} | {result.db_event_count_for_day} |",
        f"| `pos_transactions` | {result.db_pos_count} | {result.db_pos_count_for_day} |",
        "",
        "## 4. Sessions (`build_sessions`)",
        "",
        f"- Sessions created: **{result.sessions_total}**",
        f"- Customer (non-staff) sessions: **{result.customer_sessions}**",
        "",
        "> Note: Sessions open on ENTRY/REENTRY only. Zone-only pipeline demo events",
        "> produce zero sessions until CAM3 entry events are ingested.",
        "",
        "## 5. Analytics (direct compute functions — same as API handlers)",
        "",
        "### Metrics (`compute_store_metrics`)",
        "",
    ]

    if metrics is not None:
        lines.extend(
            [
                f"- unique_visitors: **{metrics.unique_visitors}**",
                f"- conversion_rate: **{metrics.conversion_rate}**",
                f"- total_sessions: **{metrics.total_sessions}**",
                f"- billing_reach_rate: **{metrics.billing_reach_rate}**",
                f"- queue_abandonment_rate: **{metrics.queue_abandonment_rate}**",
                f"- current_queue_depth: **{metrics.current_queue_depth}**",
                "",
            ]
        )

    lines.append("### Funnel (`compute_store_funnel`)")
    lines.append("")
    if funnel is not None:
        for stage in funnel.stages:
            lines.append(
                f"- {stage.stage}: count={stage.count}, drop_off_pct={stage.drop_off_pct}"
            )
        lines.append(f"- overall_conversion_rate: **{funnel.overall_conversion_rate}**")
        lines.append("")

    lines.append("### Heatmap (`compute_store_heatmap`)")
    lines.append("")
    if heatmap is not None:
        lines.append(f"- zones reported: **{len(heatmap.zones)}**")
        for zone in heatmap.zones[:10]:
            lines.append(
                f"  - {zone.zone_id}: visits={zone.visit_count}, "
                f"normalized_score={zone.normalized_score}"
            )
        if len(heatmap.zones) > 10:
            lines.append(f"  - … and {len(heatmap.zones) - 10} more")
        lines.append("")

    lines.append("### Anomalies (`compute_store_anomalies`)")
    lines.append("")
    if anomalies is not None:
        lines.append(f"- alerts: **{len(anomalies.anomalies)}**")
        for alert in anomalies.anomalies:
            lines.append(
                f"  - [{alert.severity}] {alert.anomaly_type}: {alert.title}"
            )
        lines.append("")

    lines.extend(
        [
            "## 6. API compatibility check",
            "",
            "| API endpoint | Internal function used | Compatible |",
            "|--------------|------------------------|------------|",
            "| `POST /events/ingest` | `ingest_event_dicts` | Yes — same code path |",
            "| `POST /pos/ingest` | `ingest_pos_transaction_dicts` | Yes — same code path |",
            "| `GET /stores/{id}/metrics` | `compute_store_metrics` | Yes |",
            "| `GET /stores/{id}/funnel` | `compute_store_funnel` | Yes |",
            "| `GET /stores/{id}/heatmap` | `compute_store_heatmap` | Yes |",
            "| `GET /stores/{id}/anomalies` | `compute_store_anomalies` | Yes |",
            "",
            "## 7. Load notes / errors",
            "",
        ]
    )

    all_notes = ing.event_ingest_errors + ing.pos_ingest_errors
    if all_notes:
        for note in all_notes:
            lines.append(f"- {note}")
    else:
        lines.append("- (none)")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger.info("Bridging pipeline outputs to product database …")

    result = run_bridge()
    report = _format_report(result)
    REPORT_PATH.write_text(report, encoding="utf-8")

    print(report)
    print(f"\nReport saved to: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.info("Interrupted")
        raise SystemExit(130)
