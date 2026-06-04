"""Optional AI business insight layer — interprets deterministic analytics only."""

from __future__ import annotations

import logging
import time
from datetime import date
import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.anomalies import compute_store_anomalies
from app.db import (
    EventRecord,
    PosTransactionRecord,
    fetch_store_events,
    fetch_store_pos_transactions,
    get_db,
    is_database_available,
)
from app.funnel import (
    STAGE_BILLING_QUEUE,
    STAGE_CONVERTED_VISITORS,
    STAGE_REACHED_ANY_ZONE,
    STAGE_UNIQUE_VISITORS,
    compute_store_funnel,
)
from app.health import compute_health_response
from app.heatmap import compute_store_heatmap
from app.llm_provider import build_llm_provider, is_ai_insights_enabled
from app.metrics import compute_store_metrics, parse_metric_date
from app.staff_detection import build_sessions_for_analytics
from app.schemas.business_insights import (
    AnomalySummaryContext,
    BusinessContext,
    BusinessInsightResponse,
    CheckoutContext,
    FunnelContext,
    InsightSource,
    StoreBusinessInsightsResponse,
    StoreHealthContext,
    ZoneScoreContext,
)
from app.models import (
    HealthResponse,
    StoreAnomaliesResponse,
    StoreFunnelResponse,
    StoreHeatmapResponse,
    StoreMetricsResponse,
)
from app.sessions import BILLING_ZONE_ID

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stores", tags=["business-insights"])

_BILLING_ZONE = BILLING_ZONE_ID.upper()


def _funnel_stage_count(funnel: StoreFunnelResponse, stage_key: str) -> int:
    for stage in funnel.stages:
        if stage.stage == stage_key:
            return stage.count
    return 0


def _compute_peak_queue_depth(events: list[EventRecord]) -> int:
    """Maximum metadata.queue_depth across non-staff BILLING_QUEUE_JOIN events."""
    sessions, _classifications, staff_ids = build_sessions_for_analytics(events)
    _ = sessions  # sessions unused; staff_ids derived consistently via analytics layer.
    peak = 0
    for event in events:
        if event.event_type != "BILLING_QUEUE_JOIN":
            continue
        if event.is_staff or event.visitor_id in staff_ids:
            continue
        try:
            metadata = json.loads(event.metadata_json) if event.metadata_json else {}
        except Exception:
            metadata = {}
        depth = metadata.get("queue_depth")
        if isinstance(depth, int) and depth > peak:
            peak = depth
        elif isinstance(depth, float) and int(depth) > peak:
            peak = int(depth)
    return peak


def _is_product_zone(zone_id: str) -> bool:
    return zone_id.upper() != _BILLING_ZONE


def _rank_product_zones(heatmap: StoreHeatmapResponse) -> list[ZoneScoreContext]:
    zones = [
        ZoneScoreContext(zone=zone.zone_id, score=round(zone.normalized_score, 1))
        for zone in heatmap.zones
        if _is_product_zone(zone.zone_id)
    ]
    return sorted(zones, key=lambda item: item.score, reverse=True)


def _map_health_status(health: HealthResponse) -> str:
    if not health.database_available:
        return "unavailable"
    if health.status == "ok":
        return "healthy"
    return "degraded"


def _map_data_confidence(heatmap: StoreHeatmapResponse) -> str:
    return "high" if heatmap.data_confidence else "low"


def _summarize_anomalies(anomalies: StoreAnomaliesResponse) -> list[AnomalySummaryContext]:
    summaries: list[AnomalySummaryContext] = []
    for anomaly in anomalies.anomalies[:5]:
        summaries.append(
            AnomalySummaryContext(
                type=anomaly.anomaly_type,
                severity=anomaly.severity.value.lower(),
            )
        )
    return summaries


def build_business_context(
    *,
    store_id: str,
    metric_date: date,
    metrics: StoreMetricsResponse,
    funnel: StoreFunnelResponse,
    heatmap: StoreHeatmapResponse,
    anomalies: StoreAnomaliesResponse,
    health: HealthResponse,
    events: list[EventRecord],
) -> BusinessContext:
    """
    Aggregate deterministic analytics into one compact context object.

    This is the only place that combines metrics, funnel, heatmap, anomalies,
    and health for insight generation.
    """
    ranked = _rank_product_zones(heatmap)
    top_zones = ranked[:2]
    weak_candidates = [zone for zone in ranked if zone.score < 50.0]
    weak_candidates.sort(key=lambda item: item.score)
    weak_zones = weak_candidates[:5]
    reached_checkout_count = _funnel_stage_count(funnel, STAGE_BILLING_QUEUE)
    completed_purchase_count = _funnel_stage_count(funnel, STAGE_CONVERTED_VISITORS)

    return BusinessContext(
        store_id=store_id,
        date=metric_date.isoformat(),
        visitors=metrics.unique_visitors,
        sessions=metrics.total_sessions,
        revenue=round(metrics.total_revenue_inr, 2),
        conversion_rate=round(metrics.conversion_rate, 4),
        checkout=CheckoutContext(
            queue_depth=metrics.current_queue_depth,
            peak_queue_depth=_compute_peak_queue_depth(events),
            queue_abandonment_rate=round(metrics.queue_abandonment_rate, 4),
            billing_reach_rate=round(metrics.billing_reach_rate, 4),
            reached_checkout_count=reached_checkout_count,
            completed_purchase_count=completed_purchase_count,
        ),
        funnel=FunnelContext(
            entered=_funnel_stage_count(funnel, STAGE_UNIQUE_VISITORS),
            reached_zone=_funnel_stage_count(funnel, STAGE_REACHED_ANY_ZONE),
            reached_checkout=_funnel_stage_count(funnel, STAGE_BILLING_QUEUE),
            converted=_funnel_stage_count(funnel, STAGE_CONVERTED_VISITORS),
        ),
        top_zones=top_zones,
        weak_zones=weak_zones,
        anomalies=_summarize_anomalies(anomalies),
        store_health=StoreHealthContext(
            status=_map_health_status(health),
            data_confidence=_map_data_confidence(heatmap),
        ),
    )


def _friendly_zone(zone_id: str) -> str:
    return zone_id.replace("_", " ").strip().title()


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def generate_deterministic_insights(context: BusinessContext) -> BusinessInsightResponse:
    """Rule-based fallback insights derived only from the business context."""
    visitors = context.visitors
    converted = context.funnel.converted
    conversion = context.conversion_rate
    revenue = context.revenue
    checkout = context.checkout

    top_zone = context.top_zones[0].zone if context.top_zones else None
    weak_zone = context.weak_zones[0].zone if context.weak_zones else None
    weak_score = context.weak_zones[0].score if context.weak_zones else 100.0

    summary_parts: list[str] = []
    if visitors == 0:
        summary_parts.append(
            f"No customer visits were recorded for {context.store_id} on {context.date}."
        )
    else:
        summary_parts.append(
            f"{visitors} customers visited the store and {converted} completed a purchase "
            f"({_pct(conversion)} conversion)."
        )
        if revenue > 0:
            summary_parts.append(f"Total sales reached ₹{revenue:,.0f} for the day.")
    store_summary = " ".join(summary_parts[:3])

    actions: list[str] = []
    risks: list[str] = []
    positives: list[str] = []

    for anomaly in context.anomalies:
        if anomaly.type == "QUEUE_SPIKE":
            risks.append("Checkout lines are unusually busy — customers may face longer waits.")
            actions.append("Add billing staff or open a second checkout lane during peak hours.")
        elif anomaly.type == "CONVERSION_DROP":
            risks.append("Fewer visitors than expected are completing purchases today.")
            actions.append(
                "Walk the store path from entrance to till and remove friction points."
            )
        elif anomaly.type == "DEAD_ZONE" and weak_zone:
            risks.append(
                f"{_friendly_zone(weak_zone)} shows low customer engagement compared with other areas."
            )
            actions.append(
                f"Review merchandising and signage in {_friendly_zone(weak_zone)}."
            )

    if checkout.queue_abandonment_rate >= 0.15:
        risks.append(
            f"Queue abandonment is {_pct(checkout.queue_abandonment_rate)} — "
            "some customers left checkout before paying."
        )
        actions.append("Speed up checkout service and keep tills fully staffed during busy periods.")

    if checkout.queue_depth >= 3:
        risks.append(
            f"About {checkout.queue_depth} customers were waiting at checkout when last measured."
        )
        if "Add billing staff" not in " ".join(actions):
            actions.append("Monitor checkout queue length and redeploy floor staff when lines build.")

    if visitors > 0 and conversion < 0.30 and not any("purchase" in risk.lower() for risk in risks):
        risks.append(
            f"Only {_pct(conversion)} of visitors bought something — conversion is below a healthy range."
        )
        actions.append("Check pricing visibility, stock availability, and checkout staffing.")

    pre_billing_drop = max(0, context.funnel.reached_zone - context.funnel.reached_checkout)
    if context.funnel.reached_zone > 0 and pre_billing_drop >= max(1, context.funnel.reached_zone // 2):
        actions.append(
            "Guide shoppers from busy product areas to checkout with clear signs and staff prompts."
        )

    if weak_zone and weak_score < 25 and not any(_friendly_zone(weak_zone) in risk for risk in risks):
        risks.append(
            f"{_friendly_zone(weak_zone)} received the least customer interest on the floor today."
        )
        actions.append(
            f"Refresh displays in {_friendly_zone(weak_zone)} and borrow ideas from stronger areas."
        )

    if conversion >= 0.45 and visitors > 0:
        positives.append(
            f"Strong conversion at {_pct(conversion)} — many visitors are completing purchases."
        )
    elif converted > 0:
        positives.append(f"{converted} customers completed purchases today.")

    if checkout.queue_abandonment_rate < 0.15 and context.funnel.reached_checkout > 0:
        positives.append("Checkout abandonment remains low — customers are staying in line to pay.")

    if top_zone:
        positives.append(
            f"{_friendly_zone(top_zone)} is the top-performing product area today."
        )

    if revenue > 0 and not positives:
        positives.append(f"Store recorded ₹{revenue:,.0f} in sales for the day.")

    if not risks:
        risks.append("No major operational risks flagged from today's analytics.")

    if not actions:
        if weak_zone and top_zone:
            actions.append(
                f"Keep checkout staffed and test one display improvement in {_friendly_zone(weak_zone)}."
            )
        else:
            actions.append("Maintain current staffing levels and monitor checkout during peak hours.")

    while len(actions) < 3:
        actions.append("Review peak-hour staffing and keep paths to checkout clear.")

    if not positives:
        positives.append("Store monitoring and analytics are active for this trading day.")

    # Checkout assessment (fallback)
    checkout_peak = context.checkout.peak_queue_depth
    checkout_abandon = context.checkout.queue_abandonment_rate
    reached_checkout = context.checkout.reached_checkout_count
    completed_purchase = context.checkout.completed_purchase_count
    lost_before_purchase = max(0, reached_checkout - completed_purchase)

    if checkout_peak >= 6:
        checkout_summary = "Checkout demand was elevated during busy periods and lines built up."
    elif checkout_peak >= 4:
        checkout_summary = "Checkout demand increased during busy periods and queues formed."
    else:
        checkout_summary = "Checkout flow stayed manageable for most of the day."

    if checkout_abandon >= 0.15:
        checkout_summary = (
            f"{checkout_summary} Some customers left the line before paying, so reducing wait time should be a priority."
        )
    elif lost_before_purchase > 0:
        checkout_summary = (
            f"{checkout_summary} A small number of customers reached checkout but did not complete a purchase."
        )
    else:
        checkout_summary = (
            f"{checkout_summary} Most customers who reached checkout completed their purchase."
        )

    checkout_actions: list[str] = []
    if checkout_peak >= 4:
        checkout_actions.append("Open an additional billing lane during peak periods to reduce wait times.")
    if checkout_abandon >= 0.15:
        checkout_actions.append("Assign a floater at checkout to keep the line moving and prevent walk-aways.")
    checkout_actions.extend(
        [
            "Keep checkout staffing aligned with customer traffic patterns.",
            "Pre-stage bags and common items to speed up billing during rush windows.",
        ]
    )
    # de-dupe + cap to 2–4
    deduped: list[str] = []
    seen: set[str] = set()
    for item in checkout_actions:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    checkout_actions = deduped[:4]
    if len(checkout_actions) < 2:
        checkout_actions.append("Keep checkout staffing aligned with customer traffic patterns.")

    return BusinessInsightResponse(
        store_summary=store_summary,
        manager_actions=actions[:5],
        business_risks=risks[:3],
        positive_signals=positives[:3],
        checkout_summary=checkout_summary,
        checkout_actions=checkout_actions,
    )


def generate_business_insights(
    context: BusinessContext,
) -> tuple[InsightSource, str, BusinessInsightResponse]:
    """
    Attempt LLM insight generation when enabled; otherwise use deterministic fallback.

    Never raises — always returns a validated BusinessInsightResponse.
    """
    context_dict = context.model_dump(mode="json")

    if is_ai_insights_enabled():
        provider = build_llm_provider()
        provider_name = getattr(provider, "name", provider.__class__.__name__)
        logger.info("Business insights provider selected provider=%s", provider_name)
        try:
            started = time.perf_counter()
            llm_result = provider.generate_insights(context_dict)
            if llm_result is not None:
                duration_ms = (time.perf_counter() - started) * 1000.0
                logger.info(
                    "Business insights generated via LLM provider=%s duration_ms=%.2f",
                    provider_name,
                    duration_ms,
                )
                return "llm", provider_name, llm_result
            duration_ms = (time.perf_counter() - started) * 1000.0
            logger.warning(
                "Business insights fallback activated reason=provider_returned_none provider=%s duration_ms=%.2f",
                provider_name,
                duration_ms,
            )
        except Exception:
            logger.exception(
                "Business insights fallback activated reason=provider_exception provider=%s",
                provider_name,
            )
    else:
        logger.info("Business insights fallback activated reason=ai_disabled")

    return "fallback", "fallback", generate_deterministic_insights(context)


def compute_store_business_insights(
    store_id: str,
    metric_date: date,
    events: list[EventRecord],
    transactions: list[PosTransactionRecord],
    *,
    health: HealthResponse | None = None,
    db: Session | None = None,
) -> StoreBusinessInsightsResponse:
    """Build context and insights from deterministic analytics for one store-day."""
    metrics = compute_store_metrics(store_id, metric_date, events, transactions)
    funnel = compute_store_funnel(store_id, metric_date, events, transactions)
    heatmap = compute_store_heatmap(store_id, metric_date, events)
    anomalies = compute_store_anomalies(store_id, metric_date, events, transactions)
    health_response = health if health is not None else compute_health_response(db)

    context = build_business_context(
        store_id=store_id,
        metric_date=metric_date,
        metrics=metrics,
        funnel=funnel,
        heatmap=heatmap,
        anomalies=anomalies,
        health=health_response,
        events=events,
    )
    source, provider, insights = generate_business_insights(context)

    return StoreBusinessInsightsResponse(
        store_id=store_id,
        date=metric_date.isoformat(),
        source=source,
        provider=provider,
        context=context.model_dump(mode="json"),
        insights=insights,
    )


@router.get(
    "/{store_id}/business-insights",
    response_model=StoreBusinessInsightsResponse,
    summary="Store business insights",
    description=(
        "Returns manager-friendly business insights derived from deterministic analytics. "
        "Uses an optional local LLM when enabled; otherwise returns rule-based fallback insights."
    ),
    responses={
        503: {"description": "Database unavailable"},
        422: {"description": "Invalid date query parameter"},
    },
)
def get_store_business_insights(
    store_id: str,
    date_param: str | None = Query(
        default=None,
        alias="date",
        description="UTC calendar day (YYYY-MM-DD). Defaults to today (UTC).",
    ),
    db: Session = Depends(get_db),
) -> StoreBusinessInsightsResponse:
    """Generate business insights for a store on a UTC calendar day."""
    if not is_database_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )

    metric_date = parse_metric_date(date_param)

    try:
        events = fetch_store_events(db, store_id, day=metric_date)
        transactions = fetch_store_pos_transactions(db, store_id, day=metric_date)
        health = compute_health_response(db)
    except SQLAlchemyError as exc:
        logger.exception("Database error loading business insights for %s", store_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc

    return compute_store_business_insights(
        store_id,
        metric_date,
        events,
        transactions,
        health=health,
        db=db,
    )
