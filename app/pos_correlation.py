"""POS transaction correlation for session conversion."""

from __future__ import annotations

from datetime import timedelta
from typing import Sequence

from app.db import PosTransactionRecord
from app.sessions import VisitorSession

POS_CORRELATION_WINDOW = timedelta(minutes=5)


def is_session_converted(
    session: VisitorSession,
    transactions: Sequence[PosTransactionRecord],
) -> bool:
    """
    Return True when a non-staff session reached billing and billing activity
    occurred within 5 minutes before a POS transaction (challenge PDF rule).
    """
    if session.is_staff or not session.reached_billing:
        return False

    billing_at = session.billing_activity_at
    if billing_at is None:
        return False

    for txn in transactions:
        if txn.store_id != session.store_id:
            continue
        window_start = txn.timestamp - POS_CORRELATION_WINDOW
        if window_start <= billing_at <= txn.timestamp:
            return True
    return False


def converted_visitor_ids(
    sessions: Sequence[VisitorSession],
    transactions: Sequence[PosTransactionRecord],
) -> set[str]:
    """Distinct non-staff visitor_ids with at least one converted session."""
    converted: set[str] = set()
    for session in sessions:
        if session.is_staff:
            continue
        if is_session_converted(session, transactions):
            converted.add(session.visitor_id)
    return converted
