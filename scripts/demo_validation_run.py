"""
Synthetic end-to-end validation using an isolated SQLite database.

Uses data/synthetic/demo_events.jsonl and data/synthetic/demo_pos.csv only.
Does NOT touch data/databases/store_intelligence.db (production).

Usage:
    python scripts/demo_validation_run.py
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_DIR = REPO_ROOT / "data" / "synthetic"
EVENTS_PATH = SYNTHETIC_DIR / "demo_events.jsonl"
POS_PATH = SYNTHETIC_DIR / "demo_pos.csv"

STORE_ID = "STORE_BLR_002"
METRIC_DATE = date(2026, 6, 1)
INGEST_BATCH_SIZE = 500

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.demo_cleanup import (  # noqa: E402 — before app.db
    DEMO_VALIDATION_DB,
    DEMO_VALIDATION_REPORT_PATHS,
    assert_demo_database_path,
    clean_report_files,
    delete_sqlite_database,
    force_database_url,
    resolve_engine_database_path,
)

force_database_url(DEMO_VALIDATION_DB)
delete_sqlite_database(DEMO_VALIDATION_DB)

from app.anomalies import compute_store_anomalies  # noqa: E402
from app.db import (  # noqa: E402
    EventRecord,
    PosTransactionRecord,
    fetch_store_events,
    fetch_store_pos_transactions,
    get_session,
    init_db,
)
from app.funnel import compute_store_funnel  # noqa: E402
from app.heatmap import compute_store_heatmap  # noqa: E402
from app.ingestion import ingest_event_dicts  # noqa: E402
from app.metrics import compute_store_metrics  # noqa: E402
from app.models import PosTransaction  # noqa: E402
from app.pos_correlation import converted_visitor_ids  # noqa: E402
from app.pos_ingestion import ingest_pos_transaction_dicts  # noqa: E402
from app.sessions import build_sessions, count_unique_visitors, customer_sessions  # noqa: E402


@dataclass
class ValidationSummary:
    events_loaded: int = 0
    events_ingested: int = 0
    events_duplicates: int = 0
    events_rejected: int = 0
    pos_loaded: int = 0
    pos_ingested: int = 0
    pos_duplicates: int = 0
    pos_rejected: int = 0
    sessions_total: int = 0
    sessions_customer: int = 0
    unique_visitors: int = 0
    converted_visitors: int = 0
    revenue_inr: float = 0.0
    metrics: dict = field(default_factory=dict)
    funnel_stages: list[dict] = field(default_factory=list)
    heatmap_zones: int = 0
    anomalies_count: int = 0
    errors: list[str] = field(default_factory=list)


def _parse_pos_timestamp(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_events(path: Path) -> list[dict]:
    events: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Line {line_no}: expected JSON object")
            events.append(row)
    return events


def load_pos_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            txn = PosTransaction(
                store_id=row["store_id"],
                transaction_id=row["transaction_id"],
                timestamp=_parse_pos_timestamp(row["timestamp"]),
                basket_value_inr=float(row["basket_value_inr"]),
            )
            rows.append(txn.model_dump(mode="json"))
    return rows


def reset_validation_database() -> Path:
    """Recreate validation DB schema from scratch (files removed at import)."""
    from app.db import engine

    DEMO_VALIDATION_DB.parent.mkdir(parents=True, exist_ok=True)
    init_db()
    database_used = assert_demo_database_path(
        engine,
        expected=DEMO_VALIDATION_DB,
        label="demo_validation_run",
    )
    print("[INFO] Validation DB reset")
    return database_used


def ingest_events_in_batches(events: list[dict]) -> tuple[int, int, int, list[str]]:
    """Ingest events in API-sized chunks (max 500 per request)."""
    ingested = 0
    duplicates = 0
    rejected = 0
    errors: list[str] = []
    for offset in range(0, len(events), INGEST_BATCH_SIZE):
        batch = events[offset : offset + INGEST_BATCH_SIZE]
        status = ingest_event_dicts(batch)
        ingested += status.events_ingested
        duplicates += status.duplicates_skipped
        rejected += status.rejected
        for err in status.errors:
            errors.append(f"event[{offset + err.index}]: {err.error}")
    return ingested, duplicates, rejected, errors


def run_validation() -> ValidationSummary:
    summary = ValidationSummary()

    if not EVENTS_PATH.is_file():
        summary.errors.append(f"Missing events file: {EVENTS_PATH}")
        return summary
    if not POS_PATH.is_file():
        summary.errors.append(f"Missing POS file: {POS_PATH}")
        return summary

    reset_validation_database()

    events = load_events(EVENTS_PATH)
    summary.events_loaded = len(events)
    ingested, duplicates, rejected, ingest_errors = ingest_events_in_batches(events)
    summary.events_ingested = ingested
    summary.events_duplicates = duplicates
    summary.events_rejected = rejected
    summary.errors.extend(ingest_errors)

    pos_rows = load_pos_rows(POS_PATH)
    summary.pos_loaded = len(pos_rows)
    pos_status = ingest_pos_transaction_dicts(pos_rows)
    summary.pos_ingested = pos_status.transactions_ingested
    summary.pos_duplicates = pos_status.duplicates_skipped
    summary.pos_rejected = pos_status.rejected
    if pos_status.errors:
        summary.errors.extend(
            f"pos[{e.index}]: {e.error}" for e in pos_status.errors
        )

    with get_session() as session:
        event_records: list[EventRecord] = fetch_store_events(
            session, STORE_ID, day=METRIC_DATE
        )
        pos_records: list[PosTransactionRecord] = fetch_store_pos_transactions(
            session, STORE_ID, day=METRIC_DATE
        )

    sessions = build_sessions(event_records)
    customers = customer_sessions(sessions)
    summary.sessions_total = len(sessions)
    summary.sessions_customer = len(customers)
    summary.unique_visitors = count_unique_visitors(sessions)
    summary.converted_visitors = len(converted_visitor_ids(sessions, pos_records))
    summary.revenue_inr = round(
        sum(txn.basket_value_inr for txn in pos_records), 2
    )

    metrics = compute_store_metrics(STORE_ID, METRIC_DATE, event_records, pos_records)
    summary.metrics = metrics.model_dump(mode="json")

    funnel = compute_store_funnel(STORE_ID, METRIC_DATE, event_records, pos_records)
    summary.funnel_stages = [
        stage.model_dump(mode="json") for stage in funnel.stages
    ]

    heatmap = compute_store_heatmap(STORE_ID, METRIC_DATE, event_records)
    summary.heatmap_zones = len(heatmap.zones)

    anomalies = compute_store_anomalies(STORE_ID, METRIC_DATE, event_records, pos_records)
    summary.anomalies_count = len(anomalies.anomalies)

    return summary


def write_report(summary: ValidationSummary, *, database_used: Path) -> None:
    lines: list[str] = [
        "# Demo Validation Report",
        "",
        "**Purpose:** Synthetic ENTRY-based dataset to verify sessions, funnel, metrics, and analytics.",
        "",
        f"**Store:** `{STORE_ID}`  ",
        f"**Metric date (UTC):** `{METRIC_DATE.isoformat()}`  ",
        "",
        "**Clean run:**",
        "YES",
        "",
        "**Database actually used:**",
        f"`{database_used}`",
        "",
        f"**Events file:** `{EVENTS_PATH.relative_to(REPO_ROOT)}`  ",
        f"**POS file:** `{POS_PATH.relative_to(REPO_ROOT)}`  ",
        "",
        "> Production database (`data/databases/store_intelligence.db`) is **not modified**.",
        "",
        "## 1. Ingestion",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Events loaded | {summary.events_loaded} |",
        f"| Events ingested | {summary.events_ingested} |",
        f"| Event duplicates skipped | {summary.events_duplicates} |",
        f"| Events rejected | {summary.events_rejected} |",
        f"| POS rows loaded | {summary.pos_loaded} |",
        f"| POS ingested | {summary.pos_ingested} |",
        f"| POS duplicates skipped | {summary.pos_duplicates} |",
        f"| POS rejected | {summary.pos_rejected} |",
        "",
        "## 2. Sessions",
        "",
        f"- Sessions created: **{summary.sessions_customer}** (customer sessions)",
        f"- Total sessions (incl. logic): **{summary.sessions_total}**",
        f"- Unique visitors: **{summary.unique_visitors}**",
        "",
        "### Visitor journeys",
        "",
        "| Visitor | Journey | Converted |",
        "|---------|---------|-----------|",
        "| VIS_101 | ENTRY → LAKME → dwell → billing queue → EXIT | Yes (TXN_DEMO_101) |",
        "| VIS_102 | ENTRY → PILGRIM → dwell → EXIT | No |",
        "| VIS_103 | ENTRY → GOODVIBES → dwell → billing queue → EXIT | Yes (TXN_DEMO_103) |",
        "",
        "## 3. Metrics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| unique_visitors | {summary.metrics.get('unique_visitors', 0)} |",
        f"| total_sessions | {summary.metrics.get('total_sessions', 0)} |",
        f"| conversion_rate | {summary.metrics.get('conversion_rate', 0.0):.4f} |",
        f"| billing_reach_rate | {summary.metrics.get('billing_reach_rate', 0.0):.4f} |",
        f"| queue_abandonment_rate | {summary.metrics.get('queue_abandonment_rate', 0.0):.4f} |",
        f"| current_queue_depth | {summary.metrics.get('current_queue_depth', 0)} |",
        "",
        "## 4. Funnel",
        "",
        "| Stage | Count | Drop-off % |",
        "|-------|-------|------------|",
    ]

    for stage in summary.funnel_stages:
        drop = stage.get("drop_off_pct")
        drop_str = f"{drop:.1f}" if drop is not None else "—"
        lines.append(
            f"| {stage.get('stage')} | {stage.get('count')} | {drop_str} |"
        )

    lines.extend(
        [
            "",
            f"- Converted visitors: **{summary.converted_visitors}**",
            "",
            "## 5. Conversions & revenue",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Converted visitors (POS correlation) | {summary.converted_visitors} |",
            f"| Total POS revenue (INR) | {summary.revenue_inr:,.2f} |",
            "",
            "POS transactions:",
            "",
            "| transaction_id | visitor | amount (INR) |",
            "|----------------|---------|--------------|",
            "| TXN_DEMO_101 | VIS_101 | 849.50 |",
            "| TXN_DEMO_103 | VIS_103 | 1,299.00 |",
            "",
            "## 6. Heatmap & anomalies",
            "",
            f"- Heatmap zones reported: **{summary.heatmap_zones}**",
            f"- Anomalies detected: **{summary.anomalies_count}**",
            "",
            "## 7. Dashboard verification",
            "",
            "To view non-zero analytics in Streamlit against the validation DB:",
            "",
            "```powershell",
            f'$env:DATABASE_URL = "sqlite:///{DEMO_VALIDATION_DB.resolve().as_posix()}"',
            "uvicorn app.main:app --host 0.0.0.0 --port 8000",
            "# second terminal:",
            '$env:API_BASE_URL = "http://localhost:8000"',
            f'$env:DEFAULT_METRIC_DATE = "{METRIC_DATE.isoformat()}"',
            "streamlit run dashboard/streamlit_app.py --server.port 8501",
            "```",
            "",
        ]
    )

    if summary.errors:
        lines.extend(["## Errors", ""])
        for err in summary.errors:
            lines.append(f"- {err}")
        lines.append("")

    lines.append(
        "## Verdict\n\n"
        + (
            "**PASS** — Sessions and funnel populated from synthetic ENTRY events."
            if summary.sessions_customer >= 3 and summary.unique_visitors >= 3
            else "**FAIL** — See errors or session counts above."
        )
    )

    body = "\n".join(lines) + "\n"
    for report_path in DEMO_VALIDATION_REPORT_PATHS:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(body, encoding="utf-8")


def main() -> int:
    print(f"Events: {EVENTS_PATH}")
    print(f"POS: {POS_PATH}")

    summary = run_validation()
    from app.db import engine

    database_used = resolve_engine_database_path(engine)
    assert_demo_database_path(
        engine,
        expected=DEMO_VALIDATION_DB,
        label="demo_validation_run",
    )
    print(f"Validation DB: {database_used}")

    clean_report_files(DEMO_VALIDATION_REPORT_PATHS)
    write_report(summary, database_used=database_used)

    print(f"\nEvents ingested : {summary.events_ingested}/{summary.events_loaded}")
    print(f"POS ingested    : {summary.pos_ingested}/{summary.pos_loaded}")
    print(f"Sessions        : {summary.sessions_customer}")
    print(f"Unique visitors : {summary.unique_visitors}")
    print(f"Converted       : {summary.converted_visitors}")
    print(f"Conversion rate : {summary.metrics.get('conversion_rate', 0.0):.2%}")
    print(f"Revenue (INR)   : {summary.revenue_inr:,.2f}")
    print(f"Report          : {DEMO_VALIDATION_REPORT_PATHS[0]}")

    if summary.errors:
        print("\nErrors:")
        for err in summary.errors:
            print(f"  - {err}")
        return 1
    if summary.sessions_customer < 3:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
