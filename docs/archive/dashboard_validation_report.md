# Dashboard Validation Report — Phase 8

**Date:** 2026-05-31  
**Component:** `dashboard/streamlit_app.py`  
**Store:** `STORE_BLR_002`  
**Metric date (UTC):** `2026-04-10`  
**API base URL:** `http://127.0.0.1:8000`

---

## 1. Summary

| Item | Status |
|------|--------|
| Streamlit dashboard implemented | **Yes** |
| Reads SQLite directly | **No** — HTTP only via FastAPI |
| KPI cards (Visitors, Sessions, Revenue, Conversion) | **Yes** |
| Funnel (Visitors → Engaged → Billing → Purchases) | **Yes** (hidden when sessions = 0) |
| Heatmap (engagement + dwell) | **Yes** (hidden when sessions = 0) |
| Anomalies (queue / conversion / traffic) | **Yes** (hidden when sessions = 0) |
| Empty-state handling (sessions = 0) | **Yes** — informative message, no blank charts |
| Analytics logic modified | **No** |

**Validated empty-state behavior:** With current bridged data (`total_sessions = 0`), the dashboard shows four KPI cards (all zeros / em dash for revenue) and the message:

> **No sessions found for selected date (2026-04-10).**

Funnel, heatmap, and anomaly sections are **not rendered** (via `st.stop()`) to avoid empty charts.

---

## 2. Endpoints consumed

| Endpoint | Purpose in dashboard |
|----------|----------------------|
| `GET /health` | Store selector population; database availability check |
| `GET /stores/{store_id}/metrics?date=YYYY-MM-DD` | KPI cards: visitors, sessions, conversion rate |
| `GET /stores/{store_id}/funnel?date=YYYY-MM-DD` | Funnel chart + purchase count caption |
| `GET /stores/{store_id}/heatmap?date=YYYY-MM-DD` | Zone engagement + dwell bar charts |
| `GET /stores/{store_id}/anomalies?date=YYYY-MM-DD` | Queue / conversion / dead-zone alert panels |

### Live validation results (2026-05-31)

| Endpoint | HTTP | Notes |
|----------|------|-------|
| `/health` | 200 | `database_available: true` |
| `/stores/STORE_BLR_002/metrics?date=2026-04-10` | 200 | `unique_visitors=0`, `total_sessions=0` |
| `/stores/STORE_BLR_002/funnel?date=2026-04-10` | 200 | All stage counts = 0 |
| `/stores/STORE_BLR_002/heatmap?date=2026-04-10` | 200 | `zones=[]` |
| `/stores/STORE_BLR_002/anomalies?date=2026-04-10` | 200 | `anomalies=[]` |

### Automated UI test

```text
streamlit.testing.v1.AppTest.from_file("dashboard/streamlit_app.py")
→ No exceptions
→ 4 KPI metrics rendered
→ Warning contains "No sessions found"
```

---

## 3. Feature mapping

### KPI cards

| Card | API source | Current value (2026-04-10) |
|------|------------|----------------------------|
| Visitors | `metrics.unique_visitors` | 0 |
| Sessions | `metrics.total_sessions` | 0 |
| Revenue (INR) | *Not exposed by API* | — (em dash) |
| Conversion rate | `metrics.conversion_rate` | 0.0% |

**Revenue note:** The analytics API does not expose daily revenue totals. The dashboard shows **—** with a tooltip. Purchase count is available from funnel stage `converted_visitors` when sessions exist.

### Funnel labels

| Display label | API stage key |
|---------------|---------------|
| Visitors | `unique_visitors` |
| Engaged | `reached_any_zone` |
| Billing | `billing_queue` |
| Purchases | `converted_visitors` |

### Anomaly groups

| Display section | API `anomaly_type` |
|-----------------|-------------------|
| Queue alerts | `QUEUE_SPIKE` |
| Low conversion alerts | `CONVERSION_DROP` |
| Unusual traffic alerts | `DEAD_ZONE` |

---

## 4. Screenshots saved

| File | Description |
|------|-------------|
| [`docs/dashboard_screenshots/dashboard_empty_state.png`](docs/dashboard_screenshots/dashboard_empty_state.png) | KPI row + empty-state message (validated API data) |
| [`docs/dashboard_screenshots/dashboard_funnel_zero_state.png`](docs/dashboard_screenshots/dashboard_funnel_zero_state.png) | Funnel reference chart (all zeros; shown only when sessions > 0 in live UI) |

Generated via `scripts/capture_dashboard_screenshots.py` against the running API.

**Live Streamlit UI:** Open http://localhost:8501 after launch (see below) for the interactive dashboard with sidebar filters and refresh button.

---

## 5. Launch instructions

### Prerequisites

- Python venv activated
- SQLite populated (e.g. `python scripts/bridge_pipeline_to_product.py`)
- Dependencies installed (`pip install -r requirements.txt`)

### Step 1 — Start the API

**PowerShell (local):**

```powershell
cd E:\Purpple_Vision
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Verify: http://localhost:8000/health

### Step 2 — Start Streamlit

**Second terminal:**

```powershell
cd E:\Purpple_Vision
.\.venv\Scripts\Activate.ps1
$env:API_BASE_URL = "http://localhost:8000"
$env:DEFAULT_STORE_ID = "STORE_BLR_002"
$env:DEFAULT_METRIC_DATE = "2026-04-10"
streamlit run dashboard/streamlit_app.py --server.port 8501
```

Open: http://localhost:8501

### Docker (API + dashboard profile)

```powershell
docker compose --profile dashboard up --build
```

- API: http://localhost:8000  
- Dashboard: http://localhost:8501 (`API_BASE_URL` preset to `http://api:8000`)

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `API_BASE_URL` | `http://localhost:8000` | FastAPI base URL |
| `DEFAULT_STORE_ID` | `STORE_BLR_002` | Initial store selection |
| `DEFAULT_METRIC_DATE` | `2026-04-10` | Initial date (bridged demo data) |

---

## 6. Error handling

| Condition | Dashboard behavior |
|-----------|-------------------|
| API unreachable | Red error: start uvicorn instructions |
| HTTP 503 / DB down | Error message; no charts |
| `total_sessions == 0` | KPI zeros + **No sessions found** warning; skip charts |
| Empty funnel / heatmap / anomalies (sessions > 0) | Section-level info messages |
| No anomalies | Green success: "No anomalies detected" |

---

## 7. Demo readiness

| Scenario | Expected UI |
|----------|-------------|
| Current data (zone-only, no ENTRY) | KPI zeros + empty-state message |
| After CAM3 + re-bridge | KPIs populate; funnel/heatmap/anomalies sections appear |
| API stopped | Connection error banner |

**Phase 8 status:** Dashboard presentation layer **complete**. Meaningful non-zero charts depend on session-producing ENTRY events (see `final_session_gap_report.md`).

---

## 8. Files changed

| File | Change |
|------|--------|
| `dashboard/streamlit_app.py` | Full Streamlit implementation |
| `scripts/capture_dashboard_screenshots.py` | Optional screenshot generator for validation |
| `docs/dashboard_screenshots/*.png` | Validation screenshots |
| `dashboard_validation_report.md` | This report |

**Not modified:** `app/metrics.py`, `app/funnel.py`, `app/heatmap.py`, `app/anomalies.py`, session engine, or SQLite schema.
