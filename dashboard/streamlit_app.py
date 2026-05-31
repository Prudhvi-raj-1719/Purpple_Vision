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
    "unique_visitors": "Visitors",
    "reached_any_zone": "Engaged",
    "billing_queue": "Billing",
    "converted_visitors": "Purchases",
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
    st.caption("Live analytics from the FastAPI intelligence layer")

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
    if not db_ok:
        st.error("Database is unavailable. Analytics cannot be loaded.")
        return

    total_sessions = int(metrics.get("total_sessions", 0))
    unique_visitors = int(metrics.get("unique_visitors", 0))
    conversion_rate = float(metrics.get("conversion_rate", 0.0))
    purchase_count = funnel_stage_count(funnel, "converted_visitors")

    st.subheader("Key metrics")
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("Visitors", f"{unique_visitors:,}")
    kpi2.metric("Sessions", f"{total_sessions:,}")
    kpi3.metric(
        "Revenue (INR)",
        "—",
        help=(
            "Daily revenue totals are not exposed by the analytics API. "
            "Use the Purchases funnel stage for converted visitor count."
        ),
    )
    kpi4.metric("Conversion rate", format_pct(conversion_rate))

    if purchase_count > 0:
        st.caption(
            f"Purchases (converted visitors): **{purchase_count:,}**. "
            "Revenue in INR requires a future POS summary endpoint."
        )

    if total_sessions == 0:
        render_empty_state(selected_date)
        st.stop()

    st.divider()
    st.subheader("Conversion funnel")

    funnel_rows = []
    for stage in funnel.get("stages", []):
        key = stage.get("stage", "")
        funnel_rows.append(
            {
                "Stage": FUNNEL_LABELS.get(key, key),
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

        confidence = heatmap.get("data_confidence", False)
        if not confidence:
            st.caption(
                "Low sample size: fewer than 20 customer sessions — "
                "heatmap comparisons may be unreliable."
            )

    st.divider()
    st.subheader("Anomalies")

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
