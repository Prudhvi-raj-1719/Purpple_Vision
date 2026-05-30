# Purpple_Vision — Project State (Source of Truth)

**Repository:** [Prudhvi-raj-1719/Purpple_Vision](https://github.com/Prudhvi-raj-1719/Purpple_Vision)  
**Challenge:** Apex Retail 48-Hour Engineering Hiring Challenge  
**Last updated:** Phase 6A — PDF API alignment (May 2026)

> **Use this file** to resume work in a new chat with zero context loss.  
> Detailed narrative docs: `DESIGN.md`, `CHOICES.md`, `README.md`.  
> Example API payloads: `examples/*.json`.

---

## North Star

```
Conversion Rate = Visitors who completed a purchase ÷ Total unique visitors
```

---

## 1. Current Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  pipeline/  (STUBS — not implemented)                           │
│  detect.py, tracker.py, zones.py, entry_exit.py, dwell.py,     │
│  queue.py, staff.py, emit.py, pos_loader.py                     │
│  Planned: YOLOv8n + ByteTrack → JSONL events                    │
└────────────────────────────┬────────────────────────────────────┘
                             │ POST /events/ingest  OR  seed script
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  app/ingestion.py          Batch validate + idempotent persist    │
│  app/models.py             Pydantic v2 Event + API contracts    │
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

`main.py`, `models.py`, `db.py`, `ingestion.py`, `sessions.py`, `pos_correlation.py`, `metrics.py`, `funnel.py`, `heatmap.py`, `anomalies.py`, `health.py`, `logging_config.py`

---

## 2. Implemented Endpoints

All store endpoints accept optional `?date=YYYY-MM-DD` (UTC day; defaults to today UTC).

| Method | Path | Module | Status |
|--------|------|--------|--------|
| `GET` | `/health` | `app/health.py` | ✅ Full PDF health |
| `POST` | `/events/ingest` | `app/ingestion.py` | ✅ |
| `GET` | `/stores/{store_id}/metrics` | `app/metrics.py` | ✅ |
| `GET` | `/stores/{store_id}/funnel` | `app/funnel.py` | ✅ |
| `GET` | `/stores/{store_id}/heatmap` | `app/heatmap.py` | ✅ |
| `GET` | `/stores/{store_id}/anomalies` | `app/anomalies.py` | ✅ |

### Response summaries

**`GET /health`** → `HealthResponse`  
`status`, `database_available`, `timestamp`, `stores[]` (`store_id`, `last_event_at`, `stale`), `warnings[]` (e.g. `STALE_FEED: STORE_…`)

**`POST /events/ingest`** → `IngestStatusResponse`  
`status`, `total_received`, `events_ingested`, `duplicates_skipped`, `rejected`, `errors[]`

**`GET /stores/{id}/metrics`** → `StoreMetricsResponse`  
`store_id`, `date`, `unique_visitors`, `conversion_rate`, `average_dwell_time_ms`, `average_dwell_by_zone[]`, `current_queue_depth`, `queue_abandonment_rate`, `billing_reach_rate`, `total_sessions`

**`GET /stores/{id}/funnel`** → `StoreFunnelResponse`  
`store_id`, `date`, `stages[]` (`stage`, `count`, `drop_off_pct`), `overall_conversion_rate`

**`GET /stores/{id}/heatmap`** → `StoreHeatmapResponse`  
`store_id`, `date`, `data_confidence`, `zones[]` (`zone_id`, `visit_count`, `unique_visitors`, `total_dwell_time_ms`, `average_dwell_time_ms`, `normalized_score`)

**`GET /stores/{id}/anomalies`** → `StoreAnomaliesResponse`  
`store_id`, `date`, `anomalies[]` (`anomaly_type`, `severity`, `title`, `description`, `suggested_action`, `supporting_metrics`)

### PDF gaps on endpoints (remaining)

| PDF requirement | Gap |
|-----------------|-----|
| Anomalies: 7-day conversion baseline | Fixed same-day thresholds (needs multi-day data) |
| Anomalies: dead zone = no visits 30 min | Uses heatmap normalized score (needs sub-hour events) |
| Funnel: explicit Billing Queue stage | `reached_billing` only |
| POS ingest HTTP route | Seed/ORM only |

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
| `metadata_json` | TEXT | queue_depth, sku_zone, session_seq |
| `ingested_at` | DATETIME(TZ) | Feed lag for STALE_FEED |

**Indexes:** `(store_id, timestamp)`, `(store_id, event_type, timestamp)`, `(store_id, is_staff)`

### Table: `pos_transactions`

| Column | Type | Notes |
|--------|------|-------|
| `transaction_id` | VARCHAR(64) PK | |
| `store_id` | VARCHAR(64) INDEX | |
| `timestamp` | DATETIME(TZ) | |
| `basket_value_inr` | FLOAT | |
| `ingested_at` | DATETIME(TZ) | |

**Index:** `(store_id, timestamp)`

### Key DB helpers (`app/db.py`)

- `fetch_store_events(session, store_id, day=…)`
- `fetch_store_pos_transactions(session, store_id, day=…)`
- `fetch_store_feed_statuses(session)` → per-store max timestamp + max ingested_at
- `event_to_record()`, `pos_transaction_to_record()`

**No `visitor_sessions` table** — sessions derived in memory.

---

## 4. Session Engine Summary

**File:** `app/sessions.py`

**Definition:** One contiguous visit from `ENTRY` or `REENTRY` until `EXIT`, keyed by `visitor_id`.

```
ENTRY / REENTRY → session opens
Zone/billing events → update session fields
EXIT → session closes
```

| Rule | Behavior |
|------|----------|
| REENTRY | New session, same `visitor_id`; unique visitor count unchanged |
| Staff | Sessions built; excluded via `customer_sessions()` |
| Orphan EXIT | Ignored |
| Orphan REENTRY | Opens session |
| Billing zone | `BILLING` (case-insensitive) or queue events |

**Fields:** `session_id`, `visitor_id`, `store_id`, `start_event_type`, `start_event_id`, `started_at`, `ended_at`, `is_open`, `is_staff`, `zones_visited`, `reached_billing`, `joined_queue`, `abandoned_queue`, `billing_activity_at`, `total_dwell_ms_by_zone`, `event_count`

**Helpers:**
- `build_sessions(events)` — from `EventRecord` or `Event`, sorted by timestamp
- `count_unique_visitors(sessions)` — distinct non-staff `visitor_id`
- `customer_sessions(sessions)` — non-staff filter for analytics

---

## 5. Metrics Formulas

**File:** `app/metrics.py` — all use `customer_sessions()` unless noted.

| Metric | Formula |
|--------|---------|
| **unique_visitors** | `count_unique_visitors(sessions)` |
| **total_sessions** | `len(customer_sessions(sessions))` |
| **conversion_rate** | `len(converted_visitor_ids) / unique_visitors` (0 if no visitors) |
| **billing_reach_rate** | sessions with `reached_billing` / total customer sessions |
| **queue_abandonment_rate** | sessions with `abandoned_queue` / sessions with `joined_queue` (0 if none joined) |
| **average_dwell_time_ms** | mean of `sum(total_dwell_ms_by_zone.values())` per customer session |

**POS correlation:** `app/pos_correlation.py` — session converted if non-staff, `reached_billing`, and ∃ POS txn where `billing_activity_at ≤ txn.timestamp ≤ billing_activity_at + 5 minutes`.

**Note:** PDF wording uses billing within 5 min *before* transaction; implementation uses a forward window from billing activity.

---

## 6. Funnel Logic

**File:** `app/funnel.py` — **visitor-level** (not session-level counts for stages 2–4).

| Stage key | Meaning |
|-----------|---------|
| `unique_visitors` | `count_unique_visitors(sessions)` |
| `reached_any_zone` | Distinct visitors with any `zones_visited` in any session |
| `reached_billing` | Distinct visitors with `reached_billing` in any session |
| `converted_visitors` | `len(converted_visitor_ids(sessions, transactions))` |

**Drop-off:** For stage *i > 0*: `drop_off_pct = (count[i-1] - count[i]) / count[i-1] × 100` (null if prior count is 0).

**overall_conversion_rate:** `converted_visitors / unique_visitors`

REENTRY: one visitor can contribute to a later stage via a second session without inflating unique visitors.

---

## 7. Heatmap Logic

**File:** `app/heatmap.py`

Per zone (from customer sessions, sorted by `zone_id`):

| Field | Calculation |
|-------|-------------|
| **visit_count** | +1 per session that includes zone in `zones_visited` |
| **unique_visitors** | Distinct `visitor_id` visiting zone |
| **total_dwell_time_ms** | Sum of `session.total_dwell_ms_by_zone[zone_id]` |
| **average_dwell_time_ms** | `total_dwell / visit_count` |
| **engagement_score** | `visit_count + total_dwell_time_ms / 1000` |
| **normalized_score** | `(engagement / max_engagement) × 100` (0 if all zero) |

Requires ≥2 zones with activity for meaningful relative dead-zone detection in anomalies.

---

## 8. Anomaly Detection Logic

**File:** `app/anomalies.py` — staff excluded from queue join counts; conversion uses `compute_conversion_rate`.

| Type | Condition | Severity |
|------|-----------|----------|
| **QUEUE_SPIKE** | Non-staff `BILLING_QUEUE_JOIN` count/day ≥ 10 | WARNING |
| **QUEUE_SPIKE** | Count ≥ 20 | CRITICAL |
| **CONVERSION_DROP** | `conversion_rate < 0.20` when ≥1 visitor reached billing | WARNING |
| **CONVERSION_DROP** | `conversion_rate < 0.10` | CRITICAL |
| **DEAD_ZONE** | Heatmap `normalized_score < 20` (≥2 zones) | WARNING |
| **DEAD_ZONE** | `normalized_score < 10` | CRITICAL |

Empty store → `anomalies: []`. Constants documented in code comments at top of `anomalies.py`.

---

## 9. Logging Implementation

**File:** `app/logging_config.py` — wired in `app/main.py` via `RequestLoggingMiddleware`.

| Field | Source |
|-------|--------|
| `trace_id` | UUID4 per request; header `X-Trace-Id` |
| `endpoint` | Request path |
| `latency_ms` | Wall-clock duration |
| `status_code` | HTTP response status |
| `store_id` | Parsed from `/stores/{store_id}/…` when present |

**Format:** JSON lines when `LOG_FORMAT=json` (default in compose).  
**Ingest:** `event_count` = `total_received` on `POST /events/ingest` (via `request.state` + middleware).

**Errors:** `ErrorResponse` includes `trace_id` from middleware on 422/503/500.

---

## 10. Seed Script Behavior

**File:** `scripts/seed_from_sample.py`

```powershell
python scripts/seed_from_sample.py
python scripts/seed_from_sample.py --events ./data/sample_events.jsonl --pos ./data/pos_transactions.csv
```

- Paths from `SAMPLE_EVENTS_PATH` / `POS_TRANSACTIONS_PATH` or defaults under `./data/`
- Validates with `Event` / `PosTransaction` (Pydantic)
- Skips missing files with message (non-fatal)
- **Idempotent:** skips existing `event_id` / `transaction_id`
- Prints JSON summary: `inserted`, `duplicates_skipped`, `rejected`
- **Test:** `tests/test_seed.py`

---

## 11. Docker Status

| Item | Status |
|------|--------|
| `Dockerfile` CMD | ✅ `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| `docker compose up --build` | ✅ Starts `api` service (no profile needed) |
| `.env` required | ❌ No — inline defaults in compose |
| SQLite volume | ✅ `./data:/app/data` |
| Logs volume | ✅ `./logs:/app/logs` |
| Healthcheck | ✅ Python probe to `GET /health` |
| `.dockerignore` | ✅ Excludes `.venv`, `data/`, `.env`, etc. |
| `data/.gitkeep`, `logs/.gitkeep` | ✅ |

**Verify:**
```powershell
docker compose up --build
curl http://localhost:8000/health
curl "http://localhost:8000/stores/STORE_BLR_002/metrics?date=2026-03-03"
```

First build is slow (~PyTorch via ultralytics in `requirements.txt`).

---

## 12. Test Coverage Summary

**Total tests:** 115 passing  
**Coverage:** ~95% on `app/` (`pytest --cov=app`)

| File | Tests | Focus |
|------|-------|-------|
| `test_sessions.py` | 9 | Session lifecycle |
| `test_ingestion.py` | 6 | Ingest idempotency, partial success |
| `test_metrics.py` | 17 | Metrics + API |
| `test_funnel.py` | 18 | Funnel + API |
| `test_heatmap.py` | 18 | Heatmap + API |
| `test_anomalies.py` | 18 | Anomalies + API |
| `test_health.py` | 5 | Health + STALE_FEED |
| `test_edge_cases.py` | 15 | Empty store, staff, REENTRY, batch limits, stale feed |
| `test_seed.py` | 1 | Seed idempotency |

**Fixtures:** `tests/conftest.py` — fresh SQLite per test (`test_api.db`).

**Gaps:** No `test_pipeline.py`; `tests/assertions.py` stub.

---

## 13. Acceptance Gate Status

| # | Gate | Status |
|---|------|--------|
| 1 | `docker compose up` starts API | ✅ |
| 2 | README explains detection pipeline | ⚠️ PARTIAL — documented as not built; ingest/seed path documented |
| 3 | `POST /events/ingest` works | ✅ |
| 4 | `GET /stores/STORE_BLR_002/metrics` returns JSON | ✅ |
| 5 | `DESIGN.md` + `CHOICES.md` >250 words | ✅ |

**Estimated: 4/5 full pass, 1 partial (pipeline).**

---

## 14. Remaining Gaps (Latest Audit)

### Must-have for full PDF score

| Gap | Part |
|-----|------|
| Detection pipeline (`pipeline/*.py`) | A (30 pts) |
| Anomalies: 7-day baseline, 30-min dead zones | B |
| Live dashboard | E (+10 bonus) |

### Backend fixable without CCTV

| Gap | Files |
|-----|-------|
| `POST /pos/ingest` or document seed-only | new route or README |
| POS window semantics vs PDF | `app/pos_correlation.py` |
| `tests/assertions.py` challenge examples | `tests/assertions.py` |
| `scripts/run_pipeline.sh` | `scripts/` |

### Scaffold only

`pipeline/*`, `dashboard/streamlit_app.py`, `tests/assertions.py` (empty)

---

## 15. Recommended Next Steps

### Priority 1 — Unblock Gate #2 & Part A (30 pts)

1. Implement minimal pipeline MVP: `detect.py` → `tracker.py` → `emit.py` → `scripts/run_pipeline.sh`
2. Update README with clip → JSONL → ingest workflow
3. Add `tests/test_pipeline.py` (schema compliance on emitted events)

### Priority 2 — Part D polish

4. Add `# PROMPT:` / `# CHANGES MADE:` headers to all `tests/test_*.py` files

### Priority 3 — PDF API fidelity (no video)

5. Add `average_dwell_by_zone` + `current_queue_depth` to metrics response
6. Add heatmap `data_confidence` when customer sessions < 20
7. Align anomalies with PDF (`suggested_action`, rolling baseline when multi-day data exists)

### Priority 4 — Bonus & polish

8. Streamlit dashboard wired to live API
9. Slim Docker image (optional API-only requirements split from ultralytics)

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
| 6 | Detection pipeline | ⏳ Not started |
| 7 | Dashboard | ⏳ Not started |

---

## Progress Scorecard

```
Acceptance Gates:     [████░] 4/5 (gate #2 partial)
Part A Detection:     [█░░░░] ~5%
Part B API:           [█████] ~90%
Part C Production:    [█████] ~90%
Part D Docs:          [█████] ~90%
Part E Dashboard:     [░░░░░] 0%

Tests:                115 passing
app/ coverage:        ~95%
```

---

## Quick Commands

```powershell
# Local API
uvicorn app.main:app --reload --port 8000

# Tests
pytest --cov=app

# Seed data
python scripts/seed_from_sample.py

# Docker
docker compose up --build
```

---

## Event Types (reference)

Defined in `app/models.py` → `EventType`:  
ENTRY, EXIT, REENTRY, ZONE_ENTER, ZONE_EXIT, ZONE_DWELL (≥30s), BILLING_QUEUE_JOIN (queue_depth>0), BILLING_QUEUE_ABANDON

Validation retains low-confidence events; does not drop on confidence score.
