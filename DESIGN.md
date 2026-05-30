# Design Document — Store Intelligence (Purpple_Vision)

## 1. System Overview

Purpple_Vision is an end-to-end **Store Intelligence System** for Apex Retail. The intended production flow is:

**CCTV clips → Detection pipeline → JSON event stream → Intelligence API → (optional) live dashboard**

The **North Star metric** is offline conversion rate:

```
Conversion Rate = Visitors who completed a purchase ÷ Total unique visitors
```

At submission time, the **Intelligence API** is fully implemented: it ingests schema-compliant behavioural events, persists them in SQLite, derives in-memory visitor sessions, correlates POS transactions, and exposes metrics, funnel, heatmap, anomaly, and health endpoints. The **computer-vision pipeline** (`pipeline/`) and **Streamlit dashboard** are scaffolded but not yet implemented; events can be loaded via `POST /events/ingest` or `scripts/seed_from_sample.py`.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  pipeline/  (planned)                                                   │
│  detect.py → tracker.py → zones.py → entry_exit.py → emit.py           │
│  Output: sample_events.jsonl (schema in app/models.py)                  │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ HTTP POST /events/ingest
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  app/ingestion.py          Batch validate + idempotent persist          │
│  app/models.py             Pydantic v2 contracts                        │
└───────────────────────────────┬─────────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  app/db.py                 SQLite (events, pos_transactions)          │
└───────────────────────────────┬─────────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  app/sessions.py           build_sessions() → VisitorSession[]          │
│  (in-memory; not a DB table)                                            │
└───────────────────────────────┬─────────────────────────────────────────┘
                                ▼
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
  app/metrics.py          app/funnel.py           app/heatmap.py
  app/pos_correlation.py  app/anomalies.py        app/health.py
        └───────────────────────┴───────────────────────┘
                                ▼
                    FastAPI JSON responses
```

**Cross-cutting:** `app/logging_config.py` (structured request logs), `app/main.py` (middleware, global 503 handlers).

---

## 3. Component Breakdown

### 3.1 Detection pipeline (`pipeline/`) — planned

Modules exist as stubs: `detect.py`, `tracker.py`, `zones.py`, `entry_exit.py`, `dwell.py`, `queue.py`, `staff.py`, `emit.py`, `pos_loader.py`. The planned stack is YOLOv8 + ByteTrack, zone polygons from `store_layout.json`, and JSONL emission matching `Event` in `app/models.py`. Until this is built, validation and analytics are tested with synthetic events and optional dataset files under `./data/`.

### 3.2 Intelligence API (`app/`)

| Module | Responsibility |
|--------|----------------|
| `main.py` | FastAPI app, lifespan `init_db()`, logging middleware, exception handlers |
| `ingestion.py` | `POST /events/ingest` — up to 500 events, partial success, idempotent by `event_id` |
| `sessions.py` | Session lifecycle from ENTRY/REENTRY through EXIT |
| `pos_correlation.py` | Match billing activity to POS within 5-minute window |
| `metrics.py` | `GET /stores/{id}/metrics` |
| `funnel.py` | `GET /stores/{id}/funnel` |
| `heatmap.py` | `GET /stores/{id}/heatmap` |
| `anomalies.py` | `GET /stores/{id}/anomalies` |
| `health.py` | `GET /health` with per-store feeds and STALE_FEED |

All store analytics accept optional `?date=YYYY-MM-DD` (UTC day, default today).

### 3.3 Data layer (`app/db.py`)

- **Engine:** SQLite file at `./data/store_intelligence.db` (configurable via `DATABASE_URL`).
- **Tables:** `events` (PK `event_id`), `pos_transactions` (PK `transaction_id`).
- **No Alembic:** tables created on startup via `init_db()`.
- **Sessions:** derived at query time, not persisted.

### 3.4 Dashboard (`dashboard/`) — planned

`streamlit_app.py` is a stub. Docker Compose exposes an optional `dashboard` profile that depends on a healthy API container.

---

## 4. Event schema

Events are defined in `app/models.py` as Pydantic `Event` models. Required fields: `event_id` (UUID v4), `store_id`, `camera_id`, `visitor_id`, `event_type`, `timestamp` (UTC), `zone_id`, `dwell_ms`, `is_staff`, `confidence`, `metadata`.

**Event types:** ENTRY, EXIT, REENTRY, ZONE_ENTER, ZONE_EXIT, ZONE_DWELL (≥30s dwell), BILLING_QUEUE_JOIN (requires `metadata.queue_depth > 0`), BILLING_QUEUE_ABANDON.

Validation enforces zone presence rules and retains low-confidence events (confidence is stored, not used to drop).

---

## 5. Session engine

Implemented in `app/sessions.py`:

- A **session** opens on ENTRY or REENTRY and closes on EXIT.
- **REENTRY** creates a new session for the same `visitor_id` without double-counting unique visitors.
- **Staff** sessions are built but excluded from customer analytics via `customer_sessions()`.
- Session fields include `zones_visited`, `reached_billing`, `joined_queue`, `abandoned_queue`, `billing_activity_at`, and `total_dwell_ms_by_zone`.

Helpers: `build_sessions()`, `count_unique_visitors()`, `customer_sessions()`.

---

## 6. Analytics logic (summary)

| Endpoint | Core logic |
|----------|------------|
| **Metrics** | Unique visitors, conversion rate (POS correlation), mean dwell per session, queue abandonment rate, billing reach rate, session count |
| **Funnel** | Visitor-level stages: unique → any zone → billing → converted; drop-off % between stages |
| **Heatmap** | Per-zone visits, dwell, engagement score; normalized 0–100 vs peak zone |
| **Anomalies** | Queue spike (join count), conversion drop (fixed thresholds), dead zone (low normalized heatmap score) |

**POS correlation** (`app/pos_correlation.py`): a session converts if it reached billing and a same-store POS transaction occurs within five minutes after `billing_activity_at`.

---

## 7. Data flow

1. **Ingest:** Client sends `{ "events": [ ... ] }` to `POST /events/ingest`.
2. **Persist:** Valid events stored in `events`; duplicates skipped by `event_id`.
3. **Query:** Endpoints load events (and POS rows) for `store_id` + UTC day.
4. **Derive:** `build_sessions(events)` → analytics functions → Pydantic response models.
5. **Seed (dev):** `python scripts/seed_from_sample.py` loads `data/sample_events.jsonl` and `data/pos_transactions.csv` when present.

---

## 8. Deployment

- **Docker:** `Dockerfile` runs `uvicorn app.main:app` on port 8000.
- **Compose:** `docker compose up --build` starts the `api` service; `./data` and `./logs` are bind-mounted.
- **Healthcheck:** Compose probes `GET /health` inside the container.
- **Environment:** `DATABASE_URL`, `LOG_LEVEL`, `LOG_FORMAT`, `STALE_FEED_THRESHOLD_MINUTES` (defaults in compose; no `.env` required).

---

## 9. Testing strategy

- **Framework:** pytest (107 tests at Phase 5 audit).
- **Coverage:** ~95% on `app/` (`pytest --cov=app`).
- **Suites:** `test_sessions`, `test_ingestion`, `test_metrics`, `test_funnel`, `test_heatmap`, `test_anomalies`, `test_health`, `test_edge_cases`, `test_seed`.
- **Edge cases:** Empty store, staff-only, zero purchases, REENTRY, batch limits, stale feed, idempotent seed.
- **Fixtures:** Fresh SQLite per test via `conftest.py` (`test_api.db`).

---

## 10. AI-assisted decisions

1. **In-memory sessions vs persisted session table**  
   An LLM recommended deriving sessions from the event stream at query time rather than maintaining a `visitor_sessions` table. This reduced schema complexity, kept ingest idempotent and simple, and aligned with the hackathon time box. Trade-off: repeated full scans per request (acceptable for SQLite + daily windows).

2. **Visitor-level funnel vs session-level funnel**  
   For REENTRY handling, the funnel counts distinct `visitor_id` values per stage (any session qualifies) so re-entry does not inflate unique visitors. AI helped articulate drop-off as `(prior_count - current) / prior_count × 100`.

3. **Deterministic anomaly thresholds**  
   Without seven days of historical data in the database, the implementation uses documented fixed thresholds in `app/anomalies.py` instead of a rolling baseline. AI suggested deferring 7-day averages until multi-day ingest exists, while still delivering queue spike, conversion drop, and dead-zone signals.

4. **Docker without mandatory `.env`**  
   Compose injects defaults inline so `docker compose up` works on a clean clone (acceptance gate #1). AI flagged that `env_file: .env` breaks fresh clones when `.env` is gitignored.

---

## 11. Known gaps (design level)

- CV pipeline not connected to ingest.
- Anomalies use fixed thresholds, not 7-day rolling averages or 30-minute dead-zone timers per PDF wording (requires multi-day / sub-hour event streams).
- Funnel does not expose a separate “Billing Queue” stage (`joined_queue` vs `reached_billing`).
- `CHOICES.md` documents model and storage decisions; detection choice is provisional until pipeline is built.
