# Purpple Vision

Store intelligence for retail: turn CCTV footage and POS data into visitor sessions, conversion analytics, and a live dashboard.

**North Star metric:** Conversion rate = visitors who purchased ÷ unique visitors.

---

## Overview

### Problem statement

Retail stores capture CCTV and POS transactions separately. Without linking them, managers cannot answer:

- How many visitors entered and reached billing?
- Which shelf zones get the most engagement?
- Where do shoppers drop off before purchase?
- Are queue spikes or dead zones hurting conversion?

### Solution summary

Purpple Vision processes multi-camera CCTV with YOLO + ByteTrack, emits schema-validated behavioural events, loads Brigade POS invoices, persists everything in SQLite, and exposes analytics through a FastAPI layer and Streamlit dashboard.

### Key capabilities

- Multi-camera behavioural event generation (zones, entry/exit, queue, payment)
- Idempotent event and POS ingest with session-based analytics
- Store metrics, funnel, heatmap, and anomaly detection APIs
- Offline purchase matching (CCTV ↔ POS validation)
- Docker deployment with optional dashboard profile
- 125 automated tests (~95% coverage on `app/`)

---

## Features

| Area | Description |
|------|-------------|
| **CCTV analytics** | YOLO11m person detection + ByteTrack across CAM1–CAM5 clips |
| **Zone engagement tracking** | CAM1/CAM2 shelf polygons → ZONE_ENTER, ZONE_EXIT, ZONE_DWELL |
| **Entry/Exit detection** | CAM3 line-crossing → ENTRY, EXIT, REENTRY |
| **Queue/Payment analytics** | CAM5 billing zones → queue join/exit, payment enter/exit |
| **POS ingestion** | Brigade CSV → invoice aggregation → SQLite via bridge or API |
| **Purchase matching** | Offline invoice-centric CCTV correlation (`purchase_matches.json`) |
| **FastAPI analytics** | Metrics, funnel, heatmap, anomalies, health |
| **Streamlit dashboard** | KPIs, funnel, heatmap, anomalies (reads API only) |

---

## Architecture

```
CCTV clips (data/cctv/Brigade_Bangalore/*.mp4)
    │
    ▼
pipeline/  (YOLO, zones, dwell, entry_exit, queue)
    │
    ▼
JSONL events  (data/generated/pipeline_demo/*.jsonl)
    │
    ├── scripts/bridge_pipeline_to_product.py
    │       or POST /events/ingest
    ▼
SQLite  (data/store_intelligence.db)
    │
    ▼
build_sessions()  →  metrics / funnel / heatmap / anomalies
    │
    ├── FastAPI  (port 8000)
    └── Streamlit dashboard  (port 8501)


Brigade POS CSV  (data/pos/*.csv)
    │
    ▼
pipeline/pos_loader  →  aggregated invoices + purpple_pos_transactions.csv
    │
    ├── bridge script  or  POST /pos/ingest
    ▼
SQLite  →  Analytics API  (conversion correlation)
```

Default store: `STORE_BLR_002` · Default demo metric date: `2026-04-10` (UTC)

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11 |
| API | FastAPI, Uvicorn, Pydantic v2 |
| Database | SQLite, SQLAlchemy 2.0 |
| CV | Ultralytics YOLO11m, Supervision, ByteTrack, OpenCV (headless) |
| Data | Pandas, NumPy |
| Dashboard | Streamlit, httpx |
| Container | Docker, Docker Compose |

---

## Repository Structure

```
Purpple_Vision/
├── app/                    # FastAPI intelligence API
├── pipeline/               # CCTV processors, POS loader, event adapter
├── dashboard/
│   └── streamlit_app.py    # Streamlit UI
├── scripts/
│   ├── run_pipeline_demo.py
│   ├── bridge_pipeline_to_product.py
│   ├── seed_from_sample.py
│   └── phase0_import_check.py
├── tests/                  # pytest suite (125 tests)
├── examples/               # Sample API JSON payloads
├── docs/archive/           # Historical audit reports
├── data/                   # CCTV, POS, generated outputs (gitignored)
├── requirements.txt
├── requirements-dev.txt
├── docker-compose.yml
├── Dockerfile
├── DESIGN.md
└── PROJECT_STATE.md
```

---

## Prerequisites

| Requirement | Detail |
|-------------|--------|
| **Python** | **3.11.x** (3.12+ not supported — NumPy/pins target 3.11) |
| **OS** | Windows 10/11, Linux, or macOS |
| **Git** | Clone and version control |
| **Docker** | Optional — containerized API + dashboard |
| **GPU** | Optional — pipeline defaults to CPU (`PIPELINE_DEVICE=cpu` in `.env.example`) |
| **Dataset** | Brigade CCTV MP4s under `data/cctv/Brigade_Bangalore/` and POS CSV under `data/pos/` (not in repo) |

First YOLO run downloads weights automatically if `models/yolo11m.pt` is absent.

---

## Installation

```powershell
git clone https://github.com/Prudhvi-raj-1719/Purpple_Vision.git
cd Purpple_Vision

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt
```

Optional (linting + dev tools):

```powershell
pip install -r requirements-dev.txt
```

Optional local config:

```powershell
copy .env.example .env
```

---

## Verification

```powershell
python scripts/phase0_import_check.py
pytest
```

**Expected result:**

- Import checks: **ALL PASS** (fastapi, sqlalchemy, opencv, ultralytics, supervision, etc.)
- Tests: **125 passed**

With coverage:

```powershell
pytest --cov=app --cov-report=term-missing
```

---

## Running the API

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open:

- Swagger UI: http://localhost:8000/docs
- Health: http://localhost:8000/health

Example query (after data is loaded):

```powershell
curl "http://localhost:8000/stores/STORE_BLR_002/metrics?date=2026-04-10"
curl "http://localhost:8000/stores/STORE_BLR_002/funnel?date=2026-04-10"
curl "http://localhost:8000/stores/STORE_BLR_002/heatmap?date=2026-04-10"
curl "http://localhost:8000/stores/STORE_BLR_002/anomalies?date=2026-04-10"
```

---

## Running the Dashboard

**Terminal 1 — API:**

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Terminal 2 — Streamlit:**

```powershell
$env:API_BASE_URL = "http://localhost:8000"
$env:DEFAULT_STORE_ID = "STORE_BLR_002"
$env:DEFAULT_METRIC_DATE = "2026-04-10"
streamlit run dashboard/streamlit_app.py --server.port 8501
```

Open: http://localhost:8501

When sessions = 0, the dashboard shows an informative empty state instead of blank charts.

---

## Running the CCTV Pipeline

Place Brigade clips here (default paths from `pipeline/config.py`):

```
data/cctv/Brigade_Bangalore/CAM 1.mp4
data/cctv/Brigade_Bangalore/CAM 2.mp4
data/cctv/Brigade_Bangalore/CAM 3.mp4
data/cctv/Brigade_Bangalore/CAM 5.mp4
```

Override footage directory:

```powershell
$env:CCTV_FOOTAGE_DIR = "E:\path\to\cctv\folder"
```

### Individual cameras

**CAM1 — shelf zone engagement:**

```powershell
python -m pipeline.cam1_processor
```

**CAM2 — shelf zone engagement:**

```powershell
python -m pipeline.cam2_processor
```

**CAM3 — entry / exit:**

```powershell
python -m pipeline.entry_exit
```

**CAM5 — queue / payment:**

```powershell
python -m pipeline.queue
```

Outputs: `data/generated/pipeline_demo/cam*_events.jsonl` (+ `.notbk.jsonl` mirrors)

---

## Running the Full Demo Pipeline

Runs CAM1, CAM2, CAM3, and CAM5 in one command and writes a report to `logs/pipeline_demo_report.txt`:

```powershell
python scripts/run_pipeline_demo.py
```

---

## Loading Brigade POS Data

Place CSV at `data/pos/Brigade_Bangalore_10_April_26.csv` or set:

```powershell
$env:BRIGADE_POS_CSV_PATH = "E:\path\to\Brigade_Bangalore_10_April_26.csv"
python -m pipeline.pos_loader
```

Outputs:

- `data/generated/pos/aggregated_transactions.json`
- `data/generated/pos/purpple_pos_transactions.csv`

---

## Purchase Matching

Offline validation — matches POS invoices to CCTV events by time window:

```powershell
python -m pipeline.purchase_matching
```

Output: `data/generated/purchase_matches.json`

Requires pipeline demo JSONL and aggregated POS JSON from steps above.

---

## Bridging Pipeline Data Into Product

Loads generated JSONL + POS CSV into SQLite using the same logic as HTTP ingest, then validates analytics:

```powershell
python scripts/bridge_pipeline_to_product.py
```

Report: `docs/archive/bridge_validation_report.md`

**Alternative — challenge sample files:**

```powershell
python scripts/seed_from_sample.py
```

Expects `data/sample_events.jsonl` and `data/pos_transactions.csv` when present.

---

## End-to-end demo (≈10 minutes)

```powershell
# 1. Install + verify (once)
pip install -r requirements.txt
python scripts/phase0_import_check.py

# 2. Process CCTV + POS (requires dataset files)
python scripts/run_pipeline_demo.py
python -m pipeline.pos_loader

# 3. Load into SQLite
python scripts/bridge_pipeline_to_product.py

# 4. Run API + dashboard (two terminals)
uvicorn app.main:app --host 0.0.0.0 --port 8000
# second terminal:
$env:API_BASE_URL = "http://localhost:8000"
$env:DEFAULT_METRIC_DATE = "2026-04-10"
streamlit run dashboard/streamlit_app.py --server.port 8501
```

---

## Docker

**API only** (no `.env` required):

```powershell
docker compose up --build
```

API: http://localhost:8000/health

**API + Streamlit dashboard:**

```powershell
docker compose --profile dashboard up --build
```

- API: http://localhost:8000
- Dashboard: http://localhost:8501

Stop:

```powershell
docker compose down
```

SQLite persists in `./data/store_intelligence.db` via bind mount.

---

## Current Project Status

| Area | Completion |
|------|------------|
| Intelligence API | ~96% |
| CV pipeline (code) | ~75% |
| CV pipeline (demo output) | ~40% |
| Dashboard | ~82% |
| End-to-end demo | ~35% |
| **Overall** | **~76%** |

Latest bridged snapshot: **66 events**, **24 POS rows**, **0 sessions** (zone-only events; no CAM3 ENTRY in last run).

Full breakdown: [PROJECT_STATE.md](PROJECT_STATE.md)

---

## Known Limitations

- **CAM3 ENTRY events:** Current Brigade demo clips produced **0 ENTRY** events on the last run → **0 sessions** in analytics until entry detection succeeds.
- **Session rules:** Sessions open on ENTRY/REENTRY only; zone events alone do not create sessions.
- **Cross-camera IDs:** Track IDs are per camera — CAM1 `VIS_*` ≠ CAM3 `VIS_*` (no ReID fusion).
- **Purchase matching:** Depends on CCTV/POS timestamp overlap; evening CCTV vs daytime POS yields 0 matches.
- **Revenue KPI:** Dashboard shows **—** — daily revenue totals are not exposed by the analytics API.
- **Staff detection:** `pipeline/staff.py` is a stub.

Details: [DESIGN.md](DESIGN.md) §13 · [docs/archive/final_session_gap_report.md](docs/archive/final_session_gap_report.md)

---

## Documentation

| Document | Purpose |
|----------|---------|
| [README.md](README.md) | Setup and run guide (this file) |
| [DESIGN.md](DESIGN.md) | Architecture, decisions, tradeoffs |
| [PROJECT_STATE.md](PROJECT_STATE.md) | Completion status, gaps, API reference |
| [docs/archive/](docs/archive/) | Historical phase and audit reports |
| [examples/](examples/) | Sample API request/response JSON |

---

## API Endpoints

| Method | Path |
|--------|------|
| `GET` | `/health` |
| `POST` | `/events/ingest` |
| `POST` | `/pos/ingest` |
| `GET` | `/stores/{store_id}/metrics?date=YYYY-MM-DD` |
| `GET` | `/stores/{store_id}/funnel?date=YYYY-MM-DD` |
| `GET` | `/stores/{store_id}/heatmap?date=YYYY-MM-DD` |
| `GET` | `/stores/{store_id}/anomalies?date=YYYY-MM-DD` |
