"""Streamlit web dashboard for store intelligence metrics (Part E bonus)."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any

import httpx
import pandas as pd
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
DEFAULT_STORE_ID = os.getenv("DEFAULT_STORE_ID", "STORE_BLR_002")
DEFAULT_METRIC_DATE = os.getenv("DEFAULT_METRIC_DATE", "2026-04-10")

FUNNEL_LABELS: dict[str, str] = {
    "unique_visitors": "Visitors (entry)",
    "reached_any_zone": "Engaged (zone visit)",
    "billing_queue": "Billing queue",
    "converted_visitors": "Purchased (POS)",
}

FUNNEL_DESCRIPTIONS: dict[str, str] = {
    "unique_visitors": "Unique customers with an ENTRY or REENTRY — funnel denominator; re-entries do not double-count.",
    "reached_any_zone": "Visitors who entered at least one product zone (shelf engagement).",
    "billing_queue": "Visitors who joined the billing queue (BILLING_QUEUE_JOIN).",
    "converted_visitors": "Visitors correlated to a POS transaction within 5 minutes after billing activity.",
}

METRIC_HELP: dict[str, str] = {
    "Visitors": "Unique non-staff visitors for the UTC day (`/metrics unique_visitors`).",
    "Sessions": "Customer sessions opened on ENTRY/REENTRY (`/metrics total_sessions`).",
    "Revenue (INR)": "Sum of POS basket_value_inr for the UTC day (`/metrics total_revenue_inr`).",
    "Conversion rate": "North Star — converted visitors ÷ unique visitors (`/metrics conversion_rate`).",
    "Queue depth": "Latest non-staff BILLING_QUEUE_JOIN queue_depth for the day (`/metrics current_queue_depth`).",
    "Queue abandonment": "Share of queue joins that left before purchase (`/metrics queue_abandonment_rate`).",
    "Avg session dwell": "Mean total in-zone dwell per customer session (`/metrics average_dwell_time_ms`).",
}

SECTION_INTROS: dict[str, str] = {
    "health": (
        "Operational status from `GET /health` — service availability, last ingested event, "
        "and STALE_FEED warnings when CCTV ingest lag exceeds 10 minutes."
    ),
    "funnel": (
        "Session-based conversion funnel from `GET /funnel` — Entry → Zone visit → Billing → Purchase. "
        "Drop-off % shows where customers leave the journey."
    ),
    "heatmap": (
        "Zone engagement from `GET /heatmap` — visit frequency and dwell normalized 0–100. "
        "Compare zones that attract attention vs. billing conversion."
    ),
    "anomalies": (
        "Active alerts from `GET /anomalies` — queue spikes, conversion drops, and dead zones "
        "with severity and suggested actions for store staff."
    ),
    "dwell": (
        "Per-zone dwell averages from `GET /metrics average_dwell_by_zone` — "
        "mean milliseconds spent in each zone across customer session visits."
    ),
}

ANOMALY_GROUPS: dict[str, tuple[str, ...]] = {
    "Queue alerts": ("QUEUE_SPIKE",),
    "Low conversion alerts": ("CONVERSION_DROP",),
    "Unusual traffic alerts": ("DEAD_ZONE",),
}

SEVERITY_ICONS: dict[str, str] = {
    "CRITICAL": "🔴",
    "WARN": "🟡",
    "INFO": "🔵",
}


@st.cache_data(ttl=30, show_spinner=False)
def fetch_json(path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    """GET JSON from the Store Intelligence API."""
    url = f"{API_BASE_URL}{path}"
    with httpx.Client(timeout=15.0) as client:
        response = client.get(url, params=params or {})
        response.raise_for_status()
        return response.json()


def fetch_store_ids() -> list[str]:
    """Load store IDs from GET /health; fall back to default store."""
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


def format_utc_timestamp(value: str | None) -> str:
    """Format an ISO-8601 UTC timestamp for display."""
    if not value:
        return "—"
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return value


def store_feed_status(health: dict[str, Any], store_id: str) -> dict[str, Any] | None:
    for row in health.get("stores", []):
        if row.get("store_id") == store_id:
            return row
    return None


def render_health_panel(health: dict[str, Any], store_id: str) -> None:
    """System health from GET /health — status, last event, stale feed warnings."""
    st.subheader("System health")
    st.caption(SECTION_INTROS["health"])

    service_status = str(health.get("status", "unknown"))
    db_ok = bool(health.get("database_available", False))
    feed = store_feed_status(health, store_id)
    last_event_at = feed.get("last_event_at") if feed else None
    feed_stale = bool(feed.get("stale", False)) if feed else False
    warnings: list[str] = list(health.get("warnings", []))
    stale_warnings = [w for w in warnings if w.startswith("STALE_FEED")]

    status_col, db_col, event_col, stale_col = st.columns(4)
    status_col.metric(
        "Service status",
        service_status.upper(),
        help="`ok` when database is reachable and no store feeds are stale; otherwise `degraded`.",
    )
    db_col.metric(
        "Database",
        "Available" if db_ok else "Unavailable",
        help="SQLite connectivity check from `/health`.",
    )
    event_col.metric(
        "Last event (UTC)",
        format_utc_timestamp(last_event_at),
        help="Business timestamp of the most recent ingested event for this store.",
    )
    stale_col.metric(
        "Feed status",
        "STALE" if feed_stale else "Live",
        help="STALE when no event was ingested within the configured lag threshold (default 10 min).",
    )

    if stale_warnings:
        for warning in stale_warnings:
            if store_id in warning or warning.endswith(f": {store_id}"):
                st.warning(
                    f"**{warning}** — CCTV event ingest lag exceeds threshold. "
                    "Analytics may not reflect current store activity."
                )
    elif feed_stale:
        st.warning(
            f"**STALE_FEED: {store_id}** — no recent event ingest for this store."
        )
    elif not db_ok:
        st.error("Database unavailable — analytics endpoints may return HTTP 503.")
    elif service_status == "ok":
        st.success("All health checks passed for the intelligence API.")


def format_dwell_ms(ms: float) -> str:
    if ms <= 0:
        return "0s"
    seconds = ms / 1000.0
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    rem = seconds % 60
    return f"{minutes}m {rem:.0f}s"


def render_anomaly_card(anomaly: dict[str, Any]) -> None:
    severity = str(anomaly.get("severity", "INFO"))
    icon = SEVERITY_ICONS.get(severity, "ℹ️")
    st.markdown(f"**{icon} {anomaly.get('title', 'Alert')}**")
    st.caption(anomaly.get("description", ""))
    if anomaly.get("suggested_action"):
        st.info(anomaly["suggested_action"])


def render_dwell_by_zone_table(metrics: dict[str, Any]) -> None:
    """Average dwell per zone from GET /metrics."""
    zones = metrics.get("average_dwell_by_zone", [])
    st.subheader("Average dwell by zone")
    st.caption(SECTION_INTROS["dwell"])

    if not zones:
        st.info(
            "No zone dwell averages for this date. Requires customer sessions with "
            "ZONE_ENTER or ZONE_DWELL events."
        )
        return

    rows = [
        {
            "Zone": z.get("zone_id", ""),
            "Avg dwell": format_dwell_ms(float(z.get("average_dwell_ms", 0.0))),
            "Avg dwell (ms)": float(z.get("average_dwell_ms", 0.0)),
        }
        for z in zones
    ]
    dwell_df = pd.DataFrame(rows).sort_values("Avg dwell (ms)", ascending=False)
    st.dataframe(
        dwell_df.drop(columns=["Avg dwell (ms)"]),
        use_container_width=True,
        hide_index=True,
    )


def render_heatmap_confidence_badge(heatmap: dict[str, Any], total_sessions: int) -> None:
    """Show data_confidence flag — LOW when fewer than 20 customer sessions."""
    confidence = bool(heatmap.get("data_confidence", False))
    if confidence:
        st.success(
            f"**Data confidence: HIGH** — {total_sessions} customer session(s) "
            "(≥20 required for reliable heatmap comparison)."
        )
    else:
        st.warning(
            f"**Data confidence: LOW** — {total_sessions} customer session(s) "
            "(<20). Heatmap zone scores may be unreliable per challenge spec."
        )


def render_empty_state(selected_date: date) -> None:
    st.warning(
        f"**No sessions found for selected date ({selected_date.isoformat()}).**\n\n"
        "Visitor sessions open on **ENTRY** or **REENTRY** events (typically from CAM3). "
        "The current pipeline demo dataset contains shelf zone events only, so analytics "
        "return zeros until entry/exit events are ingested.\n\n"
        "**Next steps:** run the CAM3 entry/exit pipeline, re-bridge pipeline output to "
        "SQLite, then refresh this dashboard."
    )


def main() -> None:
    st.set_page_config(
        page_title="Store Intelligence Dashboard",
        page_icon="📊",
        layout="wide",
    )

    st.title("Store Intelligence Dashboard")
    st.caption(
        "Offline store conversion intelligence (Part E) — North Star metric, funnel drop-offs, "
        "zone heatmap, queue signals, and anomalies from the FastAPI layer."
    )

    with st.sidebar:
        st.header("Filters")
        store_ids = fetch_store_ids()
        default_store_index = (
            store_ids.index(DEFAULT_STORE_ID) if DEFAULT_STORE_ID in store_ids else 0
        )
        store_id = st.selectbox("Store", store_ids, index=default_store_index)

        try:
            default_date = date.fromisoformat(DEFAULT_METRIC_DATE)
        except ValueError:
            default_date = datetime.now(timezone.utc).date()
        selected_date = st.date_input("Metric date (UTC)", value=default_date)
        date_param = selected_date.isoformat()

        st.divider()
        st.markdown("**API**")
        st.code(API_BASE_URL, language=None)
        if st.button("Refresh data", type="primary"):
            st.cache_data.clear()
            st.rerun()

    params = {"date": date_param}

    try:
        health = fetch_json("/health")
        metrics = fetch_json(f"/stores/{store_id}/metrics", params)
        funnel = fetch_json(f"/stores/{store_id}/funnel", params)
        heatmap = fetch_json(f"/stores/{store_id}/heatmap", params)
        anomalies = fetch_json(f"/stores/{store_id}/anomalies", params)
    except httpx.ConnectError:
        st.error(
            f"Cannot reach the API at **{API_BASE_URL}**. "
            "Start the server with `uvicorn app.main:app --port 8000` and refresh."
        )
        return
    except httpx.HTTPStatusError as exc:
        st.error(f"API error {exc.response.status_code}: {exc.response.text}")
        return
    except httpx.HTTPError as exc:
        st.error(f"Request failed: {exc}")
        return

    db_ok = health.get("database_available", False)

    total_sessions = int(metrics.get("total_sessions", 0))
    unique_visitors = int(metrics.get("unique_visitors", 0))
    conversion_rate = float(metrics.get("conversion_rate", 0.0))
    total_revenue_inr = float(metrics.get("total_revenue_inr", 0.0))
    queue_depth = int(metrics.get("current_queue_depth", 0))
    queue_abandonment = float(metrics.get("queue_abandonment_rate", 0.0))
    avg_session_dwell_ms = float(metrics.get("average_dwell_time_ms", 0.0))
    purchase_count = funnel_stage_count(funnel, "converted_visitors")

    render_health_panel(health, store_id)
    if not db_ok:
        st.error("Database is unavailable. KPI and analytics sections cannot be trusted.")
        st.stop()

    st.divider()

    st.subheader("Key metrics")
    st.caption(
        "North Star and daily totals from `GET /metrics` — staff excluded; "
        "conversion = visitors with POS-correlated purchase ÷ unique visitors."
    )
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric(
        "Visitors",
        f"{unique_visitors:,}",
        help=METRIC_HELP["Visitors"],
    )
    kpi2.metric(
        "Sessions",
        f"{total_sessions:,}",
        help=METRIC_HELP["Sessions"],
    )
    kpi3.metric(
        "Revenue (INR)",
        format_inr(total_revenue_inr),
        help=METRIC_HELP["Revenue (INR)"],
    )
    kpi4.metric(
        "Conversion rate",
        format_pct(conversion_rate),
        help=METRIC_HELP["Conversion rate"],
    )

    q1, q2, q3 = st.columns(3)
    q1.metric(
        "Queue depth",
        f"{queue_depth:,}",
        help=METRIC_HELP["Queue depth"],
    )
    q2.metric(
        "Queue abandonment",
        format_pct(queue_abandonment),
        help=METRIC_HELP["Queue abandonment"],
    )
    q3.metric(
        "Avg session dwell",
        format_dwell_ms(avg_session_dwell_ms),
        help=METRIC_HELP["Avg session dwell"],
    )

    if purchase_count > 0:
        st.caption(
            f"Purchases (converted visitors): **{purchase_count:,}** · "
            f"Daily POS revenue: **{format_inr(total_revenue_inr)}**."
        )

    render_dwell_by_zone_table(metrics)

    if total_sessions == 0:
        render_empty_state(selected_date)
        st.stop()

    st.divider()
    st.subheader("Conversion funnel")
    st.caption(SECTION_INTROS["funnel"])

    funnel_rows = []
    for stage in funnel.get("stages", []):
        key = stage.get("stage", "")
        funnel_rows.append(
            {
                "Stage": FUNNEL_LABELS.get(key, key),
                "Description": FUNNEL_DESCRIPTIONS.get(key, ""),
                "Visitors": stage.get("count", 0),
                "Drop-off %": stage.get("drop_off_pct"),
            }
        )

    if funnel_rows:
        funnel_df = pd.DataFrame(funnel_rows)
        chart_df = funnel_df.set_index("Stage")[["Visitors"]]
        st.bar_chart(chart_df, height=320)

        display_df = funnel_df.copy()
        display_df["Drop-off %"] = display_df["Drop-off %"].apply(
            lambda v: f"{v:.1f}%" if v is not None else "—"
        )
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        st.caption(
            f"Overall conversion: **{format_pct(float(funnel.get('overall_conversion_rate', 0.0)))}**"
        )
    else:
        st.info("No funnel stages returned for this date.")

    st.divider()
    st.subheader("Zone heatmap")
    st.caption(SECTION_INTROS["heatmap"])
    render_heatmap_confidence_badge(heatmap, total_sessions)

    zones = heatmap.get("zones", [])
    if not zones:
        st.info(
            "No zone engagement data for this date. Zone metrics require customer "
            "sessions with ZONE_ENTER or ZONE_DWELL events."
        )
    else:
        heatmap_df = pd.DataFrame(
            [
                {
                    "Zone": z["zone_id"],
                    "Engagement score": round(float(z["normalized_score"]), 1),
                    "Visits": z["visit_count"],
                    "Unique visitors": z["unique_visitors"],
                    "Avg dwell": format_dwell_ms(float(z["average_dwell_time_ms"])),
                    "Avg dwell (ms)": float(z["average_dwell_time_ms"]),
                }
                for z in zones
            ]
        )

        engagement_col, dwell_col = st.columns(2)
        with engagement_col:
            st.markdown("**Zone engagement**")
            engagement_chart = heatmap_df.set_index("Zone")[["Engagement score"]]
            st.bar_chart(engagement_chart, height=max(240, len(zones) * 36))

        with dwell_col:
            st.markdown("**Dwell time**")
            dwell_chart = heatmap_df.set_index("Zone")[["Avg dwell (ms)"]]
            st.bar_chart(dwell_chart, height=max(240, len(zones) * 36))

        st.dataframe(
            heatmap_df.drop(columns=["Avg dwell (ms)"]),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()
    st.subheader("Anomalies")
    st.caption(SECTION_INTROS["anomalies"])

    alert_list = anomalies.get("anomalies", [])
    if not alert_list:
        st.success("No anomalies detected for this date.")
    else:
        grouped: dict[str, list[dict[str, Any]]] = {
            label: [] for label in ANOMALY_GROUPS
        }
        grouped["Other alerts"] = []

        for anomaly in alert_list:
            anomaly_type = str(anomaly.get("anomaly_type", ""))
            placed = False
            for label, types in ANOMALY_GROUPS.items():
                if anomaly_type in types:
                    grouped[label].append(anomaly)
                    placed = True
                    break
            if not placed:
                grouped["Other alerts"].append(anomaly)

        for label in (*ANOMALY_GROUPS.keys(), "Other alerts"):
            items = grouped[label]
            if not items:
                st.markdown(f"**{label}**")
                st.caption("None")
                continue
            st.markdown(f"**{label}** ({len(items)})")
            for anomaly in items:
                with st.container(border=True):
                    render_anomaly_card(anomaly)


if __name__ == "__main__":
    main()
