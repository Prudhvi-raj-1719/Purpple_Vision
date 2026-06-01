# Store Intelligence Platform

**Purpple Vision** — turn CCTV footage and POS transactions into store conversion intelligence for Apex Retail.

**North Star:** Conversion rate = visitors who purchased ÷ unique visitors.

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
    → Dashboard (Streamlit → FastAPI)
```

| Layer | Location | Role |
|-------|----------|------|
| **Detection Layer** | `pipeline/` | CAM1–CAM5 processors, POS loader |
| **Event Stream** | `data/outputs/pipeline/` | Purpple-schema JSONL + NOTEBK mirrors |
| **Intelligence API** | `app/` | FastAPI + SQLite analytics |
| **Dashboard** | `dashboard/streamlit_app.py` | Reviewer UI (API-only) |

Deep dive: [docs/DESIGN.md](docs/DESIGN.md) · Flow diagrams: [docs/architecture/pipeline_flow.md](docs/architecture/pipeline_flow.md)

---

## Repository Structure

```
Purpple_Vision/
├── app/                         # FastAPI intelligence API
├── pipeline/                    # CCTV + POS processors
├── dashboard/streamlit_app.py   # Streamlit dashboard
├── scripts/                     # Bridge, validation, demo_runner orchestrators
├── tests/                       # pytest (126 tests)
├── examples/                    # Sample API JSON payloads
├── data/
│   ├── cctv/                    # CCTV footage (not committed)
│   ├── pos/                     # Raw Brigade POS CSV
│   ├── outputs/                 # Generated pipeline + POS + matching JSON
│   ├── databases/               # SQLite files (runtime)
│   └── synthetic/               # demo_events.jsonl + demo_pos.csv
└── docs/
    ├── DESIGN.md                # Architecture
    ├── CHOICES.md               # Engineering decisions
    ├── PROJECT_STATUS.md        # Completion checklist
    ├── architecture/            # Schema, API, pipeline flow
    ├── reports/
    │   ├── project_journey.md     # Development journey (single document)
    └── archive/                 # Historical phase reports
```

---

## Quick Start

**Prerequisites:** Python 3.11, Docker (optional)

```powershell
pip install -r requirements.txt
python scripts/phase0_import_check.py
docker compose up --build
```

- API: http://localhost:8000/docs
- Health: http://localhost:8000/health

Default database: `data/databases/store_intelligence.db` (override with `DATABASE_URL`).

---

## Run Detection Pipeline

### Individual cameras

```powershell
python -m pipeline.cam1_processor      # Shelf zones (CAM1)
python -m pipeline.cam2_processor      # Shelf zones (CAM2)
python -m pipeline.entry_exit            # Entry/exit (CAM3)
python -m pipeline.queue                 # Billing queue (CAM5)
python -m pipeline.pos_loader            # Brigade POS → aggregated CSV
python -m pipeline.purchase_matching     # Offline CCTV ↔ POS matching
```

Outputs: `data/outputs/pipeline/pipeline_demo/cam*_events.jsonl`

### All cameras (orchestrated)

```powershell
python scripts/run_pipeline_demo.py
```

### Full end-to-end workflow

```powershell
python scripts/demo_runner.py
```

Runs CAM1→CAM5, POS loader, purchase matching, bridge to SQLite, and synthetic validation. Report: [docs/reports/demo_run_report.md](docs/reports/demo_run_report.md)

### Bridge pipeline → product DB

```powershell
python scripts/bridge_pipeline_to_product.py
```

---

## Run Validation Demo

Synthetic dataset with **ENTRY events** (proves sessions + funnel + revenue):

```powershell
python scripts/demo_validation_run.py
```

Uses isolated DB: `data/databases/demo_validation.db`  
Data: `data/synthetic/demo_events.jsonl`, `data/synthetic/demo_pos.csv`  
Metric date: **2026-06-01**

**Expected output:**

```
Visitors: 3
Sessions: 3
Converted: 2
Revenue (INR): 2,148.50
Conversion rate: 66.67%
```

**View on dashboard:**

```powershell
# Terminal 1
$env:DATABASE_URL = "sqlite:///./data/databases/demo_validation.db"
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2
$env:API_BASE_URL = "http://localhost:8000"
$env:DEFAULT_METRIC_DATE = "2026-06-01"
streamlit run dashboard/streamlit_app.py
```

Full report: [docs/reports/demo_validation_report.md](docs/reports/demo_validation_report.md)

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/events/ingest` | Batch ingest behavioural events (idempotent) |
| `POST` | `/pos/ingest` | Batch ingest POS transactions |
| `GET` | `/stores/{id}/metrics?date=` | North Star KPIs, dwell, queue, revenue |
| `GET` | `/stores/{id}/funnel?date=` | Session funnel + drop-off % |
| `GET` | `/stores/{id}/heatmap?date=` | Zone engagement scores |
| `GET` | `/stores/{id}/anomalies?date=` | Queue spike, conversion drop, dead zone |
| `GET` | `/health` | Service + DB + feed staleness |

Full reference: [docs/architecture/api_reference.md](docs/architecture/api_reference.md) · Examples: `examples/*.json`

---

## Dashboard

Streamlit app at `dashboard/streamlit_app.py` — **reads FastAPI only** (no direct SQLite).

| Section | API source | What reviewers see |
|---------|------------|-------------------|
| **System health** | `GET /health` | Service status, DB, last event, STALE_FEED warnings |
| **Key metrics** | `GET /metrics` | Visitors, sessions, revenue, conversion |
| **Queue KPIs** | `GET /metrics` | Queue depth, abandonment rate, avg dwell |
| **Dwell by zone** | `GET /metrics` | Per-zone average dwell table |
| **Conversion funnel** | `GET /funnel` | Entry → zone → billing → purchase + drop-off |
| **Zone heatmap** | `GET /heatmap` | Engagement scores, dwell charts, confidence badge |
| **Anomalies** | `GET /anomalies` | Queue / conversion / dead-zone alerts with actions |

Empty state when no ENTRY sessions exist (common with zone-only Brigade demo data).

---

## Testing

```powershell
pytest
pytest --cov=app
```

126 tests covering ingestion, sessions, metrics, funnel, heatmap, anomalies, health, and edge cases.

---

## Design Documents

| Document | Description |
|----------|-------------|
| [docs/reports/project_journey.md](docs/reports/project_journey.md) | **Development journey** — Phase 1 to final demo |
| [docs/DESIGN.md](docs/DESIGN.md) | System architecture, sessions, analytics, limitations |
| [docs/CHOICES.md](docs/CHOICES.md) | Five engineering decisions with alternatives |
| [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) | Completion checklist |

---

## Data Directory

```
data/
├── cctv/              # CCTV clips
├── pos/               # Raw POS exports
├── outputs/           # Regenerated pipeline/POS/matching artifacts
├── databases/         # SQLite (store_intelligence, demo_*, test_*)
└── synthetic/         # Validation dataset (ENTRY-based)
```

See [docs/DESIGN.md § Data layout](docs/DESIGN.md) for details.

---

## License & submission

Hackathon submission for Apex Retail Store Intelligence Challenge. Brigade demo store: `STORE_BLR_002`.
