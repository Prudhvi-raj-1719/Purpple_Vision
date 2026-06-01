# Business Question Mapping

The Apex Retail challenge asks: *Can we link CCTV behaviour to POS outcomes and give store managers answers they can act on?*

This document maps each **business question** to the system component, API, and dashboard section that answers it.

---

## Problem → output mapping

| Business Question | System Component | Metric / API | Dashboard Section |
|-------------------|------------------|--------------|-------------------|
| How many customers entered? | Session Builder (ENTRY/REENTRY events) | `unique_visitors` · `GET /metrics` | Key metrics → **Visitors** |
| How many purchased? | POS Correlation (billing window + POS match) | `conversion_rate` · funnel `converted_visitors` · `GET /metrics` / `GET /funnel` | Key metrics → **Conversion rate**; funnel → **Purchased (POS)** |
| What sales were generated? | Metrics Engine (POS aggregation) | `total_revenue_inr` · `GET /metrics` | Key metrics → **Revenue (INR)** |
| How many separate visits occurred? | Session Builder | `total_sessions` · `GET /metrics` | Key metrics → **Sessions** |
| Where do customers spend time? | Dwell aggregation per zone | `average_dwell_by_zone` · `GET /metrics` | **Average dwell by zone** table |
| Which zones are ignored? | Heatmap + Anomaly detection | `normalized_score` · `DEAD_ZONE` · `GET /heatmap` / `GET /anomalies` | **Zone heatmap**; **Anomalies** → Unusual traffic alerts |
| Where do customers leave the journey? | Funnel computation | `drop_off_pct` per stage · `GET /funnel` | **Conversion funnel** |
| Are queues causing conversion loss? | Queue session flags + abandonment rate | `queue_abandonment_rate` · `QUEUE_SPIKE` · `GET /metrics` / `GET /anomalies` | Key metrics → **Queue abandonment**; **Anomalies** → Queue alerts |
| Which areas need staffing attention? | Queue depth + queue spike detector | `current_queue_depth` · `QUEUE_SPIKE` · `GET /metrics` / `GET /anomalies` | Key metrics → **Queue depth**; **Anomalies** |
| Is the CCTV feed healthy? | Health monitor | `status` · `stores[].stale` · `STALE_FEED` · `GET /health` | **System health** |
| Which zones generate engagement? | Heatmap engine | `normalized_score` · `visit_count` · `GET /heatmap` | **Zone heatmap** |
| Which zones require intervention? | Dead zone detector | `DEAD_ZONE` · `suggested_action` · `GET /anomalies` | **Anomalies** → Unusual traffic alerts |
| Are customers browsing or rushing? | Session dwell aggregation | `average_dwell_time_ms` · `GET /metrics` | Key metrics → **Avg session dwell** |
| Can I trust zone comparisons today? | Heatmap confidence gate | `data_confidence` · `GET /heatmap` | **Zone heatmap** → confidence badge |
| Is conversion unusually low today? | Conversion drop detector | `CONVERSION_DROP` · `GET /anomalies` | **Anomalies** → Low conversion alerts |

---

## Customer journey → KPI flow

| Step | Business insight | Primary output |
|------|------------------|----------------|
| **CCTV Events** | In-store behaviour captured and ingested | Session Builder |
| **Session Builder** | Visits structured from ENTRY through zone and queue activity | Queue, Heatmap, and Funnel Analytics |
| **POS Transactions** | Sales records for the day | Funnel Analytics (purchase correlation) |
| **Queue Analytics** | Billing wait and abandonment patterns | Operational Alerts |
| **Heatmap Analytics** | Which zones attract attention | Zone Insights |
| **Funnel Analytics** | Where customers drop off and who converted | Conversion KPI |
| **Dashboard** | Single view for store managers | Operational Alerts, Zone Insights, Conversion KPI |

---

## Reviewer Walkthrough

Read the dashboard **top to bottom** on the validation date (`2026-06-01` with `demo_validation.db`) to see non-zero KPIs:

1. **Check system health** — Confirm service status is `OK`, database is available, last event timestamp is recent, and feed status is **Live** (not STALE). If stale, downstream KPIs may be outdated.

2. **Review visitor and revenue KPIs** — Note **Visitors**, **Sessions**, **Revenue (INR)**, and **Conversion rate**. These answer "how busy was the store?" and "did visits turn into money?" Expected validation demo: 3 visitors, 3 sessions, ₹2,148.50 revenue, 66.7% conversion.

3. **Review funnel conversion** — Follow the four stages (entry → zone → billing → purchase) and read **drop-off %** between each. This shows where the journey weakens — e.g. visitors who browse but never reach billing.

4. **Review zone engagement** — Open the **Zone heatmap** and compare normalized scores across zones (LAKME, PILGRIM, GOODVIBES, etc.). High scores mean strong attention; low scores flag candidates for layout review.

5. **Review dwell behaviour** — Check **Avg session dwell** and the **Average dwell by zone** table. Long dwell in a zone with low conversion may indicate interest without easy purchase path.

6. **Review queue performance** — Inspect **Queue depth** and **Queue abandonment**. Rising depth with high abandonment signals checkout capacity problems.

7. **Review anomalies and recommendations** — Read active alerts (queue spike, conversion drop, dead zone). Each includes **severity** and a **suggested action** — the operational "so what?" for store staff.

---

## Quick validation path

```powershell
python scripts/demo_validation_run.py

$env:DATABASE_URL = "sqlite:///./data/databases/demo_validation.db"
uvicorn app.main:app --host 0.0.0.0 --port 8000

$env:API_BASE_URL = "http://localhost:8000"
$env:DEFAULT_METRIC_DATE = "2026-06-01"
streamlit run dashboard/streamlit_app.py
```

Full metric definitions: [business_metrics.md](business_metrics.md)

---

## Related

- [business_metrics.md](business_metrics.md) — detailed metric reference
- [pipeline_flow.md](pipeline_flow.md) — how data reaches the dashboard
- [../reports/demo_validation_report.md](../reports/demo_validation_report.md) — expected validation numbers
