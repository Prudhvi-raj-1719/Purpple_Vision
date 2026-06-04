# Hackathon submission — how to run Purpple Vision

Use this page for **reviewer setup** and **screen recording**. No cloud deployment is required.

---

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| **Python 3.11+** | 3.11 recommended |
| **Git clone** | This repository |
| **YOLO weights** | `models/yolo11m.pt` (download separately; not committed) |
| **CCTV footage** | `data/cctv/` (not committed; needed only to **regenerate** pipeline) |
| **FFmpeg** | Required for **in-browser shelf videos** on `store1_real` / `store2_real` |

### Install FFmpeg (Windows)

```powershell
choco install ffmpeg -y
# or: winget install --id Gyan.FFmpeg -e
```

Restart the terminal, then verify: `ffmpeg -version`

---

## Fastest path — dashboard only (committed databases)

Committed SQLite fixtures (when present in the repo):

| File | Dashboard store | Trading day |
|------|-----------------|-------------|
| `data/databases/store_1_validation.db` | **Store 1** | 2026-06-01 |
| `data/databases/store_2_validation.db` | **Store 2** | 2026-04-10 |
| `data/databases/store_1_intelligence.db` | **store1_real** | 2026-04-10 |
| `data/databases/store_2_intelligence.db` | **store2_real** | 2026-04-10 |

```powershell
cd Purpple_Vision
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run dashboard/streamlit_app.py
```

Open http://localhost:8501 → pick a store in the sidebar → **Refresh** if needed.

**Video recording tip:** Select **store1_real** or **store2_real**, trading day **2026-04-10**, after FFmpeg is installed.

---

## Regenerate CCTV + intelligence DB (per store)

```powershell
cd Purpple_Vision
.\.venv\Scripts\Activate.ps1

# Store 1 — Brigade footage
$env:PURPPLE_STORE = "store_1"
python scripts/demo_runner.py

# Store 2 — competition footage
$env:PURPPLE_STORE = "store_2"
python scripts/demo_runner.py
```

Outputs:

- Pipeline JSONL + tracking MP4: `data/outputs/pipeline/pipeline_demo_store_{1,2}/`
- Intelligence SQLite: `data/databases/store_{1,2}_intelligence.db`

Then run Streamlit (commands above) and choose **store1_real** or **store2_real**.

---

## Synthetic validation stores (non-CCTV proof)

Proves ENTRY sessions, funnel, and revenue without Brigade ENTRY lines:

```powershell
python scripts/demo_validation_run.py --store all
streamlit run dashboard/streamlit_app.py
```

| Dashboard | Date |
|-----------|------|
| Store 1 | 2026-06-01 |
| Store 2 | 2026-04-10 |

Reports: [reports/demo_validation_report_store_1.md](reports/demo_validation_report_store_1.md), [reports/demo_validation_report_store_2.md](reports/demo_validation_report_store_2.md)

---

## Optional — FastAPI

```powershell
$env:DATABASE_URL = "sqlite:///./data/databases/store_1_intelligence.db"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

To drive the dashboard via HTTP instead of direct SQLite:

```powershell
$env:DASHBOARD_USE_API = "true"
$env:API_BASE_URL = "http://localhost:8000"
streamlit run dashboard/streamlit_app.py
```

---

## Optional — Docker

```powershell
docker compose up --build
docker compose --profile dashboard up --build
```

- API: http://localhost:8000  
- Dashboard (profile): http://localhost:8501  

Mount `./data` so SQLite under `data/databases/` is visible in the container.

---

## Tests

```powershell
pytest
```

---

## Dashboard store selector

| Sidebar label | Data source |
|---------------|-------------|
| Store 1 | `store_1_validation.db` (synthetic) |
| Store 2 | `store_2_validation.db` (synthetic) |
| store1_real | `store_1_intelligence.db` + shelf tracking videos |
| store2_real | `store_2_intelligence.db` + shelf tracking videos |

`store1_real` / `store2_real` use a **manager-friendly** layout (live camera videos, brand areas, revenue — no purchase/conversion cards).  
- **store1_real** — shelf cameras (CAM1/CAM2 tracking MP4)  
- **store2_real** — same manager metrics as store1_real (no live video panel)  
Store 1 / Store 2 use the full **SaaS analytics** layout.

---

## Databases (not in the repository)

SQLite files under `data/databases/` are **gitignored**. After clone, run the commands in **Fastest path** or **Regenerate CCTV** above so `store_*_validation.db` and `store_*_intelligence.db` exist locally before opening Streamlit.
