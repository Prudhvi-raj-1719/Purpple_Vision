# Phase 06 — End-to-End Product Integration

**Status:** Complete  
**Goal:** Connect CCTV pipeline, POS, SQLite, API, and dashboard into one reviewer workflow.

---

## What we built

| Piece | What it does |
|-------|--------------|
| **Bridge script** | `scripts/bridge_pipeline_to_product.py` — loads JSONL + POS CSV into SQLite using the same logic as HTTP ingest |
| **Demo runner** | `scripts/demo_runner.py` — one command: cameras → POS → purchase matching → bridge → synthetic validation → report |
| **Per-store intelligence DB** | `store_1_intelligence.db` / `store_2_intelligence.db` from `stores/*/store.json` — fresh per CCTV demo run (does not touch `store_intelligence.db` or `store_*_validation.db`) |
| **Clean outputs** | Each `scripts/demo_runner.py` run clears `pipeline_demo/*` and `purchase_matches.json` before processing |
| **Streamlit dashboard** | `dashboard/streamlit_app.py` — reads FastAPI only (metrics, funnel, heatmap, anomalies, health) |
| **Synthetic validation** | `scripts/demo_validation_run.py` — proves non-zero sessions and revenue with ENTRY-based test data |

---

## End-to-end flow (today)

```
CCTV clips → CAM1/2/3/5 processors → JSONL in data/outputs/pipeline/pipeline_demo/
POS CSV    → pos_loader           → data/outputs/pos/
Bridge     → store_N_intelligence.db → sessions + KPIs
FastAPI    → GET /metrics, /funnel, /heatmap, /anomalies
Streamlit  → reviewer dashboard
```

---

## How reviewers should run it

**Quick proof (non-zero KPIs, ~seconds):**

```powershell
python scripts/demo_validation_run.py

$env:DATABASE_URL = "sqlite:///./data/databases/demo_validation.db"
uvicorn app.main:app --port 8000

$env:API_BASE_URL = "http://localhost:8000"
$env:DEFAULT_METRIC_DATE = "2026-06-01"
streamlit run dashboard/streamlit_app.py
```

**Full Brigade pipeline (long-running, CPU):**

```powershell
python scripts/demo_runner.py
```

Report written to `demo_run_report.md` at repo root and [docs/reports/demo_run_report.md](../../reports/demo_run_report.md).

---

## Submission-ready checklist

- [x] Pipeline writes Purpple-schema events  
- [x] POS loader produces ingest-ready CSV  
- [x] Bridge ingests into SQLite  
- [x] All analytics endpoints return JSON  
- [x] Dashboard displays API data  
- [x] Validation dataset proves conversion and revenue KPIs  
- [x] `scripts/demo_runner.py` reproducible (fresh DB + fresh JSONL each run)

---

## Known demo limitations (honest)

| Topic | Note |
|-------|------|
| Brigade CCTV only | May yield zone events but **0 ENTRY** → 0 sessions on bridged DB |
| Purchase matching | Offline JSON only; not shown on dashboard |
| Staff detection | Not implemented in pipeline |
| Live WebSocket dashboard | Not implemented (manual refresh) |

Use **validation date `2026-06-01`** and **demo_validation.db** for judging KPIs and UI.

---

## Related

- [Phase 02](phase_02_detection_pipeline.md) · [Phase 04](phase_04_pos_integration.md)  
- [final_project_summary.md](final_project_summary.md)  
