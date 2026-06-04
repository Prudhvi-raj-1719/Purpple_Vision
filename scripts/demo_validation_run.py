"""
Synthetic end-to-end validation using per-store isolated SQLite databases.

Uses:
  data/synthetic/store_1/synthetic_events_store_1.jsonl
  data/synthetic/store_1/synthetic_pos_store_1.csv
  data/synthetic/store_2/synthetic_events_store_2.jsonl
  data/synthetic/store_2/synthetic_pos_store_2.csv

Does NOT touch store_intelligence.db or cross-contaminate store DBs.

Usage:
    python scripts/demo_validation_run.py
    python scripts/demo_validation_run.py --store store_1
    python scripts/demo_validation_run.py --store all
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.demo_cleanup import (  # noqa: E402
    assert_demo_database_path,
    clean_report_files,
    delete_sqlite_database,
    force_database_url,
    resolve_engine_database_path,
)
from scripts.synthetic_paths import (  # noqa: E402
    SUPPORTED_SYNTHETIC_STORES,
    SyntheticStoreSpec,
    all_synthetic_store_specs,
    synthetic_store_spec,
)

INGEST_BATCH_SIZE = 500


@dataclass
class ValidationSummary:
    store_key: str
    store_id: str
    metric_date: date
    events_path: Path
    pos_path: Path
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
    reentry_event_count: int = 0
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
    from app.models import PosTransaction

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


def reset_validation_database(db_path: Path, *, label: str) -> Path:
    """Recreate validation DB schema; rebind SQLAlchemy engine to an isolated file."""
    import importlib

    force_database_url(db_path)
    delete_sqlite_database(db_path)

    import app.db as db_module

    importlib.reload(db_module)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_module.init_db()
    return assert_demo_database_path(db_module.engine, expected=db_path, label=label)


def ingest_events_in_batches(events: list[dict]) -> tuple[int, int, int, list[str]]:
    from app.ingestion import ingest_event_dicts

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


def run_validation_for_store(spec: SyntheticStoreSpec) -> ValidationSummary:
    import importlib

    import app.db as db_module

    database_used = reset_validation_database(
        spec.validation_db,
        label=f"demo_validation_run:{spec.store_key}",
    )
    print(f"[INFO] {spec.store_key} validation DB reset: {database_used}")

    importlib.reload(db_module)
    from app.anomalies import compute_store_anomalies
    from app.db import fetch_store_events, fetch_store_pos_transactions, get_session
    from app.funnel import compute_store_funnel
    from app.heatmap import compute_store_heatmap
    from app.metrics import compute_store_metrics
    from app.pos_correlation import converted_visitor_ids
    from app.pos_ingestion import ingest_pos_transaction_dicts
    from app.sessions import build_sessions, count_unique_visitors, customer_sessions

    summary = ValidationSummary(
        store_key=spec.store_key,
        store_id=spec.store_id,
        metric_date=spec.metric_date,
        events_path=spec.events_path,
        pos_path=spec.pos_path,
    )

    if not spec.events_path.is_file():
        summary.errors.append(f"Missing events file: {spec.events_path}")
        return summary
    if not spec.pos_path.is_file():
        summary.errors.append(f"Missing POS file: {spec.pos_path}")
        return summary

    events = load_events(spec.events_path)
    summary.events_loaded = len(events)
    summary.reentry_event_count = sum(
        1 for e in events if e.get("event_type") == "REENTRY"
    )
    ingested, duplicates, rejected, ingest_errors = ingest_events_in_batches(events)
    summary.events_ingested = ingested
    summary.events_duplicates = duplicates
    summary.events_rejected = rejected
    summary.errors.extend(ingest_errors)

    pos_rows = load_pos_rows(spec.pos_path)
    summary.pos_loaded = len(pos_rows)
    pos_status = ingest_pos_transaction_dicts(pos_rows)
    summary.pos_ingested = pos_status.transactions_ingested
    summary.pos_duplicates = pos_status.duplicates_skipped
    summary.pos_rejected = pos_status.rejected
    if pos_status.errors:
        summary.errors.extend(f"pos[{e.index}]: {e.error}" for e in pos_status.errors)

    with get_session() as session:
        event_records = fetch_store_events(session, spec.store_id, day=spec.metric_date)
        pos_records = fetch_store_pos_transactions(
            session, spec.store_id, day=spec.metric_date
        )

    sessions = build_sessions(event_records)
    customers = customer_sessions(sessions)
    summary.sessions_total = len(sessions)
    summary.sessions_customer = len(customers)
    summary.unique_visitors = count_unique_visitors(sessions)
    summary.converted_visitors = len(converted_visitor_ids(sessions, pos_records))
    summary.revenue_inr = round(sum(txn.basket_value_inr for txn in pos_records), 2)

    metrics = compute_store_metrics(
        spec.store_id, spec.metric_date, event_records, pos_records
    )
    summary.metrics = metrics.model_dump(mode="json")

    funnel = compute_store_funnel(
        spec.store_id, spec.metric_date, event_records, pos_records
    )
    summary.funnel_stages = [stage.model_dump(mode="json") for stage in funnel.stages]

    heatmap = compute_store_heatmap(spec.store_id, spec.metric_date, event_records)
    summary.heatmap_zones = len(heatmap.zones)

    anomalies = compute_store_anomalies(
        spec.store_id, spec.metric_date, event_records, pos_records
    )
    summary.anomalies_count = len(anomalies.anomalies)

    return summary


def write_report(summary: ValidationSummary, *, database_path: Path) -> None:
    spec = synthetic_store_spec(summary.store_key)
    lines: list[str] = [
        f"# Demo Validation Report — {summary.store_key}",
        "",
        "**Purpose:** Synthetic ENTRY-based dataset to verify sessions, funnel, metrics, and analytics.",
        "",
        f"**Store key:** `{summary.store_key}`  ",
        f"**Store ID:** `{summary.store_id}`  ",
        f"**Metric date (UTC):** `{summary.metric_date.isoformat()}`  ",
        "",
        "**Clean run:** YES",
        "",
        "**Database actually used:**",
        f"`{database_path}`",
        "",
        f"**Events file:** `{summary.events_path.relative_to(REPO_ROOT)}`  ",
        f"**POS file:** `{summary.pos_path.relative_to(REPO_ROOT)}`  ",
        "",
        "> Other store validation DBs are **not modified** by this run.",
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
        f"- Customer sessions: **{summary.sessions_customer}**",
        f"- Total sessions: **{summary.sessions_total}**",
        f"- Unique visitors: **{summary.unique_visitors}**",
        f"- REENTRY events in fixture: **{summary.reentry_event_count}**",
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
            f"- Revenue (INR): **{summary.revenue_inr:,.2f}**",
            f"- Anomalies: **{summary.anomalies_count}**",
            "",
            "## 5. Dashboard verification",
            "",
            "```powershell",
            f'$env:DATABASE_URL = "sqlite:///{spec.validation_db.resolve().as_posix()}"',
            f'$env:DEFAULT_METRIC_DATE = "{summary.metric_date.isoformat()}"',
            "uvicorn app.main:app --host 0.0.0.0 --port 8000",
            "streamlit run dashboard/streamlit_app.py --server.port 8501",
            "```",
            "",
        ]
    )

    if summary.errors:
        lines.extend(["## Errors", ""])
        lines.extend(f"- {err}" for err in summary.errors)
        lines.append("")

    passed = (
        summary.events_rejected == 0
        and summary.sessions_customer >= 100
        and summary.unique_visitors >= 100
        and summary.reentry_event_count >= 20
        and float(summary.metrics.get("conversion_rate", 0.0)) >= 0.60
    )
    lines.append(
        "## Verdict\n\n"
        + (
            "**PASS** — Per-store synthetic validation succeeded."
            if passed
            else "**FAIL** — See counts/errors above."
        )
    )

    body = "\n".join(lines) + "\n"
    clean_report_files(spec.report_paths)
    for report_path in spec.report_paths:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(body, encoding="utf-8")


def print_summary(summary: ValidationSummary, *, database_path: Path) -> None:
    print(f"\n=== {summary.store_key} ===")
    print(f"Validation DB: {database_path}")
    print(f"Events ingested : {summary.events_ingested}/{summary.events_loaded}")
    print(f"POS ingested    : {summary.pos_ingested}/{summary.pos_loaded}")
    print(f"Sessions        : {summary.sessions_customer}")
    print(f"Unique visitors : {summary.unique_visitors}")
    print(f"REENTRY events  : {summary.reentry_event_count}")
    print(f"Converted       : {summary.converted_visitors}")
    print(f"Conversion rate : {summary.metrics.get('conversion_rate', 0.0):.2%}")
    print(f"Queue abandon   : {summary.metrics.get('queue_abandonment_rate', 0.0):.2%}")
    print(f"Revenue (INR)   : {summary.revenue_inr:,.2f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run synthetic validation per store")
    parser.add_argument(
        "--store",
        choices=[*SUPPORTED_SYNTHETIC_STORES, "all"],
        default="all",
    )
    args = parser.parse_args()

    specs = (
        all_synthetic_store_specs()
        if args.store == "all"
        else (synthetic_store_spec(args.store),)
    )

    exit_code = 0
    for spec in specs:
        print(f"Events: {spec.events_path}")
        print(f"POS: {spec.pos_path}")
        summary = run_validation_for_store(spec)
        from app.db import engine

        database_used = resolve_engine_database_path(engine)
        assert_demo_database_path(
            engine,
            expected=spec.validation_db,
            label=f"demo_validation_run:{spec.store_key}",
        )
        write_report(summary, database_path=database_used)
        print_summary(summary, database_path=database_used)
        print(f"Report: {spec.report_paths[0]}")
        if summary.errors or summary.sessions_customer < 100:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
