"""
CCTV-first dashboard for store1_real / store2_real — plain language for store managers.

Shows live store camera view, brand-area interest, and business metrics.
No technical API panel — manager-facing layout with optional technical panel at bottom (streamlit_app).
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from dashboard.saas_presentation import (
    DEFAULT_PLOT_MARGIN,
    PLOTLY_LAYOUT,
    render_ai_insights,
    render_recommended_actions,
    render_todays_story,
    section_heading,
    zone_tier_rows_html,
)
from dashboard.validation_context import (
    STORE1_REAL_KEY,
    STORE2_REAL_KEY,
    cctv_pipeline_store_key,
)

SHELF_CAMERAS = frozenset({"CAM_SHELF_01", "CAM_SHELF_02"})
ZONE_EVENT_TYPES = frozenset({"ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL"})
BILLING_ZONE = "BILLING"


@dataclass(frozen=True)
class CctvLiveViewProfile:
    tab1_label: str
    tab2_label: str
    pipeline_cameras: tuple[str, str]
    competition_cameras: tuple[str, str]
    tip_html: str


def cctv_live_view_profile(store_key: str) -> CctvLiveViewProfile:
    if store_key == STORE2_REAL_KEY:
        return CctvLiveViewProfile(
            tab1_label="Entry camera",
            tab2_label="Billing area",
            pipeline_cameras=("CAM3", "CAM5"),
            competition_cameras=("CAM_ENTRY_01", "CAM_BILLING_01"),
            tip_html=(
                "<b>Green boxes</b> show shoppers at the store entry and billing area."
            ),
        )
    return CctvLiveViewProfile(
        tab1_label="Left camera",
        tab2_label="Right camera",
        pipeline_cameras=("CAM1", "CAM2"),
        competition_cameras=("CAM_SHELF_01", "CAM_SHELF_02"),
        tip_html="<b>Green boxes</b> show shoppers detected by the system.",
    )

CCTV_CSS = """
<style>
.cctv-header {
    background: linear-gradient(135deg, #312e81 0%, #4f46e5 45%, #6366f1 100%);
    border-radius: 16px; padding: 1.25rem 1.5rem; margin-bottom: 1rem;
    color: #fff; box-shadow: 0 12px 40px rgba(79,70,229,.25);
}
.cctv-header h1 { margin: 0; font-size: 1.45rem !important; color: #fff !important; }
.cctv-header p { margin: .35rem 0 0; opacity: .9; font-size: .92rem !important; color: #e0e7ff !important; }
.cctv-pill {
    display: inline-block; background: rgba(255,255,255,.15); border: 1px solid rgba(255,255,255,.25);
    border-radius: 999px; padding: .2rem .65rem; font-size: .75rem; margin-right: .4rem;
}
.cctv-summary, .cctv-insights {
    background: rgba(255,255,255,0.92); border: 1px solid #e2e8f0;
    border-radius: 16px; padding: 1.15rem 1.35rem; margin-bottom: 1rem;
    box-shadow: 0 4px 18px rgba(15,23,42,.06);
}
.cctv-summary h3, .cctv-insights h3 {
    margin: 0 0 0.65rem 0; font-size: 1.05rem; font-weight: 700; color: #0f172a;
}
.cctv-summary ul, .cctv-insights ul {
    margin: 0; padding-left: 1.15rem; color: #334155; font-size: 0.92rem; line-height: 1.55;
}
.cctv-summary li, .cctv-insights li { margin-bottom: 0.35rem; }
.cctv-kpi {
    background: #fff; border: 1px solid #e2e8f0; border-radius: 14px;
    padding: .9rem 1rem; height: 100%;
    box-shadow: 0 2px 10px rgba(15,23,42,.05);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.cctv-kpi:hover {
    transform: translateY(-3px);
    box-shadow: 0 8px 22px rgba(15,23,42,.08);
}
.cctv-kpi .label { font-size: .76rem; font-weight: 700; color: #475569; text-transform: uppercase; letter-spacing: 0.04em; }
.cctv-kpi .value { font-size: 1.4rem; font-weight: 700; color: #0f172a; margin-top: .25rem; letter-spacing: -0.02em; }
.cctv-kpi .sub { font-size: .76rem; color: #64748b; margin-top: .2rem; line-height: 1.4; }
.cctv-tip {
    font-size: .85rem; color: #475569; background: #f0fdf4;
    border: 1px solid #bbf7d0; border-radius: 10px; padding: .65rem .85rem; margin-top: .5rem;
}
.cctv-explain {
    font-size: 0.88rem; color: #475569; background: #f8fafc;
    border-left: 3px solid #6366f1; border-radius: 0 10px 10px 0;
    padding: 0.65rem 0.9rem; margin: 0.5rem 0 1rem 0; line-height: 1.5;
}
.brand-stat-chips {
    display: flex; flex-wrap: wrap; gap: 0.55rem; margin-bottom: 0.85rem;
}
.brand-stat-chip {
    font-size: 0.8rem; font-weight: 600; color: #1e293b;
    background: #fff; border: 1px solid #e2e8f0; border-radius: 999px;
    padding: 0.45rem 0.9rem; box-shadow: 0 1px 4px rgba(15,23,42,.04);
}
.brand-stat-chip em { font-style: normal; color: #64748b; font-weight: 500; }
</style>
"""


@dataclass
class ShelfZoneStats:
    zone_id: str
    visits: int
    dwell_total_ms: int
    dwell_samples: int
    unique_visitors: set[str]

    @property
    def avg_dwell_ms(self) -> float:
        if self.dwell_samples == 0:
            return 0.0
        return self.dwell_total_ms / self.dwell_samples

    def engagement_score(self) -> float:
        return self.visits + (self.dwell_total_ms / 1000.0)


@dataclass
class CctvDayAnalytics:
    shelf_events: int
    tracked_shoppers: int
    zone_visits: int
    avg_dwell_ms: float
    top_zone: str
    weak_zone: str
    cam1_events: int
    cam2_events: int
    ranked_zones: list[dict[str, Any]]
    hourly_labels: list[str]
    hourly_footfall: list[int]
    live_cam_a_events: int = 0
    live_cam_b_events: int = 0
    entry_visitor_count: int = 0


def _is_product_zone(zone_id: str | None) -> bool:
    if not zone_id:
        return False
    return zone_id.upper() != BILLING_ZONE


def _is_billing_zone(zone_id: str) -> bool:
    return BILLING_ZONE in (zone_id or "").upper()


def _shelf_event(ev: Any) -> bool:
    if getattr(ev, "is_staff", False):
        return False
    if str(getattr(ev, "event_type", "")) not in ZONE_EVENT_TYPES:
        return False
    if str(getattr(ev, "camera_id", "")) not in SHELF_CAMERAS:
        return False
    return _is_product_zone(getattr(ev, "zone_id", None))


def analyze_cctv_day(
    events: list[Any],
    *,
    live_cameras: tuple[str, str] = ("CAM_SHELF_01", "CAM_SHELF_02"),
) -> CctvDayAnalytics:
    """Aggregate shelf/zone metrics and per-camera activity from ingested events."""
    shelf = [ev for ev in events if _shelf_event(ev)]
    entry_visitors: set[str] = set()
    all_cam_counts: Counter[str] = Counter()
    for ev in events:
        if getattr(ev, "is_staff", False):
            continue
        all_cam_counts[str(ev.camera_id)] += 1
        if str(getattr(ev, "event_type", "")) == "ENTRY":
            entry_visitors.add(str(ev.visitor_id))
    zones: dict[str, ShelfZoneStats] = {}
    visitors: set[str] = set()
    zone_visits = 0
    dwell_vals: list[float] = []
    cam_counts: Counter[str] = Counter()
    hourly_visitors: dict[int, set[str]] = defaultdict(set)

    for ev in shelf:
        cam = str(ev.camera_id)
        cam_counts[cam] += 1
        vid = str(ev.visitor_id)
        visitors.add(vid)
        zone_id = str(ev.zone_id)
        stats = zones.setdefault(
            zone_id,
            ShelfZoneStats(
                zone_id=zone_id,
                visits=0,
                dwell_total_ms=0,
                dwell_samples=0,
                unique_visitors=set(),
            ),
        )
        stats.unique_visitors.add(vid)

        ts = ev.timestamp
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            hourly_visitors[ts.hour].add(vid)

        et = str(ev.event_type)
        if et == "ZONE_ENTER":
            stats.visits += 1
            zone_visits += 1
        elif et == "ZONE_DWELL" and int(ev.dwell_ms or 0) > 0:
            stats.dwell_total_ms += int(ev.dwell_ms)
            stats.dwell_samples += 1
            dwell_vals.append(float(ev.dwell_ms))

    scores = {z: s.engagement_score() for z, s in zones.items()}
    max_score = max(scores.values()) if scores else 0.0
    ranked: list[dict[str, Any]] = []
    for zone_id, stats in sorted(zones.items()):
        raw = scores[zone_id]
        interest = (raw / max_score * 100.0) if max_score > 0 else 0.0
        ranked.append(
            {
                "zone_id": zone_id,
                "visits": stats.visits,
                "interest_rate": interest,
                "dwell_ms": stats.avg_dwell_ms,
                "unique_visitors": len(stats.unique_visitors),
            }
        )
    ranked.sort(key=lambda z: z["interest_rate"], reverse=True)

    top_zone = ranked[0]["zone_id"] if ranked else "—"
    weak_zone = ranked[-1]["zone_id"] if ranked else "—"
    avg_dwell = sum(dwell_vals) / len(dwell_vals) if dwell_vals else 0.0

    hours = sorted(hourly_visitors.keys()) if hourly_visitors else []
    labels = [f"{h:02d}:00" for h in hours]
    footfall = [len(hourly_visitors[h]) for h in hours]

    return CctvDayAnalytics(
        shelf_events=len(shelf),
        tracked_shoppers=len(visitors),
        zone_visits=zone_visits,
        avg_dwell_ms=avg_dwell,
        top_zone=top_zone,
        weak_zone=weak_zone,
        cam1_events=cam_counts.get("CAM_SHELF_01", 0),
        cam2_events=cam_counts.get("CAM_SHELF_02", 0),
        live_cam_a_events=all_cam_counts.get(live_cameras[0], 0),
        live_cam_b_events=all_cam_counts.get(live_cameras[1], 0),
        entry_visitor_count=len(entry_visitors),
        ranked_zones=ranked,
        hourly_labels=labels,
        hourly_footfall=footfall,
    )


def fetch_cctv_events(store_key: str, store_id: str, metric_date: date) -> list[Any]:
    from dashboard.validation_context import bind_dashboard_database

    bind_dashboard_database(store_key)
    from app.db import fetch_store_events, get_session

    with get_session() as session:
        return fetch_store_events(session, store_id, day=metric_date)


def _pipeline_tracking_videos(
    pipeline_store_key: str,
    camera_keys: tuple[str, str],
) -> tuple[Path | None, Path | None]:
    try:
        from pipeline.store_config import get_store_config
        from pipeline.shelf_preview import shelf_tracking_output_path

        cfg = get_store_config(pipeline_store_key)
        first = shelf_tracking_output_path(cfg.pipeline_output_dir, camera_keys[0])
        second = shelf_tracking_output_path(cfg.pipeline_output_dir, camera_keys[1])
        return (
            first if first.is_file() else None,
            second if second.is_file() else None,
        )
    except Exception:
        return None, None


@st.cache_data(show_spinner=False)
def _tracking_mp4_preview_png(mp4_path_str: str, mtime_ns: int) -> bytes | None:
    """Cached frame grab from ``*_tracking.mp4`` (no YOLO — avoids OOM in Streamlit)."""
    from pipeline.shelf_preview import capture_tracking_mp4_preview_png

    return capture_tracking_mp4_preview_png(Path(mp4_path_str))


def _render_shelf_camera_feed(
    mp4_path: Path | None,
    *,
    camera_key: str,
    pipeline_store_key: str,
    missing_label: str,
) -> None:
    """Annotated still from pipeline ``*_tracking.mp4`` (no FFmpeg or YOLO)."""
    del camera_key, pipeline_store_key
    if not mp4_path or not mp4_path.is_file():
        st.info(missing_label)
        return

    preview_png = _tracking_mp4_preview_png(
        str(mp4_path.resolve()),
        mp4_path.stat().st_mtime_ns,
    )
    if preview_png:
        st.image(
            preview_png,
            caption="Annotated store view — brand areas and shoppers (green boxes)",
            use_container_width=True,
        )
    else:
        st.info(missing_label)


def _format_inr(value: float) -> str:
    return f"₹{value:,.2f}"


def _format_shopping_time(ms: float) -> str:
    if ms <= 0:
        return "—"
    seconds = ms / 1000.0
    if seconds < 60:
        return f"{seconds:.0f} seconds"
    minutes = seconds / 60.0
    if minutes < 2:
        return f"{seconds:.0f} seconds"
    return f"{minutes:.1f} minutes"


def _visitors_today_for_display(
    metrics: dict[str, Any],
    cctv: CctvDayAnalytics,
) -> tuple[int, float, str]:
    """
    Presentation helper for store1_real / store2_real visitor KPIs.

    Prefer API ``unique_visitors`` (CAM3 entry sessions). Fall back to ENTRY rows in
    the intelligence DB, then shelf-camera unique IDs (store_1 style).
    """
    metrics_uv = int(metrics.get("unique_visitors", 0))
    metrics_dwell = float(metrics.get("average_dwell_time_ms", 0.0))

    def _dwell_for_display() -> float:
        """Session dwell from /metrics; shelf zone dwell when session metric is zero."""
        if metrics_dwell > 0:
            return metrics_dwell
        return cctv.avg_dwell_ms

    if metrics_uv > 0:
        return (
            metrics_uv,
            _dwell_for_display(),
            "Unique visitors who entered the store",
        )

    if cctv.entry_visitor_count > 0:
        return (
            cctv.entry_visitor_count,
            _dwell_for_display(),
            "Unique visitors who entered the store",
        )

    shelf_uv = cctv.tracked_shoppers
    if shelf_uv > 0:
        dwell = cctv.avg_dwell_ms if cctv.avg_dwell_ms > 0 else metrics_dwell
        return (
            shelf_uv,
            dwell,
            "Visitors seen in brand areas today",
        )

    return metrics_uv, metrics_dwell, "Unique visitors in the store"


def _heatmap_traffic_zones(
    heatmap: dict[str, Any],
) -> tuple[str, str]:
    """Most / least visited brand area from heatmap visit counts."""
    zones = [
        z
        for z in heatmap.get("zones", [])
        if not _is_billing_zone(str(z.get("zone_id", "")))
    ]
    if not zones:
        return "—", "—"
    by_visits = sorted(zones, key=lambda z: int(z.get("visit_count", 0)), reverse=True)
    return str(by_visits[0].get("zone_id", "—")), str(by_visits[-1].get("zone_id", "—"))


def _kpi_card(label: str, value: str, sub: str = "") -> str:
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    return (
        f'<div class="cctv-kpi"><div class="label">{label}</div>'
        f'<div class="value">{value}</div>{sub_html}</div>'
    )


def _executive_summary_bullets(
    *,
    unique_visitors: int,
    total_revenue_inr: float,
    top_zone: str,
    weak_zone: str,
    friendly_zone_fn: Any,
) -> list[str]:
    bullets = [
        f"{unique_visitors:,} visitors entered shopping areas",
        f"{_format_inr(total_revenue_inr)} revenue generated",
        f"{friendly_zone_fn(top_zone)} received the highest customer attention",
        f"{friendly_zone_fn(weak_zone)} received the lowest customer attention",
    ]
    return bullets


def _dedupe_lines(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = " ".join(item.strip().lower().split())
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


def _manager_insights(
    *,
    avg_dwell_ms: float,
    top_zone: str,
    weak_zone: str,
    friendly_zone_fn: Any,
) -> list[str]:
    insights: list[str] = []
    if top_zone and top_zone != "—":
        insights.append(
            f"{friendly_zone_fn(top_zone)} attracts the highest customer traffic."
        )
    if weak_zone and weak_zone != "—" and weak_zone != top_zone:
        insights.append(
            f"{friendly_zone_fn(weak_zone)} is receiving low engagement."
        )
    dwell_text = _format_shopping_time(avg_dwell_ms)
    if avg_dwell_ms > 0:
        insights.append(f"Customers spend an average of {dwell_text} browsing.")
    if not insights:
        insights.append("Select a trading day with store activity to see insights.")
    return insights[:5]


def _build_brand_interest_map(ranked: list[dict[str, Any]], friendly_zone_fn: Any) -> go.Figure:
    if not ranked:
        fig = go.Figure()
        fig.update_layout(
            **PLOTLY_LAYOUT,
            height=260,
            margin=DEFAULT_PLOT_MARGIN,
            title=dict(
                text="Customer interest by brand area",
                font=dict(size=15, color="#0f172a"),
            ),
        )
        return fig

    n = len(ranked)
    cols = max(3, math.ceil(math.sqrt(n)))
    rows = math.ceil(n / cols)
    grid = [[0.0] * cols for _ in range(rows)]
    labels = [[""] * cols for _ in range(rows)]
    for idx, zone in enumerate(ranked):
        r, c = divmod(idx, cols)
        grid[r][c] = zone["interest_rate"]
        labels[r][c] = friendly_zone_fn(str(zone.get("zone_id", "")))

    fig = go.Figure(
        data=go.Heatmap(
            z=grid,
            text=labels,
            texttemplate="%{text}",
            textfont=dict(size=12, color="#0f172a", family="DM Sans, sans-serif"),
            colorscale=[
                [0.0, "#f1f5f9"],
                [0.35, "#93c5fd"],
                [0.65, "#3b82f6"],
                [1.0, "#1d4ed8"],
            ],
            xgap=6,
            ygap=6,
            showscale=True,
            colorbar=dict(
                title=dict(text="Customer Interest", font=dict(size=12)),
                thickness=18,
                len=0.72,
                bgcolor="rgba(255,255,255,0.85)",
                bordercolor="#e2e8f0",
                borderwidth=1,
            ),
            hovertemplate=(
                "Brand area: %{text}<br>Customer interest: %{z:.0f}%<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        **PLOTLY_LAYOUT,
        height=max(260, rows * 68),
        margin=DEFAULT_PLOT_MARGIN,
        title=dict(
            text="Customer interest by brand area",
            font=dict(size=15, color="#0f172a"),
        ),
        xaxis=dict(showgrid=False, showticklabels=False),
        yaxis=dict(showgrid=False, showticklabels=False, autorange="reversed"),
    )
    return fig


def _brand_stat_chips_html(
    *,
    most_zone: str,
    least_zone: str,
    avg_time: str,
    friendly_zone_fn: Any,
) -> str:
    return (
        '<div class="brand-stat-chips">'
        f'<span class="brand-stat-chip"><em>Most visited brand area ·</em> '
        f"{friendly_zone_fn(most_zone)}</span>"
        f'<span class="brand-stat-chip"><em>Least visited brand area ·</em> '
        f"{friendly_zone_fn(least_zone)}</span>"
        f'<span class="brand-stat-chip"><em>Average time spent ·</em> {avg_time}</span>'
        "</div>"
    )


def _zone_cards_grid(
    ranked: list[dict[str, Any]],
    friendly_zone_fn: Any,
    format_dwell_fn: Any,
) -> str:
    return zone_tier_rows_html(
        ranked,
        friendly_zone_fn=friendly_zone_fn,
        format_dwell_fn=format_dwell_fn,
        score_key="interest_rate",
    )


def _render_today_at_a_glance(
    *,
    unique_visitors: int,
    visitors_subtitle: str,
    total_revenue_inr: float,
    avg_shopping_ms: float,
    most_visited: str,
    least_visited: str,
    friendly_zone_fn: Any,
) -> None:
    st.markdown("#### Today at a glance")
    k1, k2, k3 = st.columns(3)
    k4, k5 = st.columns(2)
    cards_row1 = [
        ("Visitors Today", f"{unique_visitors:,}", visitors_subtitle),
        ("Revenue Today", _format_inr(total_revenue_inr), "Total sales for the day"),
        (
            "Average Shopping Time",
            _format_shopping_time(avg_shopping_ms),
            "Typical time spent browsing",
        ),
    ]
    cards_row2 = [
        (
            "Most Visited Brand Area",
            friendly_zone_fn(most_visited),
            "Highest customer traffic",
        ),
        (
            "Needs Attention",
            friendly_zone_fn(least_visited),
            "Lowest customer traffic",
        ),
    ]
    for col, (label, value, sub) in zip([k1, k2, k3], cards_row1):
        with col:
            st.markdown(_kpi_card(label, value, sub), unsafe_allow_html=True)
    for col, (label, value, sub) in zip([k4, k5], cards_row2):
        with col:
            st.markdown(_kpi_card(label, value, sub), unsafe_allow_html=True)


def render_cctv_real_dashboard(
    *,
    store_key: str,
    store_label: str,
    store_id: str,
    metric_date: date,
    metrics: dict[str, Any],
    funnel: dict[str, Any],
    heatmap: dict[str, Any],
    anomalies: dict[str, Any],
    health: dict[str, Any],
    friendly_zone_fn: Any,
    format_dwell_fn: Any,
    business_insights: dict[str, Any] | None = None,
) -> None:
    """Retail intelligence layout for store managers (business-first)."""
    st.markdown(CCTV_CSS, unsafe_allow_html=True)

    pipeline_key = cctv_pipeline_store_key(store_key)
    live_profile = cctv_live_view_profile(store_key)
    events = fetch_cctv_events(store_key, store_id, metric_date)
    cctv = analyze_cctv_day(events, live_cameras=live_profile.competition_cameras)

    total_revenue_inr = float(metrics.get("total_revenue_inr", 0.0))
    unique_visitors, avg_shopping_ms, visitors_subtitle = _visitors_today_for_display(
        metrics, cctv
    )

    hm_top, hm_weak = _heatmap_traffic_zones(heatmap)
    most_visited = hm_top if hm_top != "—" else cctv.top_zone
    least_visited = hm_weak if hm_weak != "—" else cctv.weak_zone

    ranked = cctv.ranked_zones
    metrics_only = store_key == STORE2_REAL_KEY
    db_ok = bool(health.get("database_available", False))
    status = "Store data loaded" if db_ok else "Check database"
    header_pill = "Store analytics" if metrics_only else "Live store view"
    st.markdown(
        f'<div class="cctv-header">'
        f'<span class="cctv-pill">{header_pill}</span>'
        f'<span class="cctv-pill">{"Ready" if db_ok else "Setup needed"}</span>'
        f"<h1>{store_label}</h1>"
        f"<p>{metric_date.strftime('%d %b %Y')} · {status}</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    conversion_rate = float(metrics.get("conversion_rate", 0.0))
    insight_data = (business_insights or {}).get("insights") or {}
    store_summary = str(insight_data.get("store_summary") or "").strip()
    manager_actions = _dedupe_lines(
        [str(x) for x in (insight_data.get("manager_actions") or []) if str(x).strip()]
    )

    if business_insights and store_summary:
        render_todays_story(store_summary, conversion_rate)
    else:
        summary_bullets = _executive_summary_bullets(
            unique_visitors=unique_visitors,
            total_revenue_inr=total_revenue_inr,
            top_zone=most_visited,
            weak_zone=least_visited,
            friendly_zone_fn=friendly_zone_fn,
        )
        st.markdown(
            '<div class="cctv-summary fade-up"><h3>Today\'s Store Summary</h3><ul>'
            + "".join(f"<li>{item}</li>" for item in summary_bullets)
            + "</ul></div>",
            unsafe_allow_html=True,
        )

    if business_insights and manager_actions:
        render_recommended_actions(manager_actions)
    else:
        insight_lines = _manager_insights(
            avg_dwell_ms=avg_shopping_ms if avg_shopping_ms > 0 else cctv.avg_dwell_ms,
            top_zone=most_visited,
            weak_zone=least_visited,
            friendly_zone_fn=friendly_zone_fn,
        )
        st.markdown(
            '<div class="cctv-insights fade-up"><h3>Store Manager Insights</h3><ul>'
            + "".join(f"<li>{item}</li>" for item in insight_lines)
            + "</ul></div>",
            unsafe_allow_html=True,
        )

    if cctv.shelf_events == 0 and unique_visitors == 0:
        st.warning(
            f"No brand-area activity recorded for this day. Run demo_runner for "
            f"{pipeline_key}, pick the correct trading day, and refresh."
        )

    kpi_kwargs = dict(
        unique_visitors=unique_visitors,
        visitors_subtitle=visitors_subtitle,
        total_revenue_inr=total_revenue_inr,
        avg_shopping_ms=avg_shopping_ms,
        most_visited=most_visited,
        least_visited=least_visited,
        friendly_zone_fn=friendly_zone_fn,
    )

    if metrics_only:
        _render_today_at_a_glance(**kpi_kwargs)
        st.caption(
            f"Camera activity today — {live_profile.tab1_label.lower()}: "
            f"**{cctv.live_cam_a_events}**, "
            f"{live_profile.tab2_label.lower()}: **{cctv.live_cam_b_events}**"
        )
    else:
        col_feed, col_kpi = st.columns([1.05, 1.45], gap="large")

        with col_feed:
            st.markdown("#### Live Store View")
            vid_a, vid_b = _pipeline_tracking_videos(
                pipeline_key, live_profile.pipeline_cameras
            )
            if vid_a or vid_b:
                tab1, tab2 = st.tabs(
                    [live_profile.tab1_label, live_profile.tab2_label]
                )
                with tab1:
                    _render_shelf_camera_feed(
                        vid_a,
                        camera_key=live_profile.pipeline_cameras[0],
                        pipeline_store_key=pipeline_key,
                        missing_label=f"{live_profile.tab1_label} recording not found yet.",
                    )
                with tab2:
                    _render_shelf_camera_feed(
                        vid_b,
                        camera_key=live_profile.pipeline_cameras[1],
                        pipeline_store_key=pipeline_key,
                        missing_label=f"{live_profile.tab2_label} recording not found yet.",
                    )
                st.markdown(
                    f'<div class="cctv-tip">{live_profile.tip_html}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.warning(
                    f"No camera recordings yet. Run: "
                    f'$env:PURPPLE_STORE = "{pipeline_key}"; '
                    "python scripts/demo_runner.py"
                )
            st.caption(
                f"Shopper interactions today — {live_profile.tab1_label.lower()}: "
                f"**{cctv.live_cam_a_events}**, "
                f"{live_profile.tab2_label.lower()}: **{cctv.live_cam_b_events}**"
            )

        with col_kpi:
            _render_today_at_a_glance(**kpi_kwargs)

    st.markdown('<div class="glass accent-indigo fade-up">', unsafe_allow_html=True)
    section_heading(
        "Which brand areas attracted customers?",
        eyebrow="Brand areas",
        accent="blue",
    )
    st.markdown(
        '<p class="cctv-explain">Customer interest is calculated using visits and '
        "time spent in each brand area.</p>",
        unsafe_allow_html=True,
    )

    if ranked:
        st.markdown(
            _brand_stat_chips_html(
                most_zone=cctv.top_zone,
                least_zone=cctv.weak_zone,
                avg_time=format_dwell_fn(avg_shopping_ms),
                friendly_zone_fn=friendly_zone_fn,
            ),
            unsafe_allow_html=True,
        )
        st.plotly_chart(
            _build_brand_interest_map(ranked, friendly_zone_fn),
            use_container_width=True,
        )
        st.markdown(
            '<p class="zone-tier-section">Brand area performance</p>',
            unsafe_allow_html=True,
        )
        st.markdown(
            _zone_cards_grid(ranked, friendly_zone_fn, format_dwell_fn),
            unsafe_allow_html=True,
        )
    else:
        st.info("No brand-area activity recorded for this day.")
    st.markdown("</div>", unsafe_allow_html=True)

    if business_insights:
        render_ai_insights(business_insights)


# Backward-compatible alias
render_store1_real_dashboard = render_cctv_real_dashboard
