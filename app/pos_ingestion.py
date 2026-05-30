"""POS transaction batch ingestion with idempotency and partial-success handling."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.db import (
    PosTransactionRecord,
    is_database_available,
    pos_transaction_to_record,
    session_scope,
)
from app.models import PosIngestErrorDetail, PosIngestStatusResponse, PosTransaction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pos", tags=["pos"])


class PosIngestPayload(BaseModel):
    """Batch ingest envelope; transactions validated individually for partial success."""

    model_config = ConfigDict(extra="forbid")

    transactions: list[dict[str, Any]] = Field(min_length=1, max_length=500)


def _validate_batch_size(transactions: list[Any]) -> None:
    if len(transactions) < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="transactions must contain at least 1 item",
        )
    if len(transactions) > 500:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="transactions must contain at most 500 items",
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
    response_model=PosIngestStatusResponse,
    summary="Ingest POS transactions",
    description=(
        "Accepts a batch of up to 500 POS transactions. Each row is validated "
        "against the challenge schema. Valid rows are stored idempotently by "
        "transaction_id. Malformed rows are reported individually."
    ),
    responses={
        503: {"description": "Database unavailable"},
        422: {"description": "Invalid batch structure"},
    },
)
def ingest_pos_transactions(
    payload: PosIngestPayload,
    request: Request,
) -> PosIngestStatusResponse:
    """Ingest POS transactions with partial-success semantics."""
    if not is_database_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        )

    result = ingest_pos_transaction_dicts(payload.transactions)
    request.state.event_count = result.total_received
    return result


def ingest_pos_transaction_dicts(
    raw_transactions: list[Any],
) -> PosIngestStatusResponse:
    """Core POS ingest logic operating on raw transaction dictionaries."""
    _validate_batch_size(raw_transactions)

    total_received = len(raw_transactions)
    transactions_ingested = 0
    duplicates_skipped = 0
    rejected = 0
    errors: list[PosIngestErrorDetail] = []

    valid_records: list[tuple[int, PosTransactionRecord]] = []

    for index, raw_txn in enumerate(raw_transactions):
        try:
            txn = PosTransaction.model_validate(raw_txn)
            valid_records.append((index, pos_transaction_to_record(txn)))
        except ValidationError as exc:
            rejected += 1
            txn_id = raw_txn.get("transaction_id") if isinstance(raw_txn, dict) else None
            errors.append(
                PosIngestErrorDetail(
                    index=index,
                    transaction_id=str(txn_id) if txn_id is not None else None,
                    error="; ".join(error["msg"] for error in exc.errors()),
                )
            )

    try:
        with session_scope() as session:
            for index, record in valid_records:
                existing = session.get(PosTransactionRecord, record.transaction_id)
                if existing is not None:
                    duplicates_skipped += 1
                    continue
                session.add(record)
                transactions_ingested += 1
    except SQLAlchemyError as exc:
        logger.exception("Database error during POS ingest")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error while ingesting POS transactions",
        ) from exc

    return PosIngestStatusResponse(
        status=_resolve_status(
            transactions_ingested, duplicates_skipped, rejected, total_received
        ),
        total_received=total_received,
        transactions_ingested=transactions_ingested,
        duplicates_skipped=duplicates_skipped,
        rejected=rejected,
        errors=errors,
    )
