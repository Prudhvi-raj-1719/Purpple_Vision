# Store Intelligence

> **Status:** Intelligence API complete (ingest, metrics, funnel, heatmap, anomalies, health). Detection pipeline and dashboard are not yet implemented.

## Overview

End-to-end Store Intelligence system for the Apex Retail 48-hour engineering challenge.
Converts CCTV footage into structured behavioral events and exposes real-time analytics via REST API.

## Prerequisites

- **Python 3.11.x** (required — see troubleshooting if you have 3.12 or 3.13)
- **Git**

Optional:

- Docker & Docker Compose (for containerized deployment)

## Quick Setup on a New Machine

### 1. Clone repository

```powershell
git clone https://github.com/Prudhvi-raj-1719/Purpple_Vision.git
cd Purpple_Vision
```

### 2. Create virtual environment (Python 3.11)

Use Python 3.11 explicitly — do not use the system default if it is 3.12 or 3.13.

```powershell
# Windows (recommended)
py -3.11 -m venv .venv

# macOS / Linux (if python3.11 is installed)
python3.11 -m venv .venv
```

### 3. Activate virtual environment

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# Windows CMD
.\.venv\Scripts\activate.bat

# macOS / Linux
source .venv/bin/activate
```

### 4. Upgrade pip

```powershell
python -m pip install --upgrade pip
```

### 5. Install requirements

```powershell
pip install -r requirements.txt
```

> First install may take 5–15 minutes because `ultralytics` pulls in `torch` (~700 MB+).

### 6. Create `.env` from `.env.example`

```powershell
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

### 7. Verify installation

```powershell
python --version
pip check
python scripts/phase0_import_check.py
```

Expected: `Python 3.11.x`, `No broken requirements found`, and `Overall: ALL PASS`.

Quick one-liner check:

```powershell
python -c "import fastapi, sqlalchemy, cv2, ultralytics, pandas, streamlit, pytest; print('All core packages OK')"
```

## Troubleshooting

### Python 3.13 is not supported

**Symptom:** `pip install -r requirements.txt` fails while building `numpy` from source, with errors about missing C compilers (`cl`, `gcc`, Meson build failure).

**Cause:** Dependencies are pinned for **Python 3.11.x**. NumPy 1.26.4 has pre-built wheels for 3.11 but not for 3.13, so pip tries to compile from source.

**Fix:**

```powershell
# Check your version
python --version

# Recreate the venv with Python 3.11
deactivate
Remove-Item -Recurse -Force .venv   # Windows
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Torch installation is slow

**Symptom:** `pip install` appears stuck on `torch` or `torchvision` for several minutes.

**Cause:** Normal behavior. `ultralytics` depends on PyTorch, which is a large download (~700 MB+ on CPU builds).

**Fix:** Wait for the install to finish. Do not interrupt unless it fails with an error. Verify after install:

```powershell
python -c "import torch; print(torch.__version__)"
```

### OpenCV installation issues

**Symptom:** `import cv2` fails, or pip reports conflicts between `opencv-python` and `opencv-python-headless`.

**Cause:** This project pins `opencv-python-headless`. `ultralytics` may also install `opencv-python` as a transitive dependency.

**Fix:**

```powershell
pip install --force-reinstall opencv-python-headless==4.10.0.84
python -c "import cv2; print(cv2.__version__)"
```

If import still fails on Linux, install system libraries:

```bash
sudo apt-get install -y libgl1 libglib2.0-0
```

On Windows, reinstalling the headless wheel is usually sufficient.

## Project Structure

```
├── app/              # FastAPI intelligence API
├── pipeline/         # CV detection & event emission pipeline
├── dashboard/        # Streamlit live dashboard (bonus)
├── tests/            # pytest test suite
├── scripts/          # Utility scripts
├── data/             # Dataset (gitignored — place challenge ZIP contents here)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── DESIGN.md
└── CHOICES.md
```

## Run the API locally

```powershell
.\.venv\Scripts\Activate.ps1
copy .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### Seed sample data (optional)

Place challenge files under `./data/` then:

```powershell
python scripts/seed_from_sample.py
```

Loads `data/sample_events.jsonl` and `data/pos_transactions.csv` when present (idempotent).

### Run tests

```powershell
pytest
pytest --cov=app --cov-report=term-missing
```

107 tests; `app/` coverage ~95%.

## API endpoints

| Method | Path | Module |
|--------|------|--------|
| `GET` | `/health` | `app/health.py` |
| `POST` | `/events/ingest` | `app/ingestion.py` |
| `GET` | `/stores/{store_id}/metrics?date=YYYY-MM-DD` | `app/metrics.py` |
| `GET` | `/stores/{store_id}/funnel?date=YYYY-MM-DD` | `app/funnel.py` |
| `GET` | `/stores/{store_id}/heatmap?date=YYYY-MM-DD` | `app/heatmap.py` |
| `GET` | `/stores/{store_id}/anomalies?date=YYYY-MM-DD` | `app/anomalies.py` |

Example payloads: `examples/*.json` (metrics include `average_dwell_by_zone` and `current_queue_depth`; heatmap includes `data_confidence`; anomalies include `suggested_action`)

## Detection pipeline (not yet implemented)

The `pipeline/` package contains module stubs (`detect.py`, `tracker.py`, `emit.py`, etc.). Until video processing is built:

1. Ingest events via `POST /events/ingest`, or  
2. Run `python scripts/seed_from_sample.py` with dataset files in `./data/`.

Planned flow: process CCTV clips → JSONL → ingest → analytics (see [DESIGN.md](./DESIGN.md)).

## Docker

SQLite is file-based — no database container is required. From a clean clone:

```powershell
git clone https://github.com/Prudhvi-raj-1719/Purpple_Vision.git
cd Purpple_Vision
docker compose up --build
```

No `.env` file is required. Optional: copy `.env.example` to `.env` to override `API_PORT`, `LOG_LEVEL`, etc.

The API listens on [http://localhost:8000](http://localhost:8000). Data persists under `./data` and logs under `./logs`.

### Verify the API

```powershell
# Health (service status, database, per-store feeds)
curl http://localhost:8000/health

# Store metrics (empty store returns valid JSON with zeros)
curl "http://localhost:8000/stores/STORE_BLR_002/metrics?date=2026-03-03"
curl "http://localhost:8000/stores/STORE_BLR_002/funnel?date=2026-03-03"
curl "http://localhost:8000/stores/STORE_BLR_002/heatmap?date=2026-03-03"
curl "http://localhost:8000/stores/STORE_BLR_002/anomalies?date=2026-03-03"
```

Expected: HTTP 200 and JSON from each endpoint.

### Stop and restart (SQLite persistence)

```powershell
docker compose down
docker compose up -d
```

The SQLite file `./data/store_intelligence.db` survives restarts via the bind mount.

### Optional dashboard profile

```powershell
docker compose --profile dashboard up --build
```

## Documentation

- [DESIGN.md](./DESIGN.md) — Architecture overview
- [CHOICES.md](./CHOICES.md) — Technical decision log

## Status

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Scaffold & environment | Complete |
| 1–2 | Event schema, ingest, health | Complete |
| 3 | Session engine, metrics, POS correlation | Complete |
| 4 | Funnel, heatmap, anomalies, production health/logging | Complete |
| 5 | Detection pipeline (YOLO) | Not started |
| 6 | Live dashboard | Not started |
