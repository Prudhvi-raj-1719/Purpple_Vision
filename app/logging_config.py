"""Structured logging configuration and request logging middleware."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("store_intelligence.access")

_STORE_ID_PATH_PATTERN = re.compile(r"^/stores/([^/]+)")


class JsonLogFormatter(logging.Formatter):
    """Emit one JSON object per log line for production log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        structured = getattr(record, "structured", None)
        if isinstance(structured, dict):
            payload.update(structured)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Configure root logging from environment variables."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = os.getenv("LOG_FORMAT", "json").lower()

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(log_level)

    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root.addHandler(handler)


def extract_store_id(path: str) -> str | None:
    """Parse store_id from /stores/{store_id}/... paths."""
    match = _STORE_ID_PATH_PATTERN.match(path)
    if match is None:
        return None
    return match.group(1)


def log_request(
    *,
    trace_id: str,
    endpoint: str,
    latency_ms: float,
    status_code: int,
    store_id: str | None = None,
    event_count: int | None = None,
) -> None:
    """Write a structured access log entry."""
    payload = {
        "trace_id": trace_id,
        "endpoint": endpoint,
        "latency_ms": round(latency_ms, 2),
        "status_code": status_code,
    }
    if store_id is not None:
        payload["store_id"] = store_id
    if event_count is not None:
        payload["event_count"] = event_count

    record = logging.LogRecord(
        name=logger.name,
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="request_completed",
        args=(),
        exc_info=None,
    )
    record.structured = payload  # type: ignore[attr-defined]
    logger.handle(record)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with trace_id, latency, and optional store_id."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        trace_id = str(uuid.uuid4())
        request.state.trace_id = trace_id
        start = time.perf_counter()

        response = await call_next(request)

        latency_ms = (time.perf_counter() - start) * 1000.0
        store_id = extract_store_id(request.url.path)
        event_count = getattr(request.state, "event_count", None)
        log_request(
            trace_id=trace_id,
            endpoint=request.url.path,
            latency_ms=latency_ms,
            status_code=response.status_code,
            store_id=store_id,
            event_count=event_count,
        )
        response.headers["X-Trace-Id"] = trace_id
        return response
