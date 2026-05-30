"""FastAPI application entry point, routing, and middleware."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.db import init_db
from app.health import router as health_router
from app.ingestion import router as ingestion_router
from app.anomalies import router as anomalies_router
from app.funnel import router as funnel_router
from app.heatmap import router as heatmap_router
from app.logging_config import RequestLoggingMiddleware, configure_logging
from app.metrics import router as metrics_router
from app.models import ErrorResponse

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application startup and shutdown lifecycle."""
    init_db()
    logger.info("Database initialized")
    yield


app = FastAPI(
    title="Store Intelligence API",
    description=(
        "Apex Retail store intelligence system. Ingests behavioural events from "
        "the CCTV detection pipeline and exposes store analytics endpoints."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)

app.include_router(health_router)
app.include_router(ingestion_router)
app.include_router(metrics_router)
app.include_router(funnel_router)
app.include_router(heatmap_router)
app.include_router(anomalies_router)


def _trace_id_from_request(request: Request) -> str | None:
    trace_id = getattr(request.state, "trace_id", None)
    return str(trace_id) if trace_id is not None else None


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return structured JSON for request validation failures."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(
            error="validation_error",
            detail=str(exc.errors()),
            trace_id=_trace_id_from_request(request),
        ).model_dump(mode="json"),
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(
    request: Request, exc: SQLAlchemyError
) -> JSONResponse:
    """Return HTTP 503 when the database layer fails unexpectedly."""
    logger.exception("Unhandled database error on %s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=ErrorResponse(
            error="database_unavailable",
            detail="A database error occurred",
            trace_id=_trace_id_from_request(request),
        ).model_dump(mode="json"),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch unexpected errors and avoid leaking stack traces to clients."""
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="internal_server_error",
            detail="An unexpected error occurred",
            trace_id=_trace_id_from_request(request),
        ).model_dump(mode="json"),
    )
