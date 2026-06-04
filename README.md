# Store Intelligence Platform

**Purpple Vision** — turn CCTV footage and POS transactions into store conversion intelligence for Apex Retail.

**North Star:** Conversion rate = visitors who purchased ÷ unique visitors.

**Submission runbook:** [docs/SUBMISSION.md](docs/SUBMISSION.md) (all commands reviewers need)

**Important for judges:** Databases and large tracking videos are **not** in git. After clone, run `python scripts/demo_validation_run.py --store all` and/or `python scripts/demo_runner.py` per store, then start Streamlit. Details: [docs/SUBMISSION.md](docs/SUBMISSION.md).

---

## Problem Statement

Offline retail stores capture CCTV and POS data separately. Without linking them, managers cannot answer:

- How many visitors entered and how many bought?
- Where in the store journey do customers drop off?
- Which zones get attention but not sales?
- Is a queue building or a camera feed stale?

This project implements the full challenge stack: **Detection Layer → Event Stream → Intelligence API → Dashboard**.

---

## Architecture Overview

```
Raw CCTV clips
    → Detection Layer (YOLO11m + ByteTrack + zone rules)
    → Event Stream (schema-validated JSONL)
    → Ingestion (POST /events/ingest, POST /pos/ingest)
    → Session Builder (ENTRY/REENTRY → EXIT)
    → Metrics Engine (conversion, funnel, heatmap, anomalies)
    → Dashboard (Streamlit)
```

| Layer | Location | Role |
|-------|----------|------|
| **Detection Layer** | `pipeline/` | CAM1–CAM5 processors, POS loader |
| **Event Stream** | `data/outputs/pipeline/` | Per-store JSONL (`pipeline_demo_store_1`, `pipeline_demo_store_2`) |
| **Intelligence API** | `app/` | FastAPI + SQLite analytics |
| **Dashboard** | `dashboard/streamlit_app.py` | Store selector + analytics UI |

Deep dive: [docs/DESIGN.md](docs/DESIGN.md) · Flow: [docs/architecture/pipeline_flow.md](docs/architecture/pipeline_flow.md)

---

## Repository Structure

```
Purpple_Vision/
├── app/                         # FastAPI intelligence API
├── pipeline/                    # CCTV + POS processors
├── dashboard/                   # streamlit_app.py, cctv_real_view.py, saas_presentation.py
├── scripts/                     # demo_runner, bridge, demo_validation_run
├── stores/                      # store_1, store_2 configs (zones, videos)
├── tests/
├── data/
│   ├── cctv/                    # Footage (not committed)
│   ├── pos/                     # Brigade POS CSV
│   ├── outputs/pipeline/        # Generated JSONL + tracking MP4
│   └── databases/               # SQLite (generated locally; gitignored)
└── docs/
    ├── SUBMISSION.md            # Hackathon / reviewer commands
    └── PROJECT_STATUS.md
```

---

## Prerequisites

- **Python 3.11+**
- **`pip install -r requirements.txt`**
- **`models/yolo11m.pt`** (YOLO weights; not in git)
- **`data/cctv/`** footage (only to regenerate pipeline; not in git)
---

## Quick start — dashboard (recommended for demo video)

**Step 1 — create databases** (required on a fresh clone):

```powershell
pip install -r requirements.txt
python scripts/demo_validation_run.py --store all
$env:PURPPLE_STORE = "store_1"; python scripts/demo_runner.py
$env:PURPPLE_STORE = "store_2"; python scripts/demo_runner.py
```

**Step 2 — run Streamlit:**

```powershell
streamlit run dashboard/streamlit_app.py
```

Open http://localhost:8501

| Sidebar store | Database | Typical trading day |
|---------------|----------|-------------------|
| **Store 1** | `store_1_validation.db` | 2026-06-01 |
| **Store 2** | `store_2_validation.db` | 2026-04-10 |
| **store1_real** | `store_1_intelligence.db` | 2026-04-10 |
| **store2_real** | `store_2_intelligence.db` | 2026-04-10 |

The dashboard reads analytics from the **bound SQLite file** by default (no API server required).

---

## Commands to regenerate data

### Full CCTV pipeline + intelligence DB (one store)

```powershell
$env:PURPPLE_STORE = "store_1"   # Brigade — or "store_2" for competition footage
python scripts/demo_runner.py
```

Creates:

- `data/outputs/pipeline/pipeline_demo_store_{N}/` — `cam*_events.jsonl`, `cam*_tracking.mp4`
- `data/databases/store_{N}_intelligence.db`

Report: [docs/reports/demo_run_report.md](docs/reports/demo_run_report.md)

### Synthetic validation only (isolated DBs, ENTRY proof)

```powershell
python scripts/demo_validation_run.py --store all
```

| Store | DB | Metric date |
|-------|-----|-------------|
| store_1 | `store_1_validation.db` | 2026-06-01 |
| store_2 | `store_2_validation.db` | 2026-04-10 |

Reports: [docs/reports/demo_validation_report_store_1.md](docs/reports/demo_validation_report_store_1.md), [store_2](docs/reports/demo_validation_report_store_2.md)

### Individual pipeline modules

```powershell
$env:PURPPLE_STORE = "store_1"
python -m pipeline.cam1_processor
python -m pipeline.cam2_processor
python -m pipeline.entry_exit
python -m pipeline.queue
python -m pipeline.pos_loader
python scripts/bridge_pipeline_to_product.py
```

---

## Optional — FastAPI + API-driven dashboard

```powershell
$env:DATABASE_URL = "sqlite:///./data/databases/store_1_intelligence.db"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```powershell
$env:DASHBOARD_USE_API = "true"
$env:API_BASE_URL = "http://localhost:8000"
streamlit run dashboard/streamlit_app.py
```

- API docs: http://localhost:8000/docs  
- Health: http://localhost:8000/health  

---

## Docker (optional)

```powershell
docker compose up --build
docker compose --profile dashboard up --build
```

API: port **8000** · Dashboard (profile): port **8501** · Mount `./data` for SQLite.

---

## Dashboard layouts

| Store key | UI |
|-----------|-----|
| `store_1`, `store_2` | Full SaaS analytics (metrics, funnel, heatmap, anomalies, technical panel) |
| `store1_real` | Manager view — shelf camera videos, brand-area heatmap, revenue KPIs |
| `store2_real` | Same manager metrics and brand areas (no live video panel) |

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/events/ingest` | Batch ingest behavioural events |
| `POST` | `/pos/ingest` | Batch ingest POS transactions |
| `GET` | `/stores/{id}/metrics?date=` | KPIs, dwell, queue, revenue |
| `GET` | `/stores/{id}/funnel?date=` | Session funnel |
| `GET` | `/stores/{id}/heatmap?date=` | Zone engagement |
| `GET` | `/stores/{id}/anomalies?date=` | Operational alerts |
| `GET` | `/health` | Service + DB status |

Reference: [docs/architecture/api_reference.md](docs/architecture/api_reference.md)

---

## Testing

```powershell
pytest
pytest --cov=app
```

---

## Databases and videos (not in git)

- **SQLite** (`data/databases/*.db`) — gitignored; create with `demo_validation_run.py` and `demo_runner.py`.
- **Tracking MP4** (`data/outputs/pipeline/**/*_tracking.mp4`) — gitignored (too large for GitHub); produced by `demo_runner.py`. **store1_real** uses a still frame from these files; **store2_real** is metrics-only.

Full reviewer steps: [docs/SUBMISSION.md](docs/SUBMISSION.md).

---

## Design documents

| Document | Description |
|----------|-------------|
| [docs/SUBMISSION.md](docs/SUBMISSION.md) | **Reviewer / video demo commands** |
| [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) | Completion checklist |
| [docs/reports/project_journey.md](docs/reports/project_journey.md) | Development journey |
| [docs/DESIGN.md](docs/DESIGN.md) | Architecture and data layout |
| [docs/CHOICES.md](docs/CHOICES.md) | Engineering decisions |
| [stores/README.md](stores/README.md) | Per-store config |

---

## License & submission

Hackathon submission for Apex Retail Store Intelligence Challenge.  
Stores: **STORE_BLR_002** (store_1 / store1_real), **STORE_BLR_003** (store_2 / store2_real).
