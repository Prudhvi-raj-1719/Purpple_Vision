"""Tests for optional AI business insights layer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.business_insights import (
    build_business_context,
    generate_business_insights,
    generate_deterministic_insights,
)
from app.health import compute_health_response
from app.llm_provider import (
    DeterministicFallbackProvider,
    GroqProvider,
    OpenRouterProvider,
    build_llm_provider,
)
from app.models import (
    Anomaly,
    AnomalySeverity,
    FunnelStage,
    HealthResponse,
    HeatmapZone,
    StoreAnomaliesResponse,
    StoreFunnelResponse,
    StoreHeatmapResponse,
    StoreMetricsResponse,
)
from app.schemas.business_insights import BusinessInsightResponse

UTC = timezone.utc
STORE = "STORE_BLR_002"
DAY = "2026-06-01"


def _metrics(**overrides) -> StoreMetricsResponse:
    base = dict(
        store_id=STORE,
        date=DAY,
        unique_visitors=128,
        conversion_rate=0.53,
        average_dwell_time_ms=120_000.0,
        average_dwell_by_zone=[],
        current_queue_depth=4,
        queue_abandonment_rate=0.14,
        billing_reach_rate=0.75,
        total_sessions=153,
        total_revenue_inr=84_441.0,
    )
    base.update(overrides)
    return StoreMetricsResponse(**base)


def _funnel() -> StoreFunnelResponse:
    return StoreFunnelResponse(
        store_id=STORE,
        date=DAY,
        stages=[
            FunnelStage(stage="unique_visitors", count=128, drop_off_pct=None),
            FunnelStage(stage="reached_any_zone", count=122, drop_off_pct=4.7),
            FunnelStage(stage="billing_queue", count=96, drop_off_pct=21.3),
            FunnelStage(stage="converted_visitors", count=68, drop_off_pct=29.2),
        ],
        overall_conversion_rate=0.53,
    )


def _heatmap() -> StoreHeatmapResponse:
    return StoreHeatmapResponse(
        store_id=STORE,
        date=DAY,
        data_confidence=True,
        zones=[
            HeatmapZone(
                zone_id="GOODVIBES",
                visit_count=40,
                unique_visitors=35,
                total_dwell_time_ms=500_000,
                average_dwell_time_ms=12_500.0,
                normalized_score=100.0,
            ),
            HeatmapZone(
                zone_id="EASTIND",
                visit_count=5,
                unique_visitors=4,
                total_dwell_time_ms=20_000,
                average_dwell_time_ms=4_000.0,
                normalized_score=12.0,
            ),
            HeatmapZone(
                zone_id="BILLING",
                visit_count=20,
                unique_visitors=18,
                total_dwell_time_ms=80_000,
                average_dwell_time_ms=4_000.0,
                normalized_score=50.0,
            ),
        ],
    )


def _anomalies() -> StoreAnomaliesResponse:
    return StoreAnomaliesResponse(
        store_id=STORE,
        date=DAY,
        anomalies=[
            Anomaly(
                anomaly_type="QUEUE_SPIKE",
                severity=AnomalySeverity.CRITICAL,
                title="Critical billing queue spike detected",
                description="Queue joins exceed threshold.",
                suggested_action="Add billing staff.",
                detected_at=datetime(2026, 6, 1, 18, 0, tzinfo=UTC),
                supporting_metrics={"queue_joins": 12},
            )
        ],
    )


def _health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        database_available=True,
        timestamp=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        stores=[],
        warnings=[],
    )


class TestBusinessContext:
    def test_build_business_context_is_compact(self) -> None:
        context = build_business_context(
            store_id=STORE,
            metric_date=datetime(2026, 6, 1, tzinfo=UTC).date(),
            metrics=_metrics(),
            funnel=_funnel(),
            heatmap=_heatmap(),
            anomalies=_anomalies(),
            health=_health(),
            events=[],
        )
        payload = context.model_dump(mode="json")
        encoded = json.dumps(payload)
        assert len(encoded) < 2048
        assert payload["visitors"] == 128
        assert payload["checkout"]["queue_depth"] == 4
        assert payload["funnel"]["converted"] == 68
        assert payload["top_zones"][0]["zone"] == "GOODVIBES"
        assert payload["weak_zones"][0]["zone"] == "EASTIND"
        assert payload["anomalies"][0]["type"] == "QUEUE_SPIKE"
        assert all(zone["zone"] != "BILLING" for zone in payload["top_zones"])


class TestDeterministicInsights:
    def test_fallback_meets_schema_constraints(self) -> None:
        context = build_business_context(
            store_id=STORE,
            metric_date=datetime(2026, 6, 1, tzinfo=UTC).date(),
            metrics=_metrics(),
            funnel=_funnel(),
            heatmap=_heatmap(),
            anomalies=_anomalies(),
            health=_health(),
            events=[],
        )
        insights = generate_deterministic_insights(context)

        assert 1 <= len(insights.business_risks) <= 3
        assert 3 <= len(insights.manager_actions) <= 5
        assert 1 <= len(insights.positive_signals) <= 3
        assert insights.store_summary
        assert insights.checkout_summary
        assert 2 <= len(insights.checkout_actions) <= 4

    def test_generate_business_insights_uses_fallback_when_disabled(self) -> None:
        context = build_business_context(
            store_id=STORE,
            metric_date=datetime(2026, 6, 1, tzinfo=UTC).date(),
            metrics=_metrics(),
            funnel=_funnel(),
            heatmap=_heatmap(),
            anomalies=_anomalies(),
            health=_health(),
            events=[],
        )
        with patch("app.business_insights.is_ai_insights_enabled", return_value=False):
            source, provider, insights = generate_business_insights(context)

        assert source == "fallback"
        assert provider == "fallback"
        assert isinstance(insights, BusinessInsightResponse)

    def test_llm_failure_falls_back(self) -> None:
        context = build_business_context(
            store_id=STORE,
            metric_date=datetime(2026, 6, 1, tzinfo=UTC).date(),
            metrics=_metrics(),
            funnel=_funnel(),
            heatmap=_heatmap(),
            anomalies=_anomalies(),
            health=_health(),
            events=[],
        )

        class FailingProvider:
            def generate_insights(self, context_dict):  # type: ignore[no-untyped-def]
                return None

        with patch("app.business_insights.is_ai_insights_enabled", return_value=True):
            with patch("app.business_insights.build_llm_provider", return_value=FailingProvider()):
                source, _provider, insights = generate_business_insights(context)

        assert source == "fallback"
        assert len(insights.manager_actions) >= 3
        assert len(insights.checkout_actions) >= 2


class TestBusinessInsightsEndpoint:
    def test_get_business_insights_returns_fallback_by_default(
        self, client: TestClient
    ) -> None:
        # Force fallback regardless of developer machine env vars.
        with patch.dict("os.environ", {"ENABLE_AI_INSIGHTS": "false"}, clear=False):
            response = client.get(
                f"/stores/{STORE}/business-insights",
                params={"date": DAY},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["store_id"] == STORE
        assert body["date"] == DAY
        assert body["source"] == "fallback"
        assert body["provider"] == "fallback"
        assert "context" in body
        assert "insights" in body
        assert 3 <= len(body["insights"]["manager_actions"]) <= 5


class TestCloudProviderSelection:
    def test_default_provider_is_groq_when_enabled_and_unspecified(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ENABLE_AI_INSIGHTS": "true",
                # LLM_PROVIDER intentionally omitted
                "GROQ_API_KEY": "test-key",
                "GROQ_MODEL": "llama-3.3-70b-versatile",
            },
            clear=False,
        ):
            provider = build_llm_provider()
        assert isinstance(provider, GroqProvider)

    def test_missing_groq_key_falls_back(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ENABLE_AI_INSIGHTS": "true",
                # LLM_PROVIDER intentionally omitted (defaults to groq)
                "GROQ_API_KEY": "",
                "GROQ_MODEL": "llama-3.3-70b-versatile",
            },
            clear=False,
        ):
            provider = build_llm_provider()
        assert isinstance(provider, DeterministicFallbackProvider)

    def test_repair_recommendations_shape_succeeds(self) -> None:
        context = build_business_context(
            store_id=STORE,
            metric_date=datetime(2026, 6, 1, tzinfo=UTC).date(),
            metrics=_metrics(),
            funnel=_funnel(),
            heatmap=_heatmap(),
            anomalies=_anomalies(),
            health=_health(),
            events=[],
        )

        class RecommendationsProvider:
            name = "groq"

            def generate_insights(self, context_dict):  # type: ignore[no-untyped-def]
                # Simulate the model returning a non-conforming but common shape.
                payload = {
                    "store_id": "STORE_BLR_002",
                    "recommendations": [
                        "Open an extra billing counter during peak hours",
                        "Add signage to guide shoppers to checkout",
                        "Refresh the weakest product area display",
                    ],
                }
                # This is what llm_provider would parse from model output.
                from app.llm_provider import _repair_common_model_shapes
                repaired = _repair_common_model_shapes(parsed=payload, context=context.model_dump(mode="json"))
                from app.schemas.business_insights import BusinessInsightResponse
                return BusinessInsightResponse.model_validate(repaired)

        with patch("app.business_insights.is_ai_insights_enabled", return_value=True):
            with patch("app.business_insights.build_llm_provider", return_value=RecommendationsProvider()):
                source, provider, insights = generate_business_insights(context)

        assert source == "llm"
        assert provider == "groq"
        assert 3 <= len(insights.manager_actions) <= 5

    def test_auto_pad_short_lists_before_validation(self) -> None:
        context = build_business_context(
            store_id=STORE,
            metric_date=datetime(2026, 6, 1, tzinfo=UTC).date(),
            metrics=_metrics(),
            funnel=_funnel(),
            heatmap=_heatmap(),
            anomalies=_anomalies(),
            health=_health(),
            events=[],
        )

        from app.llm_provider import _normalize_insight_payload_for_schema

        parsed = {
            "store_summary": "Footfall was steady and checkout demand increased during peaks.",
            "manager_actions": ["Open an extra checkout lane during peak hours", "Add a floater near billing"],
            "business_risks": [],
            "positive_signals": [],
            "checkout_summary": "",
            "checkout_actions": ["Open another billing lane"],
        }
        normalized, did_repair = _normalize_insight_payload_for_schema(
            parsed=parsed,
            context=context.model_dump(mode="json"),
        )
        assert did_repair is True
        assert len(normalized["manager_actions"]) >= 3
        assert len(normalized["business_risks"]) >= 1
        assert len(normalized["positive_signals"]) >= 1

    def test_openrouter_provider_selected(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ENABLE_AI_INSIGHTS": "true",
                "LLM_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_MODEL": "qwen/qwen3-32b",
            },
            clear=False,
        ):
            provider = build_llm_provider()
        assert isinstance(provider, OpenRouterProvider)

    def test_groq_provider_selected(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ENABLE_AI_INSIGHTS": "true",
                "LLM_PROVIDER": "groq",
                "GROQ_API_KEY": "test-key",
                "GROQ_MODEL": "llama-3.3-70b-versatile",
            },
            clear=False,
        ):
            provider = build_llm_provider()
        assert isinstance(provider, GroqProvider)

    def test_disabled_ai_uses_fallback_provider(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ENABLE_AI_INSIGHTS": "false",
                "LLM_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_MODEL": "qwen/qwen3-32b",
            },
            clear=False,
        ):
            provider = build_llm_provider()
        assert isinstance(provider, DeterministicFallbackProvider)
