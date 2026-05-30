"""Bootstrap database from sample_events.jsonl and pos_transactions.csv."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from app.db import (
    EventRecord,
    PosTransactionRecord,
    event_to_record,
    get_session,
    init_db,
    pos_transaction_to_record,
)
from app.models import Event, PosTransaction

load_dotenv()

DEFAULT_SAMPLE_EVENTS_PATH = Path("./data/sample_events.jsonl")
DEFAULT_POS_TRANSACTIONS_PATH = Path("./data/pos_transactions.csv")


def resolve_path(env_var: str, default: Path) -> Path:
    """Resolve a dataset path from environment or default."""
    raw = os.getenv(env_var)
    return Path(raw) if raw else default


def load_events_jsonl(path: Path) -> tuple[int, int, int]:
    """
    Load events from JSONL into SQLite.

    Returns (inserted, skipped_duplicates, rejected).
    """
    if not path.is_file():
        print(f"Events file not found, skipping: {path}")
        return 0, 0, 0

    inserted = 0
    skipped = 0
    rejected = 0

    session = get_session()
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                    event = Event.model_validate(raw)
                    record = event_to_record(event)
                except (json.JSONDecodeError, ValidationError) as exc:
                    rejected += 1
                    print(f"Rejected event line {line_number}: {exc}")
                    continue

                existing = session.get(EventRecord, record.event_id)
                if existing is not None:
                    skipped += 1
                    continue

                session.add(record)
                inserted += 1

        session.commit()
    finally:
        session.close()

    return inserted, skipped, rejected


def _parse_pos_timestamp(value: str) -> datetime:
    """Parse POS CSV timestamps to UTC-aware datetimes."""
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_pos_csv(path: Path) -> tuple[int, int, int]:
    """
    Load POS transactions from CSV into SQLite.

    Returns (inserted, skipped_duplicates, rejected).
    """
    if not path.is_file():
        print(f"POS file not found, skipping: {path}")
        return 0, 0, 0

    inserted = 0
    skipped = 0
    rejected = 0

    session = get_session()
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row_number, row in enumerate(reader, start=2):
                try:
                    transaction = PosTransaction(
                        store_id=row["store_id"],
                        transaction_id=row["transaction_id"],
                        timestamp=_parse_pos_timestamp(row["timestamp"]),
                        basket_value_inr=float(row["basket_value_inr"]),
                    )
                    record = pos_transaction_to_record(transaction)
                except (KeyError, ValueError, ValidationError) as exc:
                    rejected += 1
                    print(f"Rejected POS row {row_number}: {exc}")
                    continue

                existing = session.get(PosTransactionRecord, record.transaction_id)
                if existing is not None:
                    skipped += 1
                    continue

                session.add(record)
                inserted += 1

        session.commit()
    finally:
        session.close()

    return inserted, skipped, rejected


def seed_database(
    *,
    events_path: Path | None = None,
    pos_path: Path | None = None,
) -> dict[str, dict[str, int]]:
    """Seed SQLite from dataset files; safe to run multiple times."""
    init_db()

    events_file = events_path or resolve_path("SAMPLE_EVENTS_PATH", DEFAULT_SAMPLE_EVENTS_PATH)
    pos_file = pos_path or resolve_path("POS_TRANSACTIONS_PATH", DEFAULT_POS_TRANSACTIONS_PATH)

    event_inserted, event_skipped, event_rejected = load_events_jsonl(events_file)
    pos_inserted, pos_skipped, pos_rejected = load_pos_csv(pos_file)

    summary = {
        "events": {
            "inserted": event_inserted,
            "duplicates_skipped": event_skipped,
            "rejected": event_rejected,
        },
        "pos_transactions": {
            "inserted": pos_inserted,
            "duplicates_skipped": pos_skipped,
            "rejected": pos_rejected,
        },
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Seed SQLite from sample_events.jsonl and pos_transactions.csv",
    )
    parser.add_argument(
        "--events",
        type=Path,
        default=None,
        help="Path to sample_events.jsonl (overrides SAMPLE_EVENTS_PATH)",
    )
    parser.add_argument(
        "--pos",
        type=Path,
        default=None,
        help="Path to pos_transactions.csv (overrides POS_TRANSACTIONS_PATH)",
    )
    args = parser.parse_args(argv)

    summary = seed_database(events_path=args.events, pos_path=args.pos)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
