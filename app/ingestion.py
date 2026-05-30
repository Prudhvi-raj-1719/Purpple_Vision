"""Event batch ingestion with idempotency and partial-success handling."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.db import EventRecord, event_to_record, is_database_available, session_scope
from app.models import Event, IngestErrorDetail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["ingestion"])


class EventIngestPayload(BaseModel):
    """
    Batch ingest envelope with the same limits as EventIngestRequest.

    Events are provided as raw dicts so each record can be validated
    individually, enabling partial-success responses.
    """

    model_config = ConfigDict(extra="forbid")

    events: list[dict[str, Any]] = Field(min_length=1, max_length=500)


class IngestStatusResponse(BaseModel):
    """POST /events/ingest response."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(
        description="Overall result: success, partial, or failed.",
    )
    total_received: int = Field(ge=0, description="Number of events in the request batch.")
    events_ingested: int = Field(ge=0, description="New events persisted to the database.")
    duplicates_skipped: int = Field(ge=0, description="Events skipped because event_id exists.")
    rejected: int = Field(ge=0, description="Events rejected due to validation errors.")
    errors: list[IngestErrorDetail] = Field(default_factory=list)


def _validate_batch_size(events: list[Any]) -> None:
    """Enforce the same batch limits as EventIngestRequest."""
    if len(events) < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="events must contain at least 1 item",
        )
    if len(events) > 500:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="events must contain at most 500 items",
        )


def _resolve_status(ingested: int, duplicates: int, rejected: int, total: int) -> str:
    if rejected == 0 and (ingested > 0 or duplicates > 0):
        return "success"
    if ingested > 0 or duplicates > 0:
        return "partial"
    if rejected == total:
        return "failed"
    return "partial"


@router.post(
    "/ingest",
    response_model=IngestStatusResponse,
    summary="Ingest behavioural events",
    description=(
        "Accepts a batch of up to 500 events. Each event is validated against the "
        "challenge schema. Valid events are stored idempotently by event_id. "
        "Malformed events are reported individually without failing the entire batch."
    ),
    responses={
        503: {"description": "Database unavailable"},
        422: {"description": "Invalid batch structure"},
    },
)
def ingest_events(
    payload: EventIngestPayload,
    request: Request,
) -> IngestStatusResponse:
    """
    Ingest a batch of events with partial-success semantics.

    Batch size is validated on the envelope; each event is validated as an
    Event model individually so one bad record does not reject the entire batch.
    """
    if not is_database_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        )

    result = ingest_event_dicts(payload.events)
    request.state.event_count = result.total_received
    return result


def ingest_event_dicts(raw_events: list[Any]) -> IngestStatusResponse:
    """
    Core ingest logic operating on raw event dictionaries.

    Separated for testing and future pipeline integrations.
    """
    _validate_batch_size(raw_events)

    total_received = len(raw_events)
    events_ingested = 0
    duplicates_skipped = 0
    rejected = 0
    errors: list[IngestErrorDetail] = []

    valid_records: list[tuple[int, EventRecord]] = []

    for index, raw_event in enumerate(raw_events):
        try:
            event = Event.model_validate(raw_event)
            valid_records.append((index, event_to_record(event)))
        except ValidationError as exc:
            rejected += 1
            event_id = raw_event.get("event_id") if isinstance(raw_event, dict) else None
            errors.append(
                IngestErrorDetail(
                    index=index,
                    event_id=str(event_id) if event_id is not None else None,
                    error="; ".join(error["msg"] for error in exc.errors()),
                )
            )

    try:
        with session_scope() as session:
            for index, record in valid_records:
                existing = session.get(EventRecord, record.event_id)
                if existing is not None:
                    duplicates_skipped += 1
                    continue
                session.add(record)
                events_ingested += 1
    except SQLAlchemyError as exc:
        logger.exception("Database error during event ingest")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error while ingesting events",
        ) from exc

    return IngestStatusResponse(
        status=_resolve_status(
            events_ingested, duplicates_skipped, rejected, total_received
        ),
        total_received=total_received,
        events_ingested=events_ingested,
        duplicates_skipped=duplicates_skipped,
        rejected=rejected,
        errors=errors,
    )
