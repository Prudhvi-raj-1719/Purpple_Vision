# Purpple_Vision — Project State (Source of Truth)

**Repository:** [Prudhvi-raj-1719/Purpple_Vision](https://github.com/Prudhvi-raj-1719/Purpple_Vision)  
**Challenge:** Apex Retail 48-Hour Engineering Hiring Challenge  
**Last updated:** Phase 6B — Final API completeness (May 2026)

> **Authoritative snapshot** for resuming work with zero context loss.  
> Narrative docs: `DESIGN.md`, `CHOICES.md`, `README.md`.  
> Phase reports: `PHASE_6A_REPORT.md`, `PHASE_6B_REPORT.md`.  
> Example payloads: `examples/*.json`.

---

## North Star

```
Conversion Rate = Visitors who completed a purchase ÷ Total unique visitors
```

A visitor is **converted** when they reached billing and billing activity occurred within **5 minutes before** a POS transaction on the same store (`app/pos_correlation.py`).

---

## 1. Current Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  pipeline/  (STUBS — not implemented)                           │
│  detect.py, tracker.py, zones.py, entry_exit.py, dwell.py,     │
│  queue.py, staff.py, emit.py, pos_loader.py                     │
│  Planned: YOLOv8n + ByteTrack → JSONL events                    │
└────────────────────────────┬────────────────────────────────────┘
                             │ POST /events/ingest
                             │ POST /pos/ingest
                             │ OR  scripts/seed_from_sample.py
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  app/ingestion.py          Event batch validate + persist       │
│  app/pos_ingestion.py      POS batch validate + persist         │
│  app/models.py             Pydantic v2 schemas + API contracts  │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  app/db.py                 SQLite (store_intelligence.db)       │
│  tables: events, pos_transactions                               │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  app/sessions.py           build_sessions() → VisitorSession[]  │
│  (in-memory — no visitor_sessions table)                        │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
  app/metrics.py      app/funnel.py        app/heatmap.py
  app/pos_correlation   app/anomalies.py
        └────────────────────┴────────────────────┘
                             ▼
  app/health.py  +  app/logging_config.py (middleware)
                             ▼
                    FastAPI JSON responses
                             ▼
  dashboard/streamlit_app.py  (STUB — optional compose profile)
```

### Tech stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11 |
| API | FastAPI + Uvicorn |
| Validation | Pydantic v2 |
| Database | SQLite + SQLAlchemy 2.0 (sync) |
| CV (planned) | YOLOv8n, ByteTrack, OpenCV (deps pinned) |
| Dashboard (planned) | Streamlit |
| Containerization | Docker + docker-compose |

### Implemented `app/` modules

`main.py`, `models.py`, `db.py`, `ingestion.py`, `pos_ingestion.py`, `sessions.py`, `pos_correlation.py`, `metrics.py`, `funnel.py`, `heatmap.py`, `anomalies.py`, `health.py`, `logging_config.py`

---

## 2. All Endpoints

All store analytics endpoints accept optional `?date=YYYY-MM-DD` (UTC calendar day; defaults to today UTC).

| Method | Path | Module | Status |
|--------|------|--------|--------|
| `GET` | `/health` | `app/health.py` | ✅ |
| `POST` | `/events/ingest` | `app/ingestion.py` | ✅ |
| `POST` | `/pos/ingest` | `app/pos_ingestion.py` | ✅ |
| `GET` | `/stores/{store_id}/metrics` | `app/metrics.py` | ✅ |
| `GET` | `/stores/{store_id}/funnel` | `app/funnel.py` | ✅ |
| `GET` | `/stores/{store_id}/heatmap` | `app/heatmap.py` | ✅ |
| `GET` | `/stores/{store_id}/anomalies` | `app/anomalies.py` | ✅ |

### Ingest

**`POST /events/ingest`** → `IngestStatusResponse`  
`status`, `total_received`, `events_ingested`, `duplicates_skipped`, `rejected`, `errors[]`  
Batch 1–500; idempotent on `event_id`; partial success per event.

**`POST /pos/ingest`** → `PosIngestStatusResponse`  
`status`, `total_received`, `transactions_ingested`, `duplicates_skipped`, `rejected`, `errors[]`  
Batch 1–500; idempotent on `transaction_id`; partial success per row.

### Store analytics

**`GET /health`** → `HealthResponse`  
`status`, `database_available`, `timestamp`, `stores[]` (`store_id`, `last_event_at`, `stale`), `warnings[]` (e.g. `STALE_FEED: STORE_…`)

**`GET /stores/{id}/metrics`** → `StoreMetricsResponse`  
`store_id`, `date`, `unique_visitors`, `conversion_rate`, `average_dwell_time_ms`, `average_dwell_by_zone[]` (`zone_id`, `average_dwell_ms`), `current_queue_depth`, `queue_abandonment_rate`, `billing_reach_rate`, `total_sessions`

**`GET /stores/{id}/funnel`** → `StoreFunnelResponse`  
`store_id`, `date`, `stages[]` (`stage`, `count`, `drop_off_pct`), `overall_conversion_rate`  
Stages: `unique_visitors` → `reached_any_zone` → `billing_queue` → `converted_visitors`

**`GET /stores/{id}/heatmap`** → `StoreHeatmapResponse`  
`store_id`, `date`, `data_confidence`, `zones[]` (`zone_id`, `visit_count`, `unique_visitors`, `total_dwell_time_ms`, `average_dwell_time_ms`, `normalized_score`)

**`GET /stores/{id}/anomalies`** → `StoreAnomaliesResponse`  
`store_id`, `date`, `anomalies[]` (`anomaly_type`, `severity`, `title`, `description`, `suggested_action`, `detected_at`, `supporting_metrics`)  
Severity values: `INFO`, `WARN`, `CRITICAL` (alerts currently emit `WARN` or `CRITICAL`).

---

## 3. Database Schema

**Engine:** SQLite at `./data/store_intelligence.db` (override via `DATABASE_URL`)  
**Init:** `init_db()` on app startup (no Alembic)

### Table: `events`

| Column | Type | Notes |
|--------|------|-------|
| `event_id` | VARCHAR(36) PK | UUID v4; idempotent ingest |
| `store_id` | VARCHAR(64) INDEX | e.g. `STORE_BLR_002` |
| `camera_id` | VARCHAR(64) | |
| `visitor_id` | VARCHAR(64) INDEX | |
| `event_type` | VARCHAR(32) INDEX | 8 event types |
| `timestamp` | DATETIME(TZ) | UTC business time |
| `zone_id` | VARCHAR(64) NULL INDEX | |
| `dwell_ms` | INTEGER | Default 0 |
| `is_staff` | BOOLEAN | |
| `confidence` | FLOAT | |
| `metadata_json` | TEXT | `queue_depth`, `sku_zone`, `session_seq` |
| `ingested_at` | DATETIME(TZ) | Feed lag for `STALE_FEED` |

**Indexes:** `(store_id, timestamp)`, `(store_id, event_type, timestamp)`, `(store_id, is_staff)`

### Table: `pos_transactions`

| Column | Type | Notes |
|--------|------|-------|
| `transaction_id` | VARCHAR(64) PK | e.g. `TXN_00441` |
| `store_id` | VARCHAR(64) INDEX | |
| `timestamp` | DATETIME(TZ) | |
| `basket_value_inr` | FLOAT | |
| `ingested_at` | DATETIME(TZ) | |

**Index:** `(store_id, timestamp)`

### Key DB helpers (`app/db.py`)

- `fetch_store_events(session, store_id, day=…)`
- `fetch_store_pos_transactions(session, store_id, day=…)`
- `fetch_store_feed_statuses(session)` → per-store max event timestamp + max `ingested_at`
- `event_to_record()`, `pos_transaction_to_record()`

**No `visitor_sessions` table** — sessions derived in memory at query time.

---

## 4. Session Engine

**File:** `app/sessions.py`

**Definition:** One contiguous visit from `ENTRY` or `REENTRY` until `EXIT`, keyed by `visitor_id`.

```
ENTRY / REENTRY → session opens
Zone / billing / queue events → update session fields
EXIT → session closes
```

| Rule | Behavior |
|------|----------|
| REENTRY | New session, same `visitor_id`; unique visitor count unchanged |
| Staff | Sessions built; excluded via `customer_sessions()` |
| Orphan EXIT | Ignored |
| Orphan REENTRY | Opens session |
| Billing zone | `BILLING` (case-insensitive) or queue events set `reached_billing` |
| Queue join | `BILLING_QUEUE_JOIN` sets `joined_queue` |
| Queue abandon | `BILLING_QUEUE_ABANDON` sets `abandoned_queue` |

**Fields:** `session_id`, `visitor_id`, `store_id`, `start_event_type`, `start_event_id`, `started_at`, `ended_at`, `is_open`, `is_staff`, `zones_visited`, `reached_billing`, `joined_queue`, `abandoned_queue`, `billing_activity_at`, `total_dwell_ms_by_zone`, `event_count`

**Helpers:**

- `build_sessions(events)` — from `EventRecord` or `Event`, sorted by timestamp
- `count_unique_visitors(sessions)` — distinct non-staff `visitor_id`
- `customer_sessions(sessions)` — non-staff filter for analytics

---

## 5. Metrics Formulas

**File:** `app/metrics.py` — customer metrics use `customer_sessions()` unless noted.

| Metric | Formula |
|--------|---------|
| **unique_visitors** | `count_unique_visitors(sessions)` |
| **total_sessions** | `len(customer_sessions(sessions))` |
| **conversion_rate** | `len(converted_visitor_ids) / unique_visitors` (0 if no visitors) |
| **billing_reach_rate** | sessions with `reached_billing` ÷ total customer sessions |
| **queue_abandonment_rate** | sessions with `abandoned_queue` ÷ sessions with `joined_queue` (0 if none joined) |
| **average_dwell_time_ms** | mean of `sum(total_dwell_ms_by_zone.values())` per customer session |
| **average_dwell_by_zone** | per zone: mean dwell per session visit (from `total_dwell_ms_by_zone`) |
| **current_queue_depth** | `metadata.queue_depth` from latest non-staff `BILLING_QUEUE_JOIN` by timestamp (0 if none) |

**POS correlation:** `app/pos_correlation.py` — converted session iff non-staff, `reached_billing`, and ∃ POS txn on same store where:

```
transaction.timestamp − 5 minutes ≤ billing_activity_at ≤ transaction.timestamp
```

---

## 6. Funnel Stages

**File:** `app/funnel.py` — **visitor-level** counts (PDF: Entry → Zone Visit → Billing Queue → Purchase).

| Stage key | PDF meaning | Implementation |
|-----------|-------------|----------------|
| `unique_visitors` | Entry | `count_unique_visitors(sessions)` |
| `reached_any_zone` | Zone visit | Distinct visitors with any `zones_visited` in any session |
| `billing_queue` | Billing queue | Distinct visitors with `joined_queue` in any session (`BILLING_QUEUE_JOIN`) |
| `converted_visitors` | Purchase | `len(converted_visitor_ids(sessions, transactions))` |

**Note:** Zone-only `ZONE_ENTER` to `BILLING` without a queue join counts toward `reached_billing` on the session but **not** toward the `billing_queue` funnel stage.

**Drop-off:** For stage *i > 0*: `drop_off_pct = (count[i−1] − count[i]) / count[i−1] × 100` (`null` if prior count is 0).

**overall_conversion_rate:** `converted_visitors / unique_visitors`

**REENTRY:** One visitor can advance via a later session without inflating `unique_visitors`.

**Helper:** `visitors_reached_billing()` retained for anomaly conversion-drop context (any billing touch).

---

## 7. Heatmap Logic

**File:** `app/heatmap.py`

Per zone (customer sessions only, zones sorted by `zone_id`):

| Field | Calculation |
|-------|-------------|
| **visit_count** | +1 per session that includes zone in `zones_visited` |
| **unique_visitors** | Distinct `visitor_id` visiting zone |
| **total_dwell_time_ms** | Sum of `session.total_dwell_ms_by_zone[zone_id]` |
| **average_dwell_time_ms** | `total_dwell / visit_count` |
| **engagement_score** | `visit_count + total_dwell_time_ms / 1000` |
| **normalized_score** | `(engagement / max_engagement) × 100` (0 if all zero) |

**data_confidence:** `true` when ≥ 20 customer sessions on the requested UTC day; `false` otherwise (`MIN_SESSIONS_FOR_DATA_CONFIDENCE = 20`).

Dead-zone anomalies require ≥ 2 zones with activity for relative comparison.

---

## 8. Anomaly Logic

**File:** `app/anomalies.py` — staff excluded from queue-join counts; conversion uses `compute_conversion_rate`.

| Type | Condition | Severity |
|------|-----------|----------|
| **QUEUE_SPIKE** | Non-staff `BILLING_QUEUE_JOIN` count/day ≥ 10 | `WARN` |
| **QUEUE_SPIKE** | Count ≥ 20 | `CRITICAL` |
| **CONVERSION_DROP** | `conversion_rate < 0.20` when ≥1 visitor reached billing | `WARN` |
| **CONVERSION_DROP** | `conversion_rate < 0.10` | `CRITICAL` |
| **DEAD_ZONE** | Heatmap `normalized_score < 20` (≥2 zones) | `WARN` |
| **DEAD_ZONE** | `normalized_score < 10` | `CRITICAL` |

Each anomaly includes `suggested_action` (operational text) and `detected_at` (UTC, request time by default).

**Severity enum:** `INFO`, `WARN`, `CRITICAL` — `INFO` is defined but not emitted by current detectors.

Empty store → `anomalies: []`. Threshold constants documented at top of `app/anomalies.py`.

### PDF gaps (anomalies only)

| PDF requirement | Status |
|-----------------|--------|
| Conversion drop vs **7-day rolling baseline** | Not implemented — same-day fixed thresholds |
| Dead zone = **no visits in 30 minutes** | Not implemented — daily heatmap relative score |

---

## 9. POS Ingestion

**HTTP:** `POST /pos/ingest` in `app/pos_ingestion.py`  
**Seed:** `scripts/seed_from_sample.py` loads `pos_transactions.csv` when present  

| Behavior | Detail |
|----------|--------|
| Batch size | 1–500 transactions |
| Validation | Pydantic `PosTransaction` per row |
| Idempotency | Skip existing `transaction_id` |
| Partial success | Invalid rows in `errors[]`; valid rows still persist |
| Logging | Sets `request.state.event_count` = `total_received` (same middleware field as event ingest) |

**Schema:** `store_id`, `transaction_id`, `timestamp` (UTC), `basket_value_inr` ≥ 0

**Example:** `examples/pos_ingest_endpoint.json`

---

## 10. Structured Logging

**File:** `app/logging_config.py` — `RequestLoggingMiddleware` in `app/main.py`

| Field | Source |
|-------|--------|
| `trace_id` | UUID4 per request; response header `X-Trace-Id` |
| `endpoint` | Request path |
| `latency_ms` | Wall-clock duration |
| `status_code` | HTTP response status |
| `store_id` | Parsed from `/stores/{store_id}/…` when present |
| `event_count` | `total_received` on `POST /events/ingest` and `POST /pos/ingest` |

**Format:** JSON lines when `LOG_FORMAT=json` (default in compose).

**Errors:** `ErrorResponse` includes `trace_id` on 422 / 503 / 500.

---

## 11. Seed Script

**File:** `scripts/seed_from_sample.py`

```powershell
python scripts/seed_from_sample.py
python scripts/seed_from_sample.py --events ./data/sample_events.jsonl --pos ./data/pos_transactions.csv
```

- Paths from `SAMPLE_EVENTS_PATH` / `POS_TRANSACTIONS_PATH` or defaults under `./data/`
- Validates with `Event` / `PosTransaction`
- Skips missing files (non-fatal)
- **Idempotent** on `event_id` / `transaction_id`
- **Test:** `tests/test_seed.py`

---

## 12. Docker Status

| Item | Status |
|------|--------|
| `Dockerfile` CMD | ✅ `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| `docker compose up --build` | ✅ Starts `api` service (no profile needed) |
| `.env` required | ❌ No — inline defaults in compose |
| SQLite volume | ✅ `./data:/app/data` |
| Logs volume | ✅ `./logs:/app/logs` |
| Healthcheck | ✅ Probe `GET /health` |
| Dashboard profile | Optional `docker compose --profile dashboard` (Streamlit stub) |

**Verify:**

```powershell
docker compose up --build
curl http://localhost:8000/health
curl "http://localhost:8000/stores/STORE_BLR_002/metrics?date=2026-03-03"
```

First build is slow (~PyTorch via `ultralytics` in `requirements.txt`).

---

## 13. Test Summary

**Total:** 125 passing (`pytest tests/`)  
**Fixtures:** `tests/conftest.py` — fresh SQLite per test (`test_api.db`)

| File | Tests | Focus |
|------|-------|-------|
| `test_sessions.py` | 9 | Session lifecycle, REENTRY, queue |
| `test_ingestion.py` | 6 | Event ingest idempotency, partial success |
| `test_pos_ingestion.py` | 6 | POS ingest idempotency, partial success |
| `test_metrics.py` | 23 | Metrics, POS window, PDF fields, API |
| `test_funnel.py` | 20 | Funnel stages, `billing_queue`, API |
| `test_heatmap.py` | 20 | Heatmap, `data_confidence`, API |
| `test_anomalies.py` | 20 | Anomalies, `detected_at`, `WARN`, API |
| `test_health.py` | 5 | Health, `STALE_FEED` |
| `test_edge_cases.py` | 16 | Empty store, staff, REENTRY, batch 500, logging |
| `test_seed.py` | 1 | Seed idempotency |

**Gaps:** No `test_pipeline.py`; `tests/assertions.py` stub; all `tests/test_*.py` include `# PROMPT:` / `# CHANGES MADE:` headers.

---

## 14. Coverage Summary

```powershell
pytest --cov=app --cov-report=term-missing
```

| Metric | Value |
|--------|-------|
| **Statements (`app/`)** | ~1,059 |
| **Coverage** | **~95%** |
| **Last verified** | Phase 6B |

Modules at or near full coverage: `metrics`, `funnel`, `heatmap`, `anomalies`, `sessions`, `pos_correlation`, `pos_ingestion`. Lower coverage typically in `main.py` exception paths and `db.py` edge helpers.

`pipeline/` and `dashboard/` are stubs (no executable logic to cover).

---

## 15. Acceptance Gate Status

| # | Gate | Status |
|---|------|--------|
| 1 | `docker compose up` starts API | ✅ PASS |
| 2 | README explains detection pipeline | ⚠️ PARTIAL — pipeline documented as not built; ingest/seed/POS paths documented |
| 3 | `POST /events/ingest` works | ✅ PASS |
| 4 | `GET /stores/STORE_BLR_002/metrics` returns JSON | ✅ PASS |
| 5 | `DESIGN.md` + `CHOICES.md` >250 words | ✅ PASS |

**Score: 4/5 full pass, 1 partial (runnable pipeline / clip workflow).**

---

## 16. Remaining CCTV-Dependent Gaps

These cannot be completed without CCTV clips, live video processing, or challenge dataset files under `./data/`:

| Gap | Why blocked |
|-----|-------------|
| **Part A — full detection pipeline** | YOLO, ByteTrack, zones, entry/exit, dwell, queue, staff, emit |
| **`scripts/run_pipeline.sh` functional** | Clip → JSONL → ingest |
| **`tests/test_pipeline.py`** | Needs pipeline-emitted events |
| **`tests/assertions.py`** | Challenge ground-truth examples from processed clips |
| **Anomaly: 7-day conversion baseline** | Needs ≥7 days of per-store history in DB |
| **Anomaly: dead zone 30-min inactivity** | Needs sub-hour zone activity from stream |
| **Cross-camera deduplication** | Multi-camera CV + layout |
| **Group entry splitting** | Multi-person detection |
| **True live queue depth** | Continuous queue state from video (API uses last join `queue_depth`) |
| **Streamlit dashboard (Part E +10)** | Bonus; stub only |

### Implemented without CCTV (Phase 6A + 6B)

Event ingest, POS ingest, metrics/funnel/heatmap/anomalies/health APIs, PDF field alignment, POS correlation window, funnel `billing_queue`, `detected_at`, `WARN` severity, structured logging, Docker, seed script, docs, 125 tests.

---

## 17. Submission Readiness Estimate

| Lens | Estimate | Notes |
|------|----------|-------|
| **Acceptance gates** | **90%** | 4.5 / 5 — gate #2 partial |
| **Part B — Intelligence API** | **~95%** | All 7 HTTP routes; minor anomaly baseline gaps |
| **Part C — Production** | **~90%** | Docker, logging, tests, seed; no functional pipeline script |
| **Part D — Documentation** | **~93%** | DESIGN/CHOICES/PROMPT blocks; `assertions.py` empty |
| **Part A — Detection** | **~5%** | Scaffold only — **largest score risk (~30 pts)** |
| **Part E — Dashboard** | **0%** | Bonus not started |
| **Weighted base score** | **~68–72 / 100** | Pre-bonus |
| **Overall submission readiness** | **~78%** | Strong API + ops path; weak end-to-end CCTV story |

**Recommended before submit:** Minimal pipeline MVP or README that clearly positions ingest/seed as the evaluator data path; include sample data under `./data/` when allowed.

---

## Phase Completion Tracker

| Phase | Scope | Status |
|-------|-------|--------|
| 0 | Scaffold, venv, Docker structure | ✅ |
| 1 | Schemas, SQLite, tables | ✅ |
| 2 | Ingest, basic health, API tests | ✅ |
| 3A | Session engine | ✅ |
| 3B | Metrics + POS correlation | ✅ |
| 4A | Funnel API | ✅ |
| 4B | Heatmap API | ✅ |
| 4C | Anomalies API | ✅ |
| 4D | Health, logging, edge tests, seed | ✅ |
| 4E | Docker acceptance gate fix | ✅ |
| 5 | Documentation + audit | ✅ |
| 6A | PDF API field alignment (no video) | ✅ |
| 6B | Final API completeness (no video) | ✅ |
| 7 | Detection pipeline | ⏳ Not started |
| 8 | Dashboard | ⏳ Not started |

---

## Progress Scorecard

```
Acceptance Gates:     [████░] 4/5 (gate #2 partial)
Part A Detection:     [█░░░░] ~5%
Part B API:           [█████] ~95%
Part C Production:    [█████] ~90%
Part D Docs:          [█████] ~93%
Part E Dashboard:     [░░░░░] 0%

Tests:                125 passing
app/ coverage:        ~95%
Submission readiness: ~78%
```

---

## Quick Commands

```powershell
# Local API
uvicorn app.main:app --reload --port 8000

# Tests + coverage
pytest --cov=app

# Seed events + POS
python scripts/seed_from_sample.py

# Docker
docker compose up --build
```

---

## Event Types (reference)

Defined in `app/models.py` → `EventType`:

`ENTRY`, `EXIT`, `REENTRY`, `ZONE_ENTER`, `ZONE_EXIT`, `ZONE_DWELL` (≥30s), `BILLING_QUEUE_JOIN` (`metadata.queue_depth` > 0), `BILLING_QUEUE_ABANDON`

Validation retains low-confidence events; confidence is stored, not used to drop events.
