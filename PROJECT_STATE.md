# Purpple_Vision — Project State Summary

**Repository:** [Prudhvi-raj-1719/Purpple_Vision](https://github.com/Prudhvi-raj-1719/Purpple_Vision)  
**Challenge:** Apex Retail 48-Hour Engineering Hiring Challenge  
**Last updated:** Phase 3A complete (Session Engine)

---

## 1. Project Goal

Build an end-to-end **Store Intelligence System** for Apex Retail (40 stores, 8 cities) that:

1. Processes raw **CCTV footage** into structured behavioural events  
2. Ingests events into an **Intelligence API**  
3. Computes **real-time store analytics** (metrics, funnel, heatmap, anomalies)  
4. Optionally displays a **live dashboard**

**North Star metric:**

```
Conversion Rate = Visitors who completed a purchase ÷ Total unique visitors in a session window
```

The system must run via `docker compose up`, be production-aware, and be fully documented (`DESIGN.md`, `CHOICES.md`).

---

## 2. PDF Requirements

### Pipeline stages (4)

| Stage | Requirement |
|---|---|
| **Detection Layer** | Detect people, track movement, entry/exit direction, assign `visitor_id` |
| **Event Stream** | Emit schema-compliant JSON events |
| **Intelligence API** | Ingest events, compute metrics, detect anomalies, expose endpoints |
| **Live Dashboard** | At least one real-time metric (+10 bonus) |

### API endpoints (Part B — 35 pts)

| Endpoint | Purpose |
|---|---|
| `POST /events/ingest` | Batch ingest up to 500 events, idempotent |
| `GET /stores/{id}/metrics` | Unique visitors, conversion, dwell, queue, abandonment |
| `GET /stores/{id}/funnel` | Entry → Zone → Billing → Purchase with drop-off % |
| `GET /stores/{id}/heatmap` | Zone frequency + dwell normalized 0–100 |
| `GET /stores/{id}/anomalies` | Queue spikes, conversion drops, dead zones |
| `GET /health` | Service status, last event per store, STALE_FEED warning |

### Production requirements (Part C — 20 pts)

- `docker compose up` with no manual steps  
- Structured logging (`trace_id`, `store_id`, `endpoint`, `latency_ms`, `event_count`, `status_code`)  
- Idempotent ingest, HTTP 503 on DB failure  
- Test coverage >70%, edge-case tests  
- README with ≤5 setup commands + pipeline instructions  

### Documentation (Part D — 15 pts)

- `DESIGN.md` (>250 words, AI-Assisted Decisions)  
- `CHOICES.md` (>250 words, 3 technical decisions)  
- Prompt blocks in test files  

### Acceptance gate (must pass to be scored)

| # | Gate | Status |
|---|---|---|
| 1 | `docker compose up` works | ❌ Dockerfile CMD placeholder |
| 2 | README explains detection pipeline | ❌ Pipeline not built |
| 3 | `POST /events/ingest` works | ✅ |
| 4 | `GET /stores/STORE_BLR_002/metrics` returns JSON | ❌ |
| 5 | `DESIGN.md` + `CHOICES.md` >250 words | ❌ Skeleton only |

### Dataset (not yet available)

- CCTV clips: 5 stores × 3 cameras × 20 min  
- `store_layout.json`, `pos_transactions.csv`, `sample_events.jsonl`  

---

## 3. Implemented Phases

| Phase | Scope | Status |
|---|---|---|
| **Phase 0** | Project scaffold, venv, requirements, Docker skeleton, folder structure | ✅ Complete |
| **Phase 1** | Pydantic event schemas, SQLite + SQLAlchemy, `events` + `pos_transactions` tables | ✅ Complete |
| **Phase 2** | FastAPI app, `GET /health`, `POST /events/ingest`, error handling, 8 API tests | ✅ Complete |
| **Phase 3A** | Session engine (`VisitorSession`, `build_sessions`), 9 session tests | ✅ Complete |
| **Phase 3B** | Metrics + POS correlation + acceptance gate #4 | ⏳ Next |
| **Phase 4** | Funnel, heatmap, anomalies, enhanced health, logging | ⏳ Pending |
| **Phase 5** | Detection pipeline (YOLO, ByteTrack, emit) | ⏳ Needs dataset |
| **Phase 6** | Dashboard, docs, Docker polish, coverage >70% | ⏳ Pending |

---

## 4. Current Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  FUTURE: pipeline/ (YOLO + ByteTrack + emit.py)                 │
│  CCTV clips → structured JSONL events                           │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  app/ingestion.py          POST /events/ingest                  │
│  app/models.py             Event validation (Pydantic v2)         │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  app/db.py                 SQLite (store_intelligence.db)       │
│  tables: events, pos_transactions                               │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  app/sessions.py           build_sessions() → VisitorSession[]  │
│  (in-memory, derived from events — no session table)            │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         metrics.py     funnel.py     anomalies.py   ← NOT YET BUILT
              │              │              │
              └──────────────┴──────────────┘
                             │
                             ▼
                    REST API responses
                             │
                             ▼
              dashboard/ (Streamlit)  ← NOT YET BUILT
```

### Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| API | FastAPI + Uvicorn |
| Validation | Pydantic v2 |
| Database | SQLite + SQLAlchemy 2.0 |
| CV (planned) | YOLOv8, ByteTrack, OpenCV |
| Dashboard (planned) | Streamlit |
| Containerization | Docker + docker-compose |

---

## 5. Existing Endpoints

| Method | Path | Status | Response |
|---|---|---|---|
| `GET` | `/health` | ✅ Implemented | `status`, `database_available`, `timestamp` |
| `POST` | `/events/ingest` | ✅ Implemented | `status`, `total_received`, `events_ingested`, `duplicates_skipped`, `rejected`, `errors` |
| `GET` | `/stores/{id}/metrics` | ❌ Not implemented | — |
| `GET` | `/stores/{id}/funnel` | ❌ Not implemented | — |
| `GET` | `/stores/{id}/heatmap` | ❌ Not implemented | — |
| `GET` | `/stores/{id}/anomalies` | ❌ Not implemented | — |

**Note:** Current `/health` is simplified vs PDF spec (missing per-store `last_event_at` and `STALE_FEED`). Full `HealthResponse` model exists in `app/models.py` but is not wired yet.

---

## 6. Existing Database Schema

**Engine:** SQLite (`./data/store_intelligence.db`)  
**ORM:** SQLAlchemy 2.0 — no Alembic migrations; tables created via `init_db()`

### Table: `events`

| Column | Type | Notes |
|---|---|---|
| `event_id` | VARCHAR(36) PK | UUID v4, idempotent ingest |
| `store_id` | VARCHAR(64) INDEX | e.g. `STORE_BLR_002` |
| `camera_id` | VARCHAR(64) | e.g. `CAM_ENTRY_01` |
| `visitor_id` | VARCHAR(64) INDEX | e.g. `VIS_c8a2f1` |
| `event_type` | VARCHAR(32) INDEX | One of 8 event types |
| `timestamp` | DATETIME(TZ) | UTC event time |
| `zone_id` | VARCHAR(64) NULL INDEX | Zone name or null |
| `dwell_ms` | INTEGER | Default 0 |
| `is_staff` | BOOLEAN | Staff exclusion flag |
| `confidence` | FLOAT | 0.0–1.0 |
| `metadata_json` | TEXT | JSON: queue_depth, sku_zone, session_seq |
| `ingested_at` | DATETIME(TZ) | Server ingest time |

**Indexes:** `(store_id, timestamp)`, `(store_id, event_type, timestamp)`, `(store_id, is_staff)`

### Table: `pos_transactions`

| Column | Type | Notes |
|---|---|---|
| `transaction_id` | VARCHAR(64) PK | e.g. `TXN_00441` |
| `store_id` | VARCHAR(64) INDEX | Store identifier |
| `timestamp` | DATETIME(TZ) | Purchase time |
| `basket_value_inr` | FLOAT | Amount in INR |
| `ingested_at` | DATETIME(TZ) | Server ingest time |

**Index:** `(store_id, timestamp)`

No `visitor_sessions` table — sessions are derived in memory by `app/sessions.py`.

---

## 7. Event Types

All 8 types defined in `EventType` enum (`app/models.py`) with Pydantic validation:

| Event | Trigger | Key rules |
|---|---|---|
| `ENTRY` | Cross entry inbound | `zone_id` null; starts session, new `visitor_id` |
| `EXIT` | Cross entry outbound | `zone_id` null; closes session |
| `REENTRY` | Same visitor after EXIT | `zone_id` null; new session, same `visitor_id` |
| `ZONE_ENTER` | Enter named zone | `zone_id` required |
| `ZONE_EXIT` | Leave named zone | `zone_id` required |
| `ZONE_DWELL` | 30+ seconds in zone | `zone_id` required, `dwell_ms ≥ 30000` |
| `BILLING_QUEUE_JOIN` | Enter billing while queue > 0 | `metadata.queue_depth > 0` |
| `BILLING_QUEUE_ABANDON` | Leave billing before POS txn | `zone_id` required |

---

## 8. Session Design Report Summary

### Definition

A **visitor session** = one contiguous visit from `ENTRY`/`REENTRY` until `EXIT`, keyed by `visitor_id`.

### Lifecycle

```
ENTRY / REENTRY  →  session opens
Zone/billing events  →  update session fields
EXIT  →  session closes
```

### Key rules

| Rule | Behavior |
|---|---|
| Re-entry | New session, same `visitor_id`; does not double-count unique visitors |
| Staff | Sessions retained with `is_staff=true`; excluded from customer metrics |
| Orphan EXIT | Ignored |
| Orphan REENTRY | Opens session |
| Unique visitors | `COUNT(DISTINCT visitor_id)` where non-staff |

### Session fields (implemented in Phase 3A)

`session_id`, `visitor_id`, `store_id`, `start_event_type`, `start_event_id`, `started_at`, `ended_at`, `is_open`, `is_staff`, `zones_visited`, `reached_billing`, `joined_queue`, `abandoned_queue`, `total_dwell_ms_by_zone`, `event_count`

### Helpers

- `build_sessions(events)` — main builder from `EventRecord` or `Event` list  
- `count_unique_visitors(sessions)` — REENTRY-safe unique count  
- `customer_sessions(sessions)` — filter staff for metrics  

### Funnel stages (for future `funnel.py`)

Entry → Zone Visit → Billing Queue → Purchase (session-based, staff excluded)

### POS correlation (for future `pos_correlation.py`)

Visitor in billing zone within **5 minutes before** transaction timestamp = converted.

---

## 9. Remaining Roadmap

### Priority 1 — Implement now (no dataset required)

| Task | Files | PDF requirement |
|---|---|---|
| `app/pos_correlation.py` | New logic | Conversion rate (North Star) |
| `app/metrics.py` + `GET /stores/{id}/metrics` | Router in `main.py` | Acceptance gate #4, Part B |
| POS seed/load script | `scripts/seed_from_sample.py` | Conversion testing |
| Fix Dockerfile CMD | `Dockerfile` | Acceptance gate #1 |
| Tests for metrics | `tests/test_metrics.py` | Part C |

### Priority 2 — Implement now (analytics API)

| Task | Files | PDF requirement |
|---|---|---|
| `GET /stores/{id}/funnel` | `app/funnel.py` | Part B (10 pts) |
| `GET /stores/{id}/heatmap` | `app/heatmap.py` | Part B |
| `GET /stores/{id}/anomalies` | `app/anomalies.py` | Part B (5 pts) |
| Enhanced `/health` | `app/health.py` | STALE_FEED, per-store timestamps |
| Structured logging middleware | `app/logging_config.py`, `main.py` | Part C (5 pts) |
| Edge-case tests | `tests/test_edge_cases.py` | Empty store, staff-only, zero purchases, re-entry |
| Documentation | `DESIGN.md`, `CHOICES.md` | Part D + gate #5 |

### Priority 3 — Wait for dataset (Part A — 30 pts)

| Task | Files |
|---|---|
| YOLO detect + ByteTrack | `pipeline/detect.py`, `tracker.py` |
| Entry/exit + zone mapping | `pipeline/entry_exit.py`, `zones.py` |
| Staff, queue, dwell, re-entry | `pipeline/staff.py`, `queue.py`, `dwell.py` |
| Event emission + run script | `pipeline/emit.py`, `run.sh` |
| Pipeline README instructions | `README.md` |

### Priority 4 — After API + pipeline (bonus + polish)

| Task | Files |
|---|---|
| Streamlit live dashboard | `dashboard/streamlit_app.py` |
| Load `sample_events.jsonl` | `scripts/seed_from_sample.py`, `tests/assertions.py` |
| Test coverage >70% | All `tests/` |
| AI prompt blocks in tests | Test file headers |
| Docker compose verification | End-to-end acceptance gate |

---

## Progress Scorecard

```
Acceptance Gates:     [██░░░] 2/5
Part A Detection:     [█░░░░] ~5%
Part B API:           [███░░] ~35%  (ingest + health done; metrics/funnel/heatmap/anomalies pending)
Part C Production:    [██░░░] ~25%  (basic errors; logging, Docker, coverage pending)
Part D Docs:          [█░░░░] ~5%
Part E Dashboard:     [░░░░░] 0%

Test count:           17 passing (8 API + 9 sessions)
Implemented modules:  models, db, main, health, ingestion, sessions
Scaffold only:        metrics, funnel, heatmap, anomalies, pos_correlation, logging, pipeline/*, dashboard/*
```

---

## Critical Path

```
Phase 3B: metrics + POS correlation  →  passes acceptance gate #4
Phase 4:  funnel + heatmap + anomalies + health + logging
Phase 5:  detection pipeline (when dataset arrives)
Phase 6:  dashboard + docs + Docker polish  →  passes all 5 gates
```

The session engine (Phase 3A) unblocks all Part B analytics. **Next recommended step: Phase 3B — `app/metrics.py` + `GET /stores/{id}/metrics`.**