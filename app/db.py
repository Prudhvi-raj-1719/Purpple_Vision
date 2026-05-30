"""SQLite database setup, SQLAlchemy 2.0 ORM models, and session management."""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    event,
    func,
    inspect,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_DATABASE_URL = "sqlite:///./data/store_intelligence.db"


def get_database_url() -> str:
    """Resolve SQLite URL from environment with a safe local default."""
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def _ensure_sqlite_directory(database_url: str) -> None:
    """
    Create parent directory for file-based SQLite URLs.

    Relative paths like sqlite:///./data/store.db map to ./data/store.db.
    """
    if not database_url.startswith("sqlite:"):
        return

    # Strip driver prefix and optional host segment (/// or ////)
    path_part = database_url.split("sqlite:", 1)[1]
    for prefix in ("////", "///", "//"):
        if path_part.startswith(prefix):
            path_part = path_part[len(prefix) :]
            break

    if path_part in (":memory:", "/:memory:"):
        return

    db_path = Path(path_part)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path

    db_path.parent.mkdir(parents=True, exist_ok=True)


def _create_engine(database_url: str) -> Engine:
    """Build a sync SQLAlchemy engine tuned for SQLite."""
    connect_args: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(
        database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        future=True,
    )

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


DATABASE_URL = get_database_url()
_ensure_sqlite_directory(DATABASE_URL)
engine = _create_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# ORM base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy models."""


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------


class EventRecord(Base):
    """
    Persisted behavioural event from the detection pipeline.

    Idempotency is enforced via unique event_id (ingest skips duplicates).
    """

    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    camera_id: Mapped[str] = mapped_column(String(64), nullable=False)
    visitor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    zone_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    dwell_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_staff: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_events_store_timestamp", "store_id", "timestamp"),
        Index("ix_events_store_type_timestamp", "store_id", "event_type", "timestamp"),
        Index("ix_events_store_staff", "store_id", "is_staff"),
    )

    @property
    def metadata_dict(self) -> dict[str, Any]:
        """Deserialize metadata JSON column."""
        return json.loads(self.metadata_json)

    @metadata_dict.setter
    def metadata_dict(self, value: dict[str, Any]) -> None:
        self.metadata_json = json.dumps(value, separators=(",", ":"))


class PosTransactionRecord(Base):
    """
    Point-of-sale transaction for conversion correlation.

    Schema mirrors pos_transactions.csv from the challenge dataset.
    """

    __tablename__ = "pos_transactions"

    transaction_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    basket_value_inr: Mapped[float] = mapped_column(Float, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_pos_store_timestamp", "store_id", "timestamp"),
    )


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


def get_session() -> Session:
    """Create a new database session. Caller must close it."""
    return SessionLocal()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """
    Provide a transactional scope around a series of operations.

    Commits on success, rolls back on exception, always closes the session.
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency generator (for use in Phase 1+ routes).

    Yields a session and ensures it is closed after the request.
    """
    session = get_session()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Initialization & health helpers
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create all tables if they do not exist."""
    _ensure_sqlite_directory(get_database_url())
    Base.metadata.create_all(bind=engine)


def drop_all_tables() -> None:
    """Drop all tables — intended for tests only."""
    Base.metadata.drop_all(bind=engine)


def is_database_available() -> bool:
    """Return True when the database connection is reachable."""
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False


def tables_exist() -> bool:
    """Return True when application tables have been created."""
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    required = {EventRecord.__tablename__, PosTransactionRecord.__tablename__}
    return required.issubset(existing)


# ---------------------------------------------------------------------------
# Mapping helpers (ORM ↔ Pydantic)
# ---------------------------------------------------------------------------


def event_to_record(event: Any) -> EventRecord:
    """
    Convert a validated Pydantic Event into an EventRecord ORM instance.

    Accepts app.models.Event without importing at module level to avoid cycles.
    """
    metadata = event.metadata.model_dump(exclude_none=True)
    return EventRecord(
        event_id=str(event.event_id),
        store_id=event.store_id,
        camera_id=event.camera_id,
        visitor_id=event.visitor_id,
        event_type=event.event_type.value,
        timestamp=event.timestamp,
        zone_id=event.zone_id,
        dwell_ms=event.dwell_ms,
        is_staff=event.is_staff,
        confidence=event.confidence,
        metadata_json=json.dumps(metadata, separators=(",", ":")),
    )


def pos_transaction_to_record(transaction: Any) -> PosTransactionRecord:
    """Convert a validated Pydantic PosTransaction into an ORM instance."""
    return PosTransactionRecord(
        transaction_id=transaction.transaction_id,
        store_id=transaction.store_id,
        timestamp=transaction.timestamp,
        basket_value_inr=transaction.basket_value_inr,
    )


def utc_day_bounds(day: date) -> tuple[datetime, datetime]:
    """Return inclusive UTC start and exclusive end for a calendar day."""
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    end = datetime.combine(day, time.max, tzinfo=timezone.utc).replace(
        microsecond=999999
    )
    return start, end


def fetch_store_events(
    session: Session,
    store_id: str,
    *,
    day: date | None = None,
) -> list[EventRecord]:
    """Load store events ordered by timestamp, optionally filtered to one UTC day."""
    stmt = select(EventRecord).where(EventRecord.store_id == store_id)
    if day is not None:
        day_start, day_end = utc_day_bounds(day)
        stmt = stmt.where(
            EventRecord.timestamp >= day_start,
            EventRecord.timestamp <= day_end,
        )
    stmt = stmt.order_by(EventRecord.timestamp)
    return list(session.scalars(stmt).all())


def fetch_store_pos_transactions(
    session: Session,
    store_id: str,
    *,
    day: date | None = None,
) -> list[PosTransactionRecord]:
    """Load POS transactions for a store, optionally filtered to one UTC day."""
    stmt = select(PosTransactionRecord).where(PosTransactionRecord.store_id == store_id)
    if day is not None:
        day_start, day_end = utc_day_bounds(day)
        stmt = stmt.where(
            PosTransactionRecord.timestamp >= day_start,
            PosTransactionRecord.timestamp <= day_end,
        )
    stmt = stmt.order_by(PosTransactionRecord.timestamp)
    return list(session.scalars(stmt).all())


def fetch_store_feed_statuses(session: Session) -> list[tuple[str, datetime | None, datetime | None]]:
    """
    Return per-store (store_id, last_event_at, last_ingested_at).

    last_event_at is the latest event timestamp; last_ingested_at is the latest
    ingest time used for STALE_FEED lag detection.
    """
    stmt = (
        select(
            EventRecord.store_id,
            func.max(EventRecord.timestamp),
            func.max(EventRecord.ingested_at),
        )
        .group_by(EventRecord.store_id)
        .order_by(EventRecord.store_id)
    )
    rows = session.execute(stmt).all()
    return [(row[0], row[1], row[2]) for row in rows]
