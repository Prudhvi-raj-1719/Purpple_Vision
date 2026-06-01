# Store Intelligence Platform — Project Journey

**Purpple Vision** · Brigade Bangalore demo store `STORE_BLR_002`  
**North Star:** Conversion rate = visitors who purchased ÷ unique visitors

This document is the single chronological story from project foundation to a demonstrable end-to-end system. It reflects the **current repository** — not migration history or repository cleanup work.

**Quick links:** [DESIGN.md](../DESIGN.md) · [PROJECT_STATUS.md](../PROJECT_STATUS.md) · [architecture/](../architecture/)

---

# Phase 1 — Foundation

## Objective

Establish the Intelligence API foundation: validated events and POS transactions in SQLite, exposed over HTTP, ready for analytics and a dashboard.

## Architecture

```
Client / Pipeline  →  POST /events/ingest, POST /pos/ingest  →  SQLite  →  (later) analytics
```

Behavioural events are **immutable** and idempotent by `event_id`. Analytics are **derived at query time** from stored events and POS rows (sessions are not persisted as a separate table).

See [architecture/system_architecture.md](../architecture/system_architecture.md) for the full layered view.

## Components implemented

| Component | Role |
|-----------|------|
| `app/main.py` | FastAPI app, lifespan, routers, error handling |
| `app/db.py` | SQLAlchemy engine, `events` / `pos_transactions`, `init_db()` |
| `app/models.py` | Pydantic schemas — 8 event types, POS transactions, API responses |
| `app/ingestion.py` | `POST /events/ingest` — batch ≤500, partial success |
| `app/logging_config.py` | Structured JSON logs, request trace IDs |
| `Dockerfile`, `docker-compose.yml` | One-command API startup |
| `examples/*.json` | Sample request/response payloads |
| `tests/test_*.py` | Ingestion and core API tests |

### Event schema (behavioural)

| Type | Purpose |
|------|---------|
| ENTRY / EXIT / REENTRY | Doorway — opens and closes sessions |
| ZONE_ENTER / ZONE_EXIT / ZONE_DWELL | Product zone engagement |
| BILLING_QUEUE_JOIN / BILLING_QUEUE_ABANDON | Checkout queue |

### POS schema

`PosTransaction` — `transaction_id`, `store_id`, UTC `timestamp`, `basket_value_inr`.

### Problem understanding

Offline retail has **CCTV** and **POS** in silos. Store managers need one place to answer: How many visitors? Where do they go? Who bought? Is the queue too long? Which zones are ignored?

## Technical decisions

- **SQLite** for zero-ops hackathon deployment (`data/databases/store_intelligence.db`).
- **Event-driven persistence** — raw events stored; sessions computed in memory (see [CHOICES.md](../CHOICES.md)).
- **UUID v4** `event_id` for safe retries on ingest.

## Validation

```powershell
docker compose up --build
pytest
```

## Outcome

**System foundation established** — reviewers can ingest events and POS rows and call health check before any CCTV processing runs.

---

# Phase 2 — CCTV Pipeline

## Objective

Convert Brigade CCTV footage into **structured behavioural events** the Intelligence API can ingest.

## Architecture

```
MP4 clips (data/cctv/)  →  YOLO11m + ByteTrack  →  zone/line rules  →  JSONL (Purpple schema)
```

Reference: [architecture/pipeline_flow.md](../architecture/pipeline_flow.md)

## Components implemented

| Camera | Module | Events |
|--------|--------|--------|
| **CAM1** | `pipeline/cam1_processor.py`, `dwell.py` | ZONE_ENTER, ZONE_EXIT, ZONE_DWELL (shelf — left) |
| **CAM2** | `pipeline/cam2_processor.py`, `dwell.py` | Same zone/dwell pattern (shelf — right) |
| **CAM3** | `pipeline/entry_exit.py` | **ENTRY**, **EXIT**, REENTRY (store doorway) |
| **CAM5** | `pipeline/queue.py` | BILLING_QUEUE_JOIN, BILLING_QUEUE_ABANDON |

**Not implemented:** CAM4 staff processor (`pipeline/staff.py` is a placeholder). Staff can still be flagged on events via `is_staff` when set.

### Technical stack

| Piece | Location |
|-------|----------|
| Person detection | `pipeline/detect.py` (YOLO11m) |
| Tracking | `pipeline/tracker.py` (ByteTrack) |
| Zone polygons | `pipeline/zones.py` |
| Event emission | `pipeline/emit.py` |
| Schema adapter | `pipeline/event_adapter.py` |
| Config | `pipeline/config.py` (`PROCESS_EVERY_N_FRAMES = 10` for CPU runtime) |

### Outputs

| File | Path |
|------|------|
| Purpple JSONL | `data/outputs/pipeline/pipeline_demo/cam*_events.jsonl` |
| NOTEBK mirror | `data/outputs/pipeline/pipeline_demo/cam*_events.notbk.jsonl` |

## Technical decisions

- **Rule-based zones and line crossing** after detection — auditable for reviewers.
- **Frame skipping** (every 10th frame) so ~30-minute clips finish in ~25–30 minutes per camera on CPU-class hardware.
- **Dual JSONL** — Purpple schema for the API; NOTEBK mirror for offline purchase matching.

## Validation

```powershell
python -m pipeline.cam1_processor
python scripts/run_pipeline_demo.py
```

Audit evidence: documented in Phase 2 sections below (CAM3 frame-skip fix, inference frequency alignment).

## Outcome

**CCTV → structured behavioural events.** Zone and queue signals are available; **ENTRY events from CAM3 are required** for downstream sessions (Phase 3).

---

# Phase 3 — Session Engine

## Objective

Turn raw events into **customer journeys** (sessions) — the foundation for every business KPI.

## Architecture

```
Events (chronological)  →  build_sessions()  →  VisitorSession list  →  metrics / funnel / heatmap / anomalies
```

Reference: [architecture/session_lifecycle.md](../architecture/session_lifecycle.md)

## Components implemented

| Rule | Implementation (`app/sessions.py`) |
|------|----------------------------------|
| **ENTRY / REENTRY** | Opens a new session |
| **EXIT** | Closes session |
| **ZONE_*** | Records zones visited and dwell per zone |
| **BILLING_QUEUE_*** | Sets `joined_queue`, `abandoned_queue`, `reached_billing`, `billing_activity_at` |
| **Orphan events** | Zone/queue events without open session are **discarded** |
| **REENTRY** | New session; visitor counted once in funnel |
| **Staff** | Sessions built; `customer_sessions()` excludes `is_staff` |

### Session fields used by analytics

- `zones_visited`, `total_dwell_ms_by_zone`
- `joined_queue`, `abandoned_queue`
- `reached_billing`, `billing_activity_at`

## Technical decisions

- **Sessions derived at query time** — no separate `sessions` table; simplifies idempotent event ingest.
- **ENTRY is mandatory** — CAM1/CAM2-only pipeline output produces **zero sessions** (zone-only Brigade footage cannot open visitor sessions without CAM3 ENTRY events).

## Validation

```powershell
python scripts/demo_validation_run.py
```

Synthetic dataset includes ENTRY events → **3 sessions**, **3 visitors**.

## Outcome

**Customer journeys reconstructed from events.** All analytics in Phase 5 read sessions built from ingested events.

---

# Phase 4 — POS Integration

## Objective

Link **sales data** to visitor behaviour — conversion rate and revenue require POS transactions aligned with sessions.

## Architecture

```
Brigade CSV  →  pos_loader  →  purpple_pos_transactions.csv  →  POST /pos/ingest or bridge  →  SQLite
                                                                                                    ↓
                                                                              pos_correlation (5-min window)
```

## Components implemented

### POS ingestion (API)

| Endpoint | Module |
|----------|--------|
| `POST /pos/ingest` | `app/pos_ingestion.py` |

Idempotent by `transaction_id`; batch ≤500; partial success.

### Brigade POS loader

| Piece | Role |
|-------|------|
| `pipeline/pos_loader.py` | Line-item CSV → invoice-level JSON + Purpple CSV |
| Outputs | `data/outputs/pos/aggregated_transactions.json`, `purpple_pos_transactions.csv` |
| Store map | Brigade `ST1008` → `STORE_BLR_002` |

### Purchase correlation (product KPIs)

`app/pos_correlation.py` — a visitor converts when **billing activity** in a session occurred within **5 minutes before** the POS transaction timestamp.

Drives: conversion rate, funnel “Purchased”, and correlation flags on sessions.

### Offline purchase matching (engineering validation)

| Piece | Role |
|-------|------|
| `pipeline/purchase_matching.py` | Matches invoices to CCTV events in a time window |
| Output | `data/outputs/purchase_matching/purchase_matches.json` |
| Confidence | Per-invoice `confidence_score` in match records |

**Not in the live API** — offline JSON only; dashboard and `/metrics` use session + POS correlation, not this file.

## Technical decisions

- **Two paths to SQLite** — HTTP ingest or `scripts/bridge_pipeline_to_product.py` (same ingest functions).
- **Offline matching** kept separate so reviewers can compare invoice timing vs session-based conversion.

## Validation

```powershell
python -m pipeline.pos_loader
pytest tests/test_pos_ingestion.py tests/test_metrics.py -q
```

## Outcome

**Behaviour linked with purchases** — revenue and conversion KPIs are computable when ENTRY sessions and aligned POS timestamps exist.

---

# Phase 5 — Analytics API

## Objective

Transform sessions and POS data into **business intelligence** — KPIs, funnel, heatmap, and operational alerts over HTTP.

## Architecture

```
SQLite  →  build_sessions()  →  compute_store_metrics / funnel / heatmap / anomalies  →  FastAPI JSON
```

Reference: [architecture/api_reference.md](../architecture/api_reference.md), [architecture/business_metrics.md](../architecture/business_metrics.md)

## Components implemented

### Metrics (`GET /stores/{id}/metrics`)

| Field | Business meaning |
|-------|------------------|
| `unique_visitors` | Distinct visitors (ENTRY/REENTRY) |
| `total_sessions` | Customer sessions |
| `conversion_rate` | North Star — converted visitors ÷ unique visitors |
| `total_revenue_inr` | Sum of POS `basket_value_inr` for the day |
| `average_dwell_time_ms` | Mean in-zone dwell per session |
| `average_dwell_by_zone` | Per-zone dwell table |
| `current_queue_depth` | Latest queue depth from billing join events |
| `queue_abandonment_rate` | Queue joins that left without purchase |
| `billing_reach_rate` | Sessions that reached billing |

### Funnel (`GET /stores/{id}/funnel`)

Visitor-level stages (no REENTRY double-count):

1. Unique visitors (entry)  
2. Reached any zone  
3. Billing queue  
4. Converted visitors (POS)

Each stage includes **drop_off_pct** vs the prior stage.

### Heatmap (`GET /stores/{id}/heatmap`)

| Field | Meaning |
|-------|---------|
| Per-zone visit count, dwell, `normalized_score` (0–100) |
| `data_confidence` | `false` when &lt; 20 customer sessions (warns reviewers) |

### Anomalies (`GET /stores/{id}/anomalies`)

| Type | Purpose |
|------|---------|
| `QUEUE_SPIKE` | Unusual billing queue activity |
| `CONVERSION_DROP` | Low conversion with billing traffic |
| `DEAD_ZONE` | Low zone engagement score |

Each includes `severity`, `suggested_action`, and `detected_at`.

### Health (`GET /health`)

Service status, database availability, per-store last event time, **STALE_FEED** warnings.

### Ingestion

| Method | Path |
|--------|------|
| `POST` | `/events/ingest` |
| `POST` | `/pos/ingest` |

### Modules

`app/metrics.py`, `app/funnel.py`, `app/heatmap.py`, `app/anomalies.py`, `app/health.py`

## Technical decisions

- **Visitor-level funnel** — avoids double-counting on REENTRY.
- **Fixed daily anomaly thresholds** — no 7-day rolling baseline (would need multi-day history).
- **Heatmap confidence gate** at 20 sessions — matches challenge reliability guidance.

## Validation

```powershell
pytest
```

**126 tests** covering ingest, sessions, POS, metrics, funnel, heatmap, anomalies, health, and edge cases (~95% coverage on `app/` per project docs).

## Outcome

**Behaviour transformed into business intelligence** — store managers can query KPIs, funnel, heatmap, and alerts for any UTC day with ingested data.

---

# Phase 6 — Dashboard and Validation

## Objective

Give reviewers a **visual, end-to-end demo**: run pipelines, prove KPIs, and explore results in a dashboard without reading raw JSONL or SQL.

## Architecture

```
Streamlit (dashboard/streamlit_app.py)  →  HTTP  →  FastAPI  →  SQLite
```

The dashboard **never** reads SQLite or JSONL directly.

Reference: [architecture/validation_flow.md](../architecture/validation_flow.md)

## Components implemented

### Streamlit dashboard

| Section | API source |
|---------|------------|
| **System health** | `GET /health` — status, DB, last event, feed Live/STALE |
| **Key metrics** | `GET /metrics` — visitors, sessions, revenue, conversion |
| **Queue KPIs** | `GET /metrics` — queue depth, abandonment |
| **Dwell by zone** | `GET /metrics` — `average_dwell_by_zone` table |
| **Conversion funnel** | `GET /funnel` — stages and drop-off % |
| **Zone heatmap** | `GET /heatmap` — scores + **data confidence** badge |
| **Anomalies** | `GET /anomalies` — alerts with suggested actions |

Empty state when **zero sessions** exist for the selected date (common on Brigade-bridged data without ENTRY).

### Validation system

| Script | Role |
|--------|------|
| `scripts/demo_validation_run.py` | Isolated `demo_validation.db`; synthetic ENTRY dataset; writes validation report |

**Synthetic validation dataset** (`data/synthetic/`):

| Metric | Expected |
|--------|----------|
| Visitors | 3 |
| Sessions | 3 |
| Converted | 2 |
| Revenue (INR) | 2,148.50 |
| Conversion | 66.7% |

Metric date: **2026-06-01**

### Demo orchestration

| Script | Role |
|--------|------|
| `scripts/demo_runner.py` | Full workflow: fresh `demo_product.db`, clear pipeline JSONL, CAM1–5, POS loader, purchase matching, bridge, synthetic validation, `demo_run_report.md` |
| `scripts/bridge_pipeline_to_product.py` | Load pipeline JSONL + POS CSV into SQLite |
| `scripts/run_pipeline_demo.py` | Run all camera processors |

## Technical decisions

- **API-only dashboard** — single source of truth for UI and external clients.
- **Isolated validation DB** — proves analytics without touching production `store_intelligence.db`.
- **Reproducible demo runs** — `scripts/demo_runner.py` deletes prior demo DB and pipeline_demo files before each run.

## Validation

```powershell
# Fast proof (recommended for judges)
python scripts/demo_validation_run.py
$env:DATABASE_URL = "sqlite:///./data/databases/demo_validation.db"
uvicorn app.main:app --port 8000
$env:API_BASE_URL = "http://localhost:8000"
$env:DEFAULT_METRIC_DATE = "2026-06-01"
streamlit run dashboard/streamlit_app.py

# Full Brigade pipeline (long CPU run)
python scripts/demo_runner.py
```

Evidence: [demo_validation_report.md](demo_validation_report.md), [demo_run_report.md](demo_run_report.md)

## Outcome

**End-to-end demonstrable system** — from CCTV clips and POS CSV through KPIs and a reviewer dashboard, with a deterministic validation path for non-zero metrics.

---

# Final Project Summary

## Problem

Store managers lack visibility into **in-store customer behaviour**. CCTV and POS data exist separately, so questions go unanswered: How many visitors came in? Where did they spend time? Who reached checkout? Who actually bought? Which zones need attention?

## Solution

**Purpple Vision** — an AI-assisted Store Intelligence platform that:

- Processes CCTV with detection and zone rules (Phase 2)
- Builds customer sessions from behavioural events (Phase 3)
- Ingests POS sales and correlates purchases (Phase 4)
- Exposes analytics over FastAPI (Phase 5)
- Visualizes KPIs in a Streamlit dashboard (Phase 6)

```
CCTV + POS  →  Events  →  Sessions  →  Analytics API  →  Dashboard
```

## Final capabilities

| Capability | Status |
|------------|--------|
| Behaviour tracking (zone, entry, queue events) | Implemented |
| Session reconstruction | Implemented |
| Conversion measurement | Implemented |
| Revenue attribution (`total_revenue_inr`) | Implemented |
| Queue monitoring | Implemented |
| Zone heatmaps | Implemented |
| Anomaly detection (queue, conversion, dead zone) | Implemented |
| Dashboard analytics | Implemented |
| Docker deployment | Implemented |
| One-command demo (`scripts/demo_runner.py`) | Implemented |

## Validation

| Evidence | Detail |
|----------|--------|
| **Automated tests** | 126 pytest tests on `app/` |
| **Synthetic demo** | `demo_validation_run.py` — 3 sessions, ₹2,148.50 revenue, 66.7% conversion |
| **End-to-end workflow** | `scripts/demo_runner.py` — pipeline → bridge → report |
| **API examples** | `examples/*.json` for all main endpoints |

## Recommended reviewer path (5 minutes)

1. Read [README.md](../../README.md)  
2. Run validation demo (commands in Phase 6 above)  
3. Skim [DESIGN.md](../DESIGN.md) and [business_question_mapping.md](../architecture/business_question_mapping.md)  
4. Optional: `python scripts/demo_runner.py` for full Brigade CCTV run  

## Known limitations (current, honest)

| Limitation | Detail |
|------------|--------|
| **Brigade CCTV demo** | Last runs: CAM1/CAM2 emit zone events; **CAM3/CAM5 may emit zero events** on bundled clips → **0 sessions** when bridged to SQLite |
| **Validation dataset** | Proves analytics with ENTRY events — use `demo_validation.db` and date `2026-06-01` for non-zero dashboard |
| **Purchase matching** | Offline JSON; depends on timestamp overlap between evening CCTV and daytime POS — often low match count on Brigade data |
| **Staff detection** | No CAM4 processor; `is_staff` logic exists in API but pipeline does not classify staff |
| **Anomaly baselines** | Fixed daily thresholds, not 7-day rolling history |
| **Real-time updates** | Dashboard refreshes on load; no WebSocket live feed |
| **Cross-camera ReID** | Visitor IDs are per-camera track tokens |

## Submission status

The platform is **submission-ready**: working API, documented architecture, pytest coverage, synthetic validation with non-zero KPIs, and optional full pipeline demo for Brigade footage.

---

