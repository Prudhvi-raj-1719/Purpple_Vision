# Phase 01 — Intelligence API Foundation

**Status:** Complete  
**Challenge parts:** B (Intelligence API) and C (production readiness)

---

## What we built

The core **Store Intelligence API** — everything needed to receive CCTV behavioural events and POS sales, store them safely, and compute analytics on demand.

| Deliverable | What it does |
|-------------|--------------|
| **Event schema** (`app/models.py`) | Eight event types (ENTRY, EXIT, zone events, billing queue) with validation rules |
| **Event ingest** | `POST /events/ingest` — up to 500 events per batch, duplicate-safe by `event_id` |
| **POS ingest** | `POST /pos/ingest` — sales transactions for conversion matching |
| **SQLite database** | `events` and `pos_transactions` tables under `data/databases/` |
| **FastAPI application** | REST API with health check, structured errors, request logging |
| **Docker** | `docker compose up` runs the API without manual setup |
| **Tests** | Full pytest suite for ingest, sessions, metrics, funnel, heatmap, anomalies |
| **Examples** | Sample JSON in `examples/` for every main endpoint |

---

## Why this phase matters

- Defines the **contract** between the CCTV pipeline and analytics (validated events in, KPIs out).
- Lets reviewers verify the API with `curl` or Swagger at `http://localhost:8000/docs` before running any video processing.
- All later phases (pipeline, sessions, dashboard) plug into this foundation.

---

## How to verify

```powershell
docker compose up --build
pytest
```

---

## Next phases

| Phase | Builds on Phase 01 by… |
|-------|-------------------------|
| [Phase 02](phase_02_detection_pipeline.md) | Generating real events from CCTV |
| [Phase 03](phase_03_session_builder.md) | Turning events into customer visits |
| [Phase 06](phase_06_product_integration.md) | Wiring pipeline output into the API |
