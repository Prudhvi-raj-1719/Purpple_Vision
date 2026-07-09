"""Retail Intelligence dashboard — data loading, orchestration, and analytics logic."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Streamlit runs this file with dashboard/ on sys.path; repo root is required
# for ``from dashboard.*`` and ``from scripts.*`` (via validation_context).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import httpx
import streamlit as st

from dashboard.saas_presentation import (
    hero_header_html,
    inject_saas_styles,
    render_ai_insights,
    render_checkout_command_center,
    render_customer_journey,
    render_executive_metrics,
    render_floor_intelligence,
    render_operations_monitoring,
    render_recommended_actions,
    render_technical_panel,
    render_todays_story,
    render_trust_center,
    sidebar_brand_html,
)
from dashboard.cctv_real_view import render_cctv_real_dashboard
from dashboard.validation_context import (
    is_cctv_real_store,
    api_base_url_for_store,
    bind_validation_database,
    dashboard_store_options,
    list_event_dates_from_db,
    load_analytics_from_validation_db,
    missing_database_hint,
    use_api_client,
)

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
DEFAULT_STORE_KEY = os.getenv("DEFAULT_DASHBOARD_STORE", "store_1")
DEFAULT_STORE_ID = os.getenv("DEFAULT_STORE_ID", "STORE_BLR_002")
DEFAULT_METRIC_DATE = os.getenv("DEFAULT_METRIC_DATE", "2026-04-10")

FUNNEL_ORDER = (
    "unique_visitors",
    "reached_any_zone",
    "billing_queue",
    "converted_visitors",
)

FUNNEL_LABELS: dict[str, str] = {
    "unique_visitors": "Entered store",
    "reached_any_zone": "Browsed products",
    "billing_queue": "Reached checkout",
    "converted_visitors": "Made a purchase",
}

# Presentation CSS and HTML live in dashboard.saas_presentation (SAAS_CSS).


@dataclass
class StoreSummary:
    happened: list[str]
    next_steps: list[str]


@dataclass
class BusinessInsight:
    problem: str
    evidence: str
    action: str
    priority: str
    severity: str = "WARN"


@dataclass
class CheckoutPerformance:
    """Checkout health summary derived from existing metrics APIs."""

    status: str  # "healthy" | "attention"
    headline: str
    bullets: list[str]


@st.cache_data(ttl=30, show_spinner=False)
def fetch_json(
    path: str,
    params: dict[str, str] | None = None,
    *,
    base_url: str | None = None,
) -> dict[str, Any]:
    root = (base_url or API_BASE_URL).rstrip("/")
    url = f"{root}{path}"
    with httpx.Client(timeout=15.0) as client:
        response = client.get(url, params=params or {})
        response.raise_for_status()
        return response.json()


@st.cache_data(ttl=30, show_spinner=False)
def load_validation_analytics(
    store_key: str,
    store_id: str,
    metric_date_iso: str,
) -> dict[str, Any]:
    """Analytics bundle from the selected validation SQLite database (in-process)."""
    return load_analytics_from_validation_db(
        store_key,
        store_id,
        date.fromisoformat(metric_date_iso),
    )


def fetch_store_ids() -> list[str]:
    try:
        health = fetch_json("/health")
        store_ids = [row["store_id"] for row in health.get("stores", []) if row.get("store_id")]
        if store_ids:
            return sorted(set(store_ids))
    except httpx.HTTPError:
        pass
    return [DEFAULT_STORE_ID]


def funnel_stage_count(funnel: dict[str, Any], stage_key: str) -> int:
    for stage in funnel.get("stages", []):
        if stage.get("stage") == stage_key:
            return int(stage.get("count", 0))
    return 0


def format_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def format_inr(value: float) -> str:
    return f"₹{value:,.2f}"


def format_dwell_ms(ms: float) -> str:
    if ms <= 0:
        return "0 seconds"
    seconds = ms / 1000.0
    if seconds < 60:
        return f"{seconds:.0f} seconds"
    return f"{int(seconds // 60)} min {seconds % 60:.0f} sec"


def friendly_zone(zone_id: str) -> str:
    if not zone_id or zone_id == "—":
        return "—"
    return zone_id.replace("_", " ").strip().title()


def dwell_customer_language(ms: float) -> str:
    if ms <= 0:
        return "Customers spend very little time in this area"
    seconds = ms / 1000.0
    if seconds < 20:
        return "Customers spend very little time in this area"
    if seconds < 60:
        return f"Customers spend about {seconds:.0f} seconds here on average"
    minutes = int(seconds // 60)
    return f"Customers spend about {minutes} minute{'s' if minutes != 1 else ''} here on average"


def area_interest_language(score: float, visits: int, dwell_ms: float) -> str:
    if visits == 0:
        return "Very few customers visited this area today"
    if score < 15:
        return f"{dwell_customer_language(dwell_ms).rstrip('.')}, with only {visits} visit{'s' if visits != 1 else ''} recorded"
    if score < 40:
        return (
            f"Moderate interest — {visits} visit{'s' if visits != 1 else ''}. "
            f"{dwell_customer_language(dwell_ms)}."
        )
    return (
        f"Strong interest — {visits} visit{'s' if visits != 1 else ''}. "
        f"{dwell_customer_language(dwell_ms)}."
    )


def humanize_alert_title(title: str) -> str:
    raw = (title or "").strip()
    lower = raw.lower()
    if "dead zone" in lower:
        zone_part = raw.split(":")[-1].strip() if ":" in raw else ""
        name = friendly_zone(zone_part) if zone_part else "This product area"
        if "critical" in lower:
            return f"{name} needs urgent attention"
        return f"{name} needs attention"
    if "conversion drop" in lower or "conversion" in lower and "drop" in lower:
        return "Fewer customers are completing purchases than expected"
    if "queue spike" in lower or "billing queue" in lower:
        return "Checkout lines are getting busy"
    return raw.replace("Critical ", "").replace(" detected", "").strip() or "Something on the floor needs attention"


def humanize_alert_description(description: str, *, unique_visitors: int) -> str:
    text = (description or "").strip()
    if not text:
        if unique_visitors <= 5:
            return (
                f"Only {unique_visitors} customer visit{'s' if unique_visitors != 1 else ''} "
                "today — patterns may change as more shoppers arrive"
            )
        return "Today's activity shows a pattern to fix before the next busy period"
    replacements = (
        ("normalized score", "customer interest"),
        ("normalized engagement score", "customer interest"),
        ("engagement score", "customer interest"),
        ("threshold", "expected level"),
        ("dead zone", "underused area"),
        ("conversion rate", "share of visitors who bought"),
        ("conversion efficiency", "share of visitors who bought"),
        ("queue joins", "customers joining the checkout line"),
        ("planogram", "product layout"),
    )
    result = text
    for old, new in replacements:
        result = result.replace(old, new)
    return result


def text_to_bullets(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    cleaned = text.replace(";", ".").replace("—", ".")
    parts: list[str] = []
    for chunk in cleaned.split("."):
        line = chunk.strip()
        if line:
            parts.append(line[0].upper() + line[1:] if len(line) > 1 else line)
    return parts



def dedupe_action_items(items: list[str]) -> list[str]:
    """Remove near-duplicate actions (case-insensitive) for cleaner UI."""
    def norm(text: str) -> str:
        s = (text or "").strip().lower()
        if not s:
            return ""
        # unify a few common checkout synonyms
        s = s.replace("billing lane", "checkout lane")
        s = s.replace("billing counter", "checkout lane")
        s = s.replace("another", "extra")
        s = s.replace("additional", "extra")
        s = s.replace("during busy periods", "during peak periods")
        s = s.replace("during busy hours", "during peak periods")
        s = s.replace("busy periods", "peak periods")
        s = "".join(ch for ch in s if ch.isalnum() or ch.isspace())
        return " ".join(s.split())

    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = norm(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


def priority_label(severity: str) -> str:
    if severity == "CRITICAL":
        return "High"
    if severity == "WARN":
        return "Medium"
    return "Low"


def _scrub_action_text(text: str) -> str:
    replacements = (
        ("planogram", "product layout"),
        ("POS", "checkout"),
        ("deploy additional billing staff", "add staff at checkout"),
        ("express checkout lanes", "a faster checkout lane"),
        ("Review product layout, signage and staffing", "Improve product visibility near billing"),
    )
    result = text
    for old, new in replacements:
        result = result.replace(old, new)
    return result


def retail_action_phrases(suggested: str, zone: str = "") -> list[str]:
    text = (suggested or "").strip().lower()
    if not text:
        if zone and "billing" in zone.lower():
            return [
                "Improve product visibility near billing",
                "Add promotional displays",
                "Place best-selling products closer to checkout",
            ]
        return ["Walk the floor with staff and clear the path to checkout"]

    if any(k in text for k in ("planogram", "dead zone", "underperforming", "signage and staffing")):
        return [
            "Improve product visibility near billing",
            "Add promotional displays",
            "Place best-selling products closer to checkout",
        ]
    if any(k in text for k in ("billing staff", "checkout lane", "wait time", "queue")):
        return [
            "Add staff at checkout during busy periods",
            "Open a faster checkout lane",
            "Keep impulse items visible near the till",
        ]
    if any(k in text for k in ("conversion", "friction", "pricing", "checkout")):
        return [
            "Check pricing signs at checkout",
            "Make sure tills are staffed and easy to find",
            "Clear the path from busy areas to billing",
        ]
    return text_to_bullets(_scrub_action_text(suggested))


def suggested_action_plain(suggested: str, zone: str = "") -> str:
    return ". ".join(retail_action_phrases(suggested, zone=zone))


def store_status_label(health: dict[str, Any], db_ok: bool) -> tuple[str, str]:
    """Return (label, css_class) for store operational health."""
    status = str(health.get("status", "")).lower()
    if not db_ok or status not in ("ok", "healthy"):
        return "Needs Attention", "warn"
    return "Healthy", "ok"


def analytics_status_label(db_ok: bool, feed_stale: bool) -> tuple[str, str]:
    if not db_ok:
        return "Unavailable", "bad"
    if feed_stale:
        return "Delayed", "warn"
    return "Updated", "ok"


def camera_activity_label(feed_stale: bool) -> tuple[str, str]:
    if feed_stale:
        return "No Recent Updates", "warn"
    return "Receiving Events", "ok"


def data_confidence_display(
    unique_visitors: int,
    has_confidence: bool,
    *,
    events_processed: int,
) -> tuple[str, str, str]:
    """Return (headline, supporting line, css_class) without truncation."""
    if unique_visitors == 0:
        return "No Data Yet", "0 visitors analysed", "bad"
    if unique_visitors <= 5 or not has_confidence:
        return (
            "Limited Confidence",
            f"{unique_visitors:,} visitors analysed",
            "warn",
        )
    if has_confidence and unique_visitors >= 20:
        return (
            "High Confidence",
            f"{unique_visitors:,} visitors analysed · {events_processed:,} events processed",
            "ok",
        )
    return (
        "Moderate Confidence",
        f"{unique_visitors:,} visitors analysed",
        "warn",
    )


def estimate_events_processed(
    heatmap: dict[str, Any],
    total_sessions: int,
    funnel: dict[str, Any],
) -> int:
    """
    Presentation-layer estimate from API payloads (no extra backend fields).

    Approximates ingested events: entry/exit per session, zone dwell visits,
    and checkout queue joins for the selected day.
    """
    zone_visits = sum(int(z.get("visit_count", 0)) for z in heatmap.get("zones", []))
    queue_joins = funnel_stage_count(funnel, "billing_queue")
    return max(0, total_sessions * 2 + zone_visits + queue_joins)



def format_utc_timestamp(value: str | None) -> str:
    if not value:
        return "—"
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return value


def store_feed_status(health: dict[str, Any], store_id: str) -> dict[str, Any] | None:
    for row in health.get("stores", []):
        if row.get("store_id") == store_id:
            return row
    return None


def is_billing_zone(zone_id: str) -> bool:
    return "BILLING" in (zone_id or "").upper()


def split_zone_performance(
    ranked: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Top product areas vs lowest-engagement product area (BILLING excluded)."""
    if not ranked:
        return [], None
    attention = ranked[-1]
    top = ranked[:-1]
    return top, attention


def zone_rankings(heatmap: dict[str, Any]) -> list[dict[str, Any]]:
    """Rank product/browse zones only — checkout is handled separately."""
    zones = [
        z
        for z in heatmap.get("zones", [])
        if not is_billing_zone(str(z.get("zone_id", "")))
    ]
    return sorted(
        [
            {
                "zone_id": z.get("zone_id", ""),
                "visits": int(z.get("visit_count", 0)),
                "score": float(z.get("normalized_score", 0)),
                "dwell_ms": float(z.get("average_dwell_time_ms", 0)),
            }
            for z in zones
        ],
        key=lambda x: x["score"],
        reverse=True,
    )


def build_checkout_performance(
    *,
    peak_queue_depth: int,
    queue_abandonment: float,
    reached_checkout_count: int,
    completed_purchase_count: int,
) -> CheckoutPerformance:
    """Manager-friendly checkout summary from operational checkout metrics."""
    lost_before_purchase = max(0, reached_checkout_count - completed_purchase_count)
    needs_attention = queue_abandonment >= 0.20 or peak_queue_depth >= 4 or lost_before_purchase >= 10

    if needs_attention:
        bullets: list[str] = []
        if queue_abandonment >= 0.15:
            bullets.append(
                f"Queue abandonment is {format_pct(queue_abandonment)} — "
                "several customers left the checkout line before purchasing."
            )
        if peak_queue_depth > 0:
            bullets.append(
                f"Peak queues reached {peak_queue_depth} customers during busy periods."
            )
        if completed_purchase_count > 0:
            bullets.append(
                f"{completed_purchase_count} customers completed purchases after reaching checkout."
            )
        if lost_before_purchase > 0:
            bullets.append(
                f"{lost_before_purchase} customers reached checkout but did not complete a purchase."
            )
        if not bullets:
            bullets.append(
                "Checkout metrics suggest reviewing staffing and line speed."
            )
        return CheckoutPerformance(
            status="attention",
            headline="Checkout needs attention",
            bullets=bullets,
        )

    bullets = [
        "Checkout performing smoothly.",
        "Queue abandonment remains low.",
    ]
    if peak_queue_depth > 0:
        bullets.append(f"Peak queues stayed manageable (peak {peak_queue_depth}).")
    if completed_purchase_count > 0:
        bullets.append(f"{completed_purchase_count} customers completed purchases after reaching checkout.")
    if lost_before_purchase > 0:
        bullets.append(f"{lost_before_purchase} customers reached checkout but did not complete a purchase.")
    return CheckoutPerformance(
        status="healthy",
        headline="Checkout performing well",
        bullets=bullets,
    )


def funnel_drop_offs(funnel: dict[str, Any]) -> dict[str, int]:
    uv = funnel_stage_count(funnel, "unique_visitors")
    rz = funnel_stage_count(funnel, "reached_any_zone")
    bq = funnel_stage_count(funnel, "billing_queue")
    cv = funnel_stage_count(funnel, "converted_visitors")
    return {
        "pre_zone": max(0, uv - rz),
        "pre_billing": max(0, rz - bq),
        "no_purchase": max(0, bq - cv),
        "visitors": uv,
        "zone_engaged": rz,
        "billing": bq,
        "purchased": cv,
    }


def _next_step_action(
    *,
    alert_list: list[dict[str, Any]],
    drops: dict[str, int],
    unique_visitors: int,
    conversion_rate: float,
    queue_abandonment: float,
    billing_reach_rate: float,
    top_zone: str,
    weak_zone: str,
    ranked: list[dict[str, Any]],
    purchase_count: int,
) -> list[str]:
    top_score = ranked[0]["score"] if ranked else 0.0
    weak_score = ranked[-1]["score"] if ranked else 0.0

    if alert_list:
        return retail_action_phrases(
            str(alert_list[0].get("suggested_action", "")),
            zone=str(alert_list[0].get("title", "")).split(":")[-1].strip(),
        )
    if drops["visitors"] > 0 and drops["pre_billing"] >= max(1, drops["zone_engaged"] // 2):
        return text_to_bullets(
            f"Station staff near {friendly_zone(top_zone)} to guide customers to checkout. "
            "Check signs and aisles to the tills."
        )
    if conversion_rate < 0.25:
        return text_to_bullets(
            "Walk from entrance to till during a busy hour. "
            "Remove anything that blocks or confuses the path to pay."
        )
    if queue_abandonment > 0.25:
        return text_to_bullets(
            "Add a second billing counter or speed up service before the next rush."
        )
    if billing_reach_rate < 0.5:
        return text_to_bullets(
            f"Guide customers from {friendly_zone(top_zone)} to checkout with signs and staff prompts."
        )
    if ranked and weak_score < top_score * 0.6:
        return text_to_bullets(
            f"Refresh displays in {friendly_zone(weak_zone)}. "
            f"Copy what works in {friendly_zone(top_zone)}."
        )
    if purchase_count == 0:
        return text_to_bullets(
            "Check prices, stock, and checkout staffing. Ask staff what stopped customers from buying."
        )
    return text_to_bullets(
        f"Keep checkout staffed. Test one display change in {friendly_zone(weak_zone)} this week."
    )


def build_store_summary(
    *,
    selected_date: date,
    funnel: dict[str, Any],
    unique_visitors: int,
    purchase_count: int,
    conversion_rate: float,
    total_revenue_inr: float,
    top_zone: str,
    weak_zone: str,
    anomalies: dict[str, Any],
    ranked: list[dict[str, Any]],
    billing_reach_rate: float,
    queue_abandonment: float,
) -> StoreSummary:
    alert_list = anomalies.get("anomalies", [])
    drops = funnel_drop_offs(funnel)

    if unique_visitors == 0:
        return StoreSummary(
            happened=[
                f"No customers counted on {selected_date.strftime('%d %b %Y')}",
                "Sales and shopping journey cannot be shown for this day",
            ],
            next_steps=text_to_bullets(
                "Confirm the store was open and busy. "
                "If it was, ask support to verify customer counting."
            ),
        )

    happened = [
        f"{unique_visitors:,} customers entered the store",
        f"{purchase_count:,} completed a purchase",
        f"{format_inr(total_revenue_inr)} total sales",
        f"{format_pct(conversion_rate)} of visitors bought something",
        f"Strongest area: {friendly_zone(top_zone)}",
        f"Lowest product-area interest: {friendly_zone(weak_zone)}",
    ]
    if purchase_count > 0:
        happened.append(f"Average spend per purchase: {format_inr(total_revenue_inr / purchase_count)}")
    if drops["pre_zone"] > 0:
        happened.append(f"{drops['pre_zone']} left before browsing product areas")
    if drops["pre_billing"] > 0:
        happened.append(f"{drops['pre_billing']} browsed but did not reach checkout")
    if drops["no_purchase"] > 0:
        happened.append(f"{drops['no_purchase']} reached checkout without buying")

    next_steps = _next_step_action(
        alert_list=alert_list,
        drops=drops,
        unique_visitors=unique_visitors,
        conversion_rate=conversion_rate,
        queue_abandonment=queue_abandonment,
        billing_reach_rate=billing_reach_rate,
        top_zone=top_zone,
        weak_zone=weak_zone,
        ranked=ranked,
        purchase_count=purchase_count,
    )
    return StoreSummary(happened=happened, next_steps=next_steps)


def build_business_insights(
    *,
    anomalies: dict[str, Any],
    funnel: dict[str, Any],
    ranked: list[dict[str, Any]],
    unique_visitors: int,
    conversion_rate: float,
    queue_abandonment: float,
    weak_zone: str,
) -> list[BusinessInsight]:
    insights: list[BusinessInsight] = []
    drops = funnel_drop_offs(funnel)

    for anomaly in anomalies.get("anomalies", [])[:3]:
        title = str(anomaly.get("title", ""))
        zone_hint = title.split(":")[-1].strip() if ":" in title else weak_zone
        if (
            str(anomaly.get("anomaly_type", "")) == "DEAD_ZONE"
            and is_billing_zone(zone_hint)
        ):
            continue
        insights.append(
            BusinessInsight(
                problem=humanize_alert_title(title),
                evidence=humanize_alert_description(
                    str(anomaly.get("description", "")), unique_visitors=unique_visitors
                ),
                action=". ".join(retail_action_phrases(str(anomaly.get("suggested_action", "")), zone=zone_hint)),
                priority=priority_label(str(anomaly.get("severity", "WARN"))),
                severity=str(anomaly.get("severity", "WARN")),
            )
        )

    if unique_visitors > 0 and conversion_rate < 0.3 and len(insights) < 4:
        if not any("purchase" in i.problem.lower() for i in insights):
            insights.append(
                BusinessInsight(
                    problem="Too few visitors are buying",
                    evidence=(
                        f"Only {format_pct(conversion_rate)} of today's {unique_visitors} "
                        f"customer{'s' if unique_visitors != 1 else ''} made a purchase."
                    ),
                    action=(
                        "Walk from entrance to checkout during a busy hour. "
                        "Keep the path clear and help hesitant shoppers."
                    ),
                    priority="Medium",
                    severity="WARN",
                )
            )

    rz = drops["zone_engaged"]
    bq = drops["billing"]
    if unique_visitors > 0 and rz > 0 and (rz - bq) >= max(1, rz // 2) and len(insights) < 4:
        insights.append(
            BusinessInsight(
                problem="Many shoppers browse but do not reach checkout",
                evidence=(
                    f"{drops['pre_billing']} customer{'s' if drops['pre_billing'] != 1 else ''} "
                    f"browsed products but did not reach checkout, out of {rz} who shopped the floor."
                ),
                action=(
                    "Add clear signs and staff prompts from busy areas to checkout. "
                    "Make sure checkout is easy to find."
                ),
                priority="Low",
                severity="INFO",
            )
        )

    if queue_abandonment > 0.2 and len(insights) < 4:
        insights.append(
            BusinessInsight(
                problem="Customers are leaving the checkout line without buying",
                evidence=(
                    f"{format_pct(queue_abandonment)} of customers who joined the line "
                    "left before completing a purchase — wait time may be too long."
                ),
                action="Open another billing counter or speed up service before the next rush.",
                priority="Medium",
                severity="WARN",
            )
        )

    if weak_zone and ranked and len(insights) < 4:
        weak = ranked[-1]
        if is_billing_zone(weak_zone):
            pass
        elif not any(friendly_zone(weak_zone) in i.problem for i in insights):
            insights.append(
                BusinessInsight(
                    problem=f"{friendly_zone(weak_zone)} receives the least customer interest",
                    evidence=area_interest_language(
                        weak["score"], weak["visits"], weak["dwell_ms"]
                    ),
                    action=(
                        f"Refresh displays and signage in {friendly_zone(weak_zone)}. "
                        f"Copy layout ideas from {friendly_zone(ranked[0]['zone_id'])}."
                    ),
                    priority="Low",
                    severity="INFO",
                )
            )

    if not insights:
        insights.append(
            BusinessInsight(
                problem="No urgent issues flagged for today",
                evidence="Sales, checkout, and product areas are within a normal range for this day.",
                action="Keep current staffing and watch checkout during peak hours.",
                priority="Low",
                severity="INFO",
            )
        )

    return insights[:4]




def checkout_status_pill(metric: str, value: float | int) -> str:
    """Presentation-only status labels for checkout KPI cards."""
    if metric == "queue_depth":
        if int(value) <= 2:
            return "excellent"
        if int(value) <= 4:
            return "healthy"
        return "warning"
    if metric == "abandonment":
        if float(value) < 0.10:
            return "excellent"
        if float(value) < 0.20:
            return "healthy"
        return "warning"
    if metric == "reached":
        if int(value) >= 20:
            return "excellent"
        if int(value) >= 5:
            return "healthy"
        return "warning"
    if int(value) >= 10:
        return "excellent"
    if int(value) >= 1:
        return "healthy"
    return "warning"



def main() -> None:
    st.set_page_config(
        page_title="Purpple Vision",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_saas_styles()

    with st.sidebar:
        st.markdown(sidebar_brand_html(), unsafe_allow_html=True)

        store_options = dashboard_store_options()
        store_labels = [option.label for option in store_options]
        label_to_option = {option.label: option for option in store_options}

        default_index = 0
        try:
            default_index = next(
                i
                for i, option in enumerate(store_options)
                if option.store_key == DEFAULT_STORE_KEY
            )
        except StopIteration:
            pass

        st.markdown('<div class="glass-panel"><div class="gp-label">Store</div></div>', unsafe_allow_html=True)
        selected_label = st.selectbox("Store location", store_labels, index=default_index, label_visibility="collapsed")
        store_option = label_to_option[selected_label]
        store_id = store_option.store_id
        store_key = store_option.store_key

        available_dates = list_event_dates_from_db(
            store_option.database_path,
            store_option.store_id,
        )
        if not available_dates:
            st.error(
                f"No events in {store_option.database_path.name}. "
                f"Run: {missing_database_hint(store_option)}"
            )
            st.stop()

        preferred_default = store_option.default_metric_date
        if preferred_default not in available_dates:
            preferred_default = available_dates[-1]

        date_labels = [day.isoformat() for day in available_dates]
        if (
            "metric_date_iso" not in st.session_state
            or st.session_state.metric_date_iso not in date_labels
            or st.session_state.get("store_key") != store_key
        ):
            st.session_state.store_key = store_key
            st.session_state.metric_date_iso = preferred_default.isoformat()

        date_index = date_labels.index(st.session_state.metric_date_iso)
        st.markdown('<div class="glass-panel"><div class="gp-label">Trading day</div></div>', unsafe_allow_html=True)
        selected_date_iso = st.selectbox("Date", date_labels, index=date_index, label_visibility="collapsed")
        st.session_state.metric_date_iso = selected_date_iso
        st.session_state.store_key = store_key
        selected_date = date.fromisoformat(selected_date_iso)
        date_param = selected_date_iso

        if use_api_client():
            st.caption("Data source: API")
            st.caption(f"API: {api_base_url_for_store(store_key)}")
            st.caption(
                "Set the API server DATABASE_URL to match the selected store database."
            )
        else:
            try:
                bind_validation_database(store_key)
            except FileNotFoundError as exc:
                st.error(str(exc))
                st.stop()
            if store_option.is_intelligence_db:
                pass
            else:
                st.caption("Data source: Validation DB")
                st.caption(f"Database: {store_option.database_path.name}")

        if st.button("Refresh", type="primary", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    params = {"date": date_param}
    staff_analysis: dict[str, Any] | None = None
    business_insights: dict[str, Any] | None = None

    try:
        if use_api_client():
            api_root = api_base_url_for_store(store_key)
            health = fetch_json("/health", base_url=api_root)
            metrics = fetch_json(
                f"/stores/{store_id}/metrics", params, base_url=api_root
            )
            funnel = fetch_json(
                f"/stores/{store_id}/funnel", params, base_url=api_root
            )
            heatmap = fetch_json(
                f"/stores/{store_id}/heatmap", params, base_url=api_root
            )
            anomalies = fetch_json(
                f"/stores/{store_id}/anomalies", params, base_url=api_root
            )
            try:
                staff_analysis = fetch_json(
                    f"/stores/{store_id}/staff-analysis",
                    params,
                    base_url=api_root,
                )
            except httpx.HTTPError:
                staff_analysis = None
        else:
            bundle = load_validation_analytics(store_key, store_id, date_param)
            health = bundle["health"]
            metrics = bundle["metrics"]
            funnel = bundle["funnel"]
            heatmap = bundle["heatmap"]
            anomalies = bundle["anomalies"]
            staff_analysis = bundle.get("staff_analysis")
            business_insights = bundle.get("business_insights")
    except FileNotFoundError as exc:
        st.error(str(exc))
        return
    except httpx.ConnectError:
        st.error(
            "Unable to load store data. Please ensure the store system is running, then refresh."
        )
        return
    except httpx.HTTPStatusError:
        st.error("Store data could not be loaded. Please try again or pick another date.")
        return
    except httpx.HTTPError:
        st.error("Something went wrong while loading the dashboard. Please refresh.")
        return
    except Exception as exc:
        st.error(f"Failed to load analytics: {exc}")
        return

    if business_insights is None and use_api_client():
        try:
            business_insights = fetch_json(
                f"/stores/{store_id}/business-insights",
                params,
                base_url=api_base_url_for_store(store_key),
            )
        except httpx.HTTPError:
            business_insights = None

    if not health.get("database_available", False):
        if is_cctv_real_store(store_key):
            st.error(
                f"CCTV intelligence database is not available. "
                f"{missing_database_hint(store_option)}"
            )
        else:
            st.error(
                "Store sales records are temporarily unavailable. Please try again shortly."
            )
        st.stop()

    if is_cctv_real_store(store_key):
        render_cctv_real_dashboard(
            store_key=store_key,
            store_label=selected_label,
            store_id=store_id,
            metric_date=selected_date,
            metrics=metrics,
            funnel=funnel,
            heatmap=heatmap,
            anomalies=anomalies,
            health=health,
            friendly_zone_fn=friendly_zone,
            format_dwell_fn=format_dwell_ms,
            business_insights=business_insights,
        )
        render_technical_panel(
            health=health,
            metrics=metrics,
            funnel=funnel,
            heatmap=heatmap,
            anomalies=anomalies,
            business_insights=business_insights,
            staff_analysis=staff_analysis,
            verification_mode=True,
        )
        return

    unique_visitors = int(metrics.get("unique_visitors", 0))
    total_sessions = int(metrics.get("total_sessions", 0))
    conversion_rate = float(metrics.get("conversion_rate", 0.0))
    total_revenue_inr = float(metrics.get("total_revenue_inr", 0.0))
    queue_depth = int(metrics.get("current_queue_depth", 0))
    queue_abandonment = float(metrics.get("queue_abandonment_rate", 0.0))
    billing_reach_rate = float(metrics.get("billing_reach_rate", 0.0))
    avg_session_dwell_ms = float(metrics.get("average_dwell_time_ms", 0.0))
    purchase_count = funnel_stage_count(funnel, "converted_visitors")
    reached_checkout_count = funnel_stage_count(funnel, "billing_queue")

    checkout_ctx = (
        (business_insights or {}).get("context", {}).get("checkout", {})
        if business_insights
        else {}
    )
    peak_queue_depth = int(checkout_ctx.get("peak_queue_depth", queue_depth) or 0)
    completed_purchase_count = int(
        checkout_ctx.get("completed_purchase_count", purchase_count) or 0
    )
    reached_checkout_count = int(
        checkout_ctx.get("reached_checkout_count", reached_checkout_count) or 0
    )

    ranked = zone_rankings(heatmap)
    top_areas, attention_zone = split_zone_performance(ranked)
    top_zone = top_areas[0]["zone_id"] if top_areas else (ranked[0]["zone_id"] if ranked else "—")
    weak_zone = attention_zone["zone_id"] if attention_zone else "—"

    _, store_css = store_status_label(health, bool(health.get("database_available", False)))
    header_status = (
        "All systems operational"
        if store_css == "ok"
        else ("Partial degradation" if store_css == "warn" else "Attention required")
    )
    st.markdown(
        hero_header_html(
            selected_label,
            store_id,
            selected_date,
            visitors=unique_visitors,
            revenue_text=format_inr(total_revenue_inr),
            conversion_text=format_pct(conversion_rate),
            status_label=header_status,
            status_css=store_css,
        ),
        unsafe_allow_html=True,
    )

    insight_data = (business_insights or {}).get("insights") or {}
    store_summary = str(insight_data.get("store_summary") or "").strip()
    manager_actions = insight_data.get("manager_actions") or []
    if not store_summary:
        store_summary = (
            f"{unique_visitors:,} customers visited on "
            f"{selected_date.strftime('%d %b %Y')} at {store_id}."
        )
    if not manager_actions:
        manager_actions = [
            "Review checkout staffing during peak hours.",
            "Walk the store path from entrance to till.",
            "Refresh displays in the lowest-performing product area.",
        ]
    manager_actions = dedupe_action_items([str(x) for x in manager_actions])

    render_executive_metrics(
        unique_visitors=unique_visitors,
        purchase_count=purchase_count,
        revenue_text=format_inr(total_revenue_inr),
        conversion_text=format_pct(conversion_rate),
        top_zone=friendly_zone(top_zone),
        weak_zone=friendly_zone(weak_zone),
        conversion_rate=conversion_rate,
    )
    render_todays_story(store_summary, conversion_rate)
    render_recommended_actions(manager_actions)

    if total_sessions == 0:
        st.warning(
            "No customer shopping activity was recorded for this day. "
            "Choose another date or confirm the store was open."
        )
    else:
        render_customer_journey(
            funnel,
            stage_count_fn=funnel_stage_count,
            funnel_drop_offs_fn=funnel_drop_offs,
            format_pct_fn=format_pct,
        )
        render_floor_intelligence(
            ranked,
            friendly_zone_fn=friendly_zone,
            format_dwell_fn=format_dwell_ms,
        )
        checkout = build_checkout_performance(
            peak_queue_depth=peak_queue_depth,
            queue_abandonment=queue_abandonment,
            reached_checkout_count=reached_checkout_count,
            completed_purchase_count=completed_purchase_count,
        )
        checkout_insight = (business_insights or {}).get("insights") or {}
        checkout_summary = str(checkout_insight.get("checkout_summary") or "").strip()
        checkout_actions = checkout_insight.get("checkout_actions") or []
        if not checkout_summary and checkout.headline:
            checkout_summary = checkout.headline
        render_checkout_command_center(
            peak_queue_depth=peak_queue_depth,
            queue_abandonment=queue_abandonment,
            queue_abandonment_text=format_pct(queue_abandonment),
            reached_checkout_count=reached_checkout_count,
            completed_purchase_count=completed_purchase_count,
            checkout_status_pill_fn=checkout_status_pill,
            checkout_summary=checkout_summary,
            checkout_actions=dedupe_action_items([str(x) for x in checkout_actions]),
            checkout_bullets=checkout.bullets,
        )

    render_ai_insights(business_insights)

    events_processed = estimate_events_processed(heatmap, total_sessions, funnel)
    has_confidence = bool(heatmap.get("data_confidence", False))

    feed = store_feed_status(health, store_id)
    feed_stale = bool(feed.get("stale", False)) if feed else False
    db_ok = bool(health.get("database_available", False))
    last_activity = format_utc_timestamp(feed.get("last_event_at") if feed else None)
    _, store_css = store_status_label(health, db_ok)
    _, analytics_css = analytics_status_label(db_ok, feed_stale)
    _, camera_css = camera_activity_label(feed_stale)
    _, confidence_sub, confidence_css = data_confidence_display(
        unique_visitors,
        has_confidence,
        events_processed=events_processed,
    )
    store_display = "Operational" if store_css == "ok" else (
        "Degraded" if store_css == "warn" else "Issue"
    )
    analytics_display = "Operational" if analytics_css == "ok" else (
        "Degraded" if analytics_css == "warn" else "Issue"
    )
    camera_display = "Operational" if camera_css == "ok" else (
        "Degraded" if camera_css == "warn" else "Issue"
    )
    confidence_display = "Operational" if confidence_css == "ok" else (
        "Degraded" if confidence_css == "warn" else "Issue"
    )
    facts = [
        f"Visitors analyzed: {unique_visitors:,}",
        f"Sessions created: {total_sessions:,}",
        f"Events processed: {events_processed:,}",
        f"POS transactions: {purchase_count:,}",
        f"Last activity timestamp: {last_activity}",
    ]
    if queue_depth > 0:
        facts.append(f"Customers waiting at checkout: {queue_depth:,}")
    facts.append(f"Typical time in store: {format_dwell_ms(avg_session_dwell_ms)}")

    render_operations_monitoring(
        store_display=store_display,
        store_css=store_css,
        analytics_display=analytics_display,
        analytics_css=analytics_css,
        camera_display=camera_display,
        camera_css=camera_css,
        confidence_display=confidence_display,
        confidence_css=confidence_css,
        confidence_sub=confidence_sub,
        last_activity=last_activity,
        facts=facts,
    )
    render_trust_center(
        unique_visitors=unique_visitors,
        total_sessions=total_sessions,
        events_processed=events_processed,
        pos_transactions=purchase_count,
        revenue_text=format_inr(total_revenue_inr),
        api_loaded=True,
        has_confidence=has_confidence,
    )
    render_technical_panel(
        health=health,
        metrics=metrics,
        funnel=funnel,
        heatmap=heatmap,
        anomalies=anomalies,
        business_insights=business_insights,
        staff_analysis=staff_analysis,
    )


if __name__ == "__main__":
    main()
