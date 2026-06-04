"""Pydantic schemas for AI business insights (optional analytics layer)."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_STRICT_MODEL_CONFIG = ConfigDict(
    str_strip_whitespace=True,
    extra="forbid",
    populate_by_name=True,
)

InsightSource = Literal["llm", "fallback"]

_SENTENCE_SPLIT = re.compile(r"[.!?]+")


def _count_sentences(text: str) -> int:
    return len([part for part in _SENTENCE_SPLIT.split(text.strip()) if part.strip()])


class CheckoutContext(BaseModel):
    model_config = _STRICT_MODEL_CONFIG

    queue_depth: int = Field(ge=0)
    peak_queue_depth: int = Field(
        ge=0,
        description="Maximum queue_depth observed across BILLING_QUEUE_JOIN events for the day.",
    )
    queue_abandonment_rate: float = Field(ge=0.0, le=1.0)
    billing_reach_rate: float = Field(ge=0.0, le=1.0)
    reached_checkout_count: int = Field(
        ge=0,
        description="Count of customers who reached checkout (funnel billing_queue stage).",
    )
    completed_purchase_count: int = Field(
        ge=0,
        description="Count of customers who completed a purchase (funnel converted_visitors stage).",
    )


class FunnelContext(BaseModel):
    model_config = _STRICT_MODEL_CONFIG

    entered: int = Field(ge=0)
    reached_zone: int = Field(ge=0)
    reached_checkout: int = Field(ge=0)
    converted: int = Field(ge=0)


class ZoneScoreContext(BaseModel):
    model_config = _STRICT_MODEL_CONFIG

    zone: str
    score: float = Field(ge=0.0, le=100.0)


class AnomalySummaryContext(BaseModel):
    model_config = _STRICT_MODEL_CONFIG

    type: str
    severity: str


class StoreHealthContext(BaseModel):
    model_config = _STRICT_MODEL_CONFIG

    status: str
    data_confidence: str


class BusinessContext(BaseModel):
    """Compact analytics snapshot passed to the LLM (< 2 KB target)."""

    model_config = _STRICT_MODEL_CONFIG

    store_id: str
    date: str
    visitors: int = Field(ge=0)
    sessions: int = Field(ge=0)
    revenue: float = Field(ge=0.0)
    conversion_rate: float = Field(ge=0.0, le=1.0)
    checkout: CheckoutContext
    funnel: FunnelContext
    top_zones: list[ZoneScoreContext] = Field(default_factory=list)
    weak_zones: list[ZoneScoreContext] = Field(default_factory=list)
    anomalies: list[AnomalySummaryContext] = Field(default_factory=list)
    store_health: StoreHealthContext


class BusinessInsightResponse(BaseModel):
    """Validated manager-facing insight payload."""

    model_config = _STRICT_MODEL_CONFIG

    store_summary: str = Field(min_length=1)
    manager_actions: list[str] = Field(min_length=3, max_length=5)
    business_risks: list[str] = Field(min_length=1, max_length=3)
    positive_signals: list[str] = Field(min_length=1, max_length=3)
    checkout_summary: str = Field(min_length=1)
    checkout_actions: list[str] = Field(min_length=2, max_length=4)

    @field_validator("store_summary")
    @classmethod
    def store_summary_max_three_sentences(cls, value: str) -> str:
        if _count_sentences(value) > 3:
            raise ValueError("store_summary must be at most 3 sentences")
        return value

    @field_validator("checkout_summary")
    @classmethod
    def checkout_summary_max_two_sentences(cls, value: str) -> str:
        if _count_sentences(value) > 2:
            raise ValueError("checkout_summary must be at most 2 sentences")
        return value

    @field_validator(
        "manager_actions",
        "business_risks",
        "positive_signals",
        "checkout_actions",
    )
    @classmethod
    def strip_non_empty_items(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if len(cleaned) != len(value):
            raise ValueError("insight list items must be non-empty strings")
        return cleaned


class StoreBusinessInsightsResponse(BaseModel):
    """GET /stores/{store_id}/business-insights response."""

    model_config = _STRICT_MODEL_CONFIG

    store_id: str
    date: str
    source: InsightSource
    provider: str = Field(
        min_length=1,
        description="Insight provider used: groq/openrouter/ollama/openai_compatible or fallback.",
    )
    context: dict[str, Any]
    insights: BusinessInsightResponse
