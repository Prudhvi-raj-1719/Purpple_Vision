"""Pydantic v2 schemas for events, ingestion, and API contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class EventType(StrEnum):
    """Behavioural event types emitted by the detection pipeline."""

    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    ZONE_DWELL = "ZONE_DWELL"
    BILLING_QUEUE_JOIN = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_ABANDON = "BILLING_QUEUE_ABANDON"
    REENTRY = "REENTRY"


class AnomalySeverity(StrEnum):
    """Severity levels for store anomaly alerts (PDF: INFO / WARN / CRITICAL)."""

    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


# Threshold events where zone_id must be absent per challenge schema.
_ZONE_ABSENT_EVENT_TYPES: frozenset[EventType] = frozenset(
    {EventType.ENTRY, EventType.EXIT, EventType.REENTRY}
)

# Threshold events where zone_id must be present.
_ZONE_REQUIRED_EVENT_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.ZONE_ENTER,
        EventType.ZONE_EXIT,
        EventType.ZONE_DWELL,
        EventType.BILLING_QUEUE_JOIN,
        EventType.BILLING_QUEUE_ABANDON,
    }
)


# ---------------------------------------------------------------------------
# Shared configuration
# ---------------------------------------------------------------------------

_STRICT_MODEL_CONFIG = ConfigDict(
    str_strip_whitespace=True,
    extra="forbid",
    populate_by_name=True,
)


# ---------------------------------------------------------------------------
# Event schema (challenge PDF §4 Part A)
# ---------------------------------------------------------------------------


class EventMetadata(BaseModel):
    """Optional metadata attached to behavioural events."""

    model_config = _STRICT_MODEL_CONFIG

    queue_depth: int | None = Field(
        default=None,
        ge=0,
        description="Queue depth when visitor joins billing queue.",
    )
    sku_zone: str | None = Field(
        default=None,
        min_length=1,
        description="Product zone label from store_layout.json.",
    )
    session_seq: int | None = Field(
        default=None,
        ge=1,
        description="Ordinal position of this event within the visitor session.",
    )


class Event(BaseModel):
    """
    Structured behavioural event emitted by the detection pipeline.

    Matches the challenge output schema. Low-confidence events must be retained
    (confidence is recorded, not used to drop events).
    """

    model_config = _STRICT_MODEL_CONFIG

    event_id: UUID = Field(description="Globally unique UUID v4 identifier.")
    store_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^STORE_[A-Z0-9_]+$",
        examples=["STORE_BLR_002"],
    )
    camera_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^CAM_[A-Z0-9_]+$",
        examples=["CAM_ENTRY_01"],
    )
    visitor_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^VIS_[a-z0-9]+$",
        examples=["VIS_c8a2f1"],
    )
    event_type: EventType
    timestamp: datetime = Field(
        description="ISO-8601 UTC timestamp derived from clip start + frame offset.",
    )
    zone_id: str | None = Field(
        default=None,
        max_length=64,
        description="Zone from store_layout.json; null for ENTRY/EXIT/REENTRY.",
    )
    dwell_ms: int = Field(
        default=0,
        ge=0,
        description="Dwell duration in milliseconds; 0 for instantaneous events.",
    )
    is_staff: bool = Field(
        description="True when the detected person is classified as store staff.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Detection confidence; low values must not suppress the event.",
    )
    metadata: EventMetadata = Field(default_factory=EventMetadata)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_utc(cls, value: datetime) -> datetime:
        """Normalise timestamps to UTC-aware datetimes."""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @field_validator("event_id")
    @classmethod
    def event_id_must_be_uuid_v4(cls, value: UUID) -> UUID:
        """Enforce UUID v4 as required by the challenge schema."""
        if value.version != 4:
            raise ValueError("event_id must be a UUID v4 value")
        return value

    @model_validator(mode="after")
    def validate_event_semantics(self) -> Event:
        """Cross-field rules aligned with the event type catalogue."""
        if self.event_type in _ZONE_ABSENT_EVENT_TYPES and self.zone_id is not None:
            raise ValueError(
                f"zone_id must be null for {self.event_type.value} events"
            )

        if self.event_type in _ZONE_REQUIRED_EVENT_TYPES and not self.zone_id:
            raise ValueError(
                f"zone_id is required for {self.event_type.value} events"
            )

        if self.event_type == EventType.BILLING_QUEUE_JOIN:
            depth = self.metadata.queue_depth
            if depth is None or depth <= 0:
                raise ValueError(
                    "metadata.queue_depth must be > 0 for BILLING_QUEUE_JOIN events"
                )

        if self.event_type == EventType.ZONE_DWELL and self.dwell_ms < 30_000:
            raise ValueError(
                "dwell_ms must be >= 30000 for ZONE_DWELL events"
            )

        return self


# ---------------------------------------------------------------------------
# Ingestion request / response models (POST /events/ingest)
# ---------------------------------------------------------------------------


class EventIngestRequest(BaseModel):
    """Batch ingest payload — up to 500 events per request."""

    model_config = _STRICT_MODEL_CONFIG

    events: list[Event] = Field(min_length=1, max_length=500)


class IngestErrorDetail(BaseModel):
    """Structured error for a single malformed or rejected event."""

    model_config = _STRICT_MODEL_CONFIG

    index: int = Field(ge=0, description="Position in the submitted batch.")
    event_id: str | None = Field(
        default=None,
        description="event_id if present in the raw payload.",
    )
    error: str = Field(min_length=1)


class EventIngestResponse(BaseModel):
    """Partial-success ingest result."""

    model_config = _STRICT_MODEL_CONFIG

    accepted: int = Field(ge=0)
    rejected: int = Field(ge=0)
    duplicate: int = Field(
        ge=0,
        default=0,
        description="Events skipped because event_id already exists (idempotent).",
    )
    errors: list[IngestErrorDetail] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# POS transaction schema (pos_transactions.csv)
# ---------------------------------------------------------------------------


class PosTransaction(BaseModel):
    """Point-of-sale record used for conversion correlation."""

    model_config = _STRICT_MODEL_CONFIG

    store_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^STORE_[A-Z0-9_]+$",
    )
    transaction_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^TXN_[A-Z0-9_]+$",
        examples=["TXN_00441"],
    )
    timestamp: datetime
    basket_value_inr: float = Field(ge=0.0, examples=[1240.00])

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class PosTransactionIngestRequest(BaseModel):
    """Batch ingest payload for POS transactions."""

    model_config = _STRICT_MODEL_CONFIG

    transactions: list[PosTransaction] = Field(min_length=1, max_length=500)


class PosIngestErrorDetail(BaseModel):
    """Structured error for a single malformed or rejected POS transaction."""

    model_config = _STRICT_MODEL_CONFIG

    index: int = Field(ge=0, description="Position in the submitted batch.")
    transaction_id: str | None = Field(
        default=None,
        description="transaction_id if present in the raw payload.",
    )
    error: str = Field(min_length=1)


class PosIngestStatusResponse(BaseModel):
    """POST /pos/ingest response."""

    model_config = _STRICT_MODEL_CONFIG

    status: str = Field(
        description="Overall result: success, partial, or failed.",
    )
    total_received: int = Field(ge=0, description="Number of transactions in the batch.")
    transactions_ingested: int = Field(
        ge=0,
        description="New transactions persisted to the database.",
    )
    duplicates_skipped: int = Field(
        ge=0,
        description="Transactions skipped because transaction_id exists.",
    )
    rejected: int = Field(ge=0, description="Transactions rejected due to validation errors.")
    errors: list[PosIngestErrorDetail] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API response models (shape only — logic implemented in later phases)
# ---------------------------------------------------------------------------


class ZoneDwellMetric(BaseModel):
    model_config = _STRICT_MODEL_CONFIG

    zone_id: str
    average_dwell_ms: float = Field(ge=0.0)


class StoreMetricsResponse(BaseModel):
    """GET /stores/{store_id}/metrics response (Phase 3B)."""

    model_config = _STRICT_MODEL_CONFIG

    store_id: str
    date: str = Field(
        description="UTC calendar day (YYYY-MM-DD) used for the metrics window.",
    )
    unique_visitors: int = Field(ge=0)
    conversion_rate: float = Field(ge=0.0, le=1.0)
    average_dwell_time_ms: float = Field(
        ge=0.0,
        description="Mean total in-zone dwell per customer session (milliseconds).",
    )
    average_dwell_by_zone: list[ZoneDwellMetric] = Field(
        default_factory=list,
        description="Mean dwell per zone across customer session visits (milliseconds).",
    )
    current_queue_depth: int = Field(
        ge=0,
        description=(
            "Queue depth from the latest non-staff BILLING_QUEUE_JOIN event "
            "on the requested day; 0 when no queue joins were recorded."
        ),
    )
    queue_abandonment_rate: float = Field(ge=0.0, le=1.0)
    billing_reach_rate: float = Field(ge=0.0, le=1.0)
    total_sessions: int = Field(ge=0)


class FunnelStage(BaseModel):
    model_config = _STRICT_MODEL_CONFIG

    stage: str
    count: int = Field(ge=0)
    drop_off_pct: float | None = Field(default=None, ge=0.0, le=100.0)


class StoreFunnelResponse(BaseModel):
    """GET /stores/{store_id}/funnel response (Phase 4A)."""

    model_config = _STRICT_MODEL_CONFIG

    store_id: str
    date: str = Field(
        description="UTC calendar day (YYYY-MM-DD) used for the funnel window.",
    )
    stages: list[FunnelStage]
    overall_conversion_rate: float = Field(
        ge=0.0,
        le=1.0,
        description="Converted visitors ÷ unique visitors (North Star).",
    )


class HeatmapZone(BaseModel):
    """Per-zone heatmap metrics for GET /stores/{store_id}/heatmap (Phase 4B)."""

    model_config = _STRICT_MODEL_CONFIG

    zone_id: str
    visit_count: int = Field(ge=0)
    unique_visitors: int = Field(ge=0)
    total_dwell_time_ms: int = Field(ge=0)
    average_dwell_time_ms: float = Field(ge=0.0)
    normalized_score: float = Field(ge=0.0, le=100.0)


class StoreHeatmapResponse(BaseModel):
    """GET /stores/{store_id}/heatmap response (Phase 4B)."""

    model_config = _STRICT_MODEL_CONFIG

    store_id: str
    date: str = Field(
        description="UTC calendar day (YYYY-MM-DD) used for the heatmap window.",
    )
    zones: list[HeatmapZone]
    data_confidence: bool = Field(
        description=(
            "True when at least 20 customer sessions exist for the day; "
            "False when sample size is too small for reliable heatmap comparison."
        ),
    )


class Anomaly(BaseModel):
    """Single detected store anomaly (Phase 4C)."""

    model_config = _STRICT_MODEL_CONFIG

    anomaly_type: str
    severity: AnomalySeverity
    title: str
    description: str
    suggested_action: str = Field(
        min_length=1,
        description="Operational recommendation for store staff or managers.",
    )
    detected_at: datetime = Field(
        description="UTC timestamp when the anomaly was detected.",
    )
    supporting_metrics: dict[str, float | int | str] = Field(default_factory=dict)


class StoreAnomaliesResponse(BaseModel):
    """GET /stores/{store_id}/anomalies response (Phase 4C)."""

    model_config = _STRICT_MODEL_CONFIG

    store_id: str
    date: str = Field(
        description="UTC calendar day (YYYY-MM-DD) used for the anomaly window.",
    )
    anomalies: list[Anomaly]


class StoreFeedStatus(BaseModel):
    model_config = _STRICT_MODEL_CONFIG

    store_id: str
    last_event_at: datetime | None = None
    stale: bool = False


class HealthResponse(BaseModel):
    """GET /health response (Phase 4D)."""

    model_config = _STRICT_MODEL_CONFIG

    status: str
    database_available: bool
    timestamp: datetime = Field(
        description="UTC timestamp when the health check was performed.",
    )
    stores: list[StoreFeedStatus]
    warnings: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Structured API error body (e.g. HTTP 503 when DB unavailable)."""

    model_config = _STRICT_MODEL_CONFIG

    error: str
    detail: str | None = None
    trace_id: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_event(raw: dict[str, Any]) -> Event:
    """Parse and validate a raw dict into an Event model."""
    return Event.model_validate(raw)
