# Technical Choices — Store Intelligence (Purpple_Vision)

This document records three primary technical decisions plus supporting choices. Each section lists options considered, AI input where applicable, the final choice, and rationale grounded in the **actual codebase** as of Phase 5.

---

## Decision 1: Detection model (planned pipeline)

**Options considered**

- **YOLOv8n (Ultralytics)** — small, fast, strong community, integrates with ByteTrack.
- **YOLOv9 / YOLOv10** — newer accuracy; heavier integration risk in 48 hours.
- **RT-DETR** — transformer detector; higher latency on CPU retail CCTV.
- **MediaPipe** — lightweight; weaker in crowded retail scenes.

**What AI suggested**

Use YOLOv8n as the default hackathon path: pre-trained COCO weights, CPU-viable inference, and first-class tracking examples. Defer custom training until baseline clip processing works.

**Final choice**

**YOLOv8n + ByteTrack** (planned; `pipeline/detect.py`, `pipeline/tracker.py` are stubs). Dependencies are already pinned in `requirements.txt` (`ultralytics`, `opencv-python-headless`, `lapx`).

**Rationale**

Part A scoring rewards reasoning and edge-case handling more than SOTA mAP. YOLOv8n minimizes cold-start risk, matches README/Docker OpenCV system libraries, and emits bounding boxes suitable for zone polygons and line-crossing logic. A heavier model risks blowing the time box before the Intelligence API (higher weighted path) was complete.

---

## Decision 2: Event schema and session model

**Options considered**

- **Flat event-per-action** — every behaviour is one JSON row; analytics computed on read.
- **Session-aggregated only** — pipeline emits session summaries; loses audit trail.
- **Hybrid** — events persisted + sessions derived in API (or materialized later).

**What AI suggested**

Persist immutable events matching the PDF schema; build sessions in the API layer. Use Pydantic v2 strict validation at ingest so malformed pipeline output never corrupts metrics.

**Final choice**

**Hybrid:** SQLite `events` table + in-memory `VisitorSession` via `app/sessions.build_sessions()`. No separate `visitor_sessions` table.

**Rationale**

- Ingest stays **idempotent** on `event_id` (`app/ingestion.py`).
- Full event history supports heatmap dwell sums and queue join counting.
- `REENTRY`, staff flags, and orphan EXIT rules are centralized in `sessions.py` with 97% test coverage.
- Trade-off: analytics recompute sessions each request — acceptable for day-scoped queries on SQLite.

Event validation lives in `app/models.Event` (zone rules, UUID v4, ZONE_DWELL ≥30s, queue_depth on BILLING_QUEUE_JOIN).

---

## Decision 3: API storage and architecture

**Options considered**

- **SQLite** — single file, zero ops, bind-mount in Docker.
- **PostgreSQL** — production-grade, extra container and migrations.
- **In-memory store** — fast demo; fails persistence and acceptance gates.

**What AI suggested**

SQLite for the hackathon: one `docker compose up`, no DB service, file survives restarts under `./data`. Use SQLAlchemy 2.0 sync API with FastAPI dependency `get_db()`.

**Final choice**

**SQLite** at `sqlite:///./data/store_intelligence.db` via SQLAlchemy 2.0 (`app/db.py`). WAL mode enabled on connect.

**Rationale**

- Meets Part C “no manual DB setup” when combined with current Dockerfile/Compose.
- POS and events share one file for join queries by `store_id` and day.
- `CHOICES.md` and `DESIGN.md` can honestly describe deployment.
- Trade-off: not ideal for high concurrent write load — out of scope for challenge scale.

**API framework:** FastAPI + Uvicorn. Routers split by domain (`metrics`, `funnel`, `heatmap`, `anomalies`, `ingestion`, `health`). Global handlers return HTTP 503 on `SQLAlchemyError` with `ErrorResponse` including `trace_id` from middleware.

---

## Additional decisions

### POS conversion window

**Choice:** `transaction.timestamp − 5 minutes ≤ billing_activity_at ≤ transaction.timestamp` (`app/pos_correlation.py`).

**Rationale:** Matches the challenge PDF rule that the visitor was in billing within five minutes before the POS transaction.

### Anomaly detection

**Choice:** Fixed thresholds in `app/anomalies.py` (e.g. queue joins ≥10/≥20, conversion rate <0.20/<0.10, heatmap normalized score <20/<10). No multi-day history table yet.

**Rationale:** Delivers testable anomalies without seeding seven days of data.

### Structured logging

**Choice:** JSON access logs via `RequestLoggingMiddleware` — `trace_id`, `endpoint`, `latency_ms`, `status_code`, optional `store_id` from path. No external log aggregator.

**Ingest:** `POST /events/ingest` sets `request.state.event_count` to `total_received`; middleware includes it in structured access logs.

### Staff exclusion

**Choice:** `is_staff` on events; `customer_sessions()` filters staff for all customer metrics. Staff sessions still built for audit consistency.

### Heatmap normalization

**Choice:** `engagement_score = visit_count + total_dwell_ms/1000`; highest zone scores 100 (`app/heatmap.py`).

### Seed workflow

**Choice:** `scripts/seed_from_sample.py` idempotently loads JSONL + CSV when files exist under `./data/`. No separate POS HTTP ingest route; POS rows inserted directly for tests and seeding.

---

## Summary

| Area | Decision | Status in repo |
|------|----------|----------------|
| Detection | YOLOv8n + ByteTrack | Scaffold only |
| Events + sessions | Hybrid persist + derive | Implemented |
| Database | SQLite + SQLAlchemy | Implemented |
| API | FastAPI domain routers | Implemented |
| Anomalies | Fixed thresholds | Implemented |
| Logging | JSON middleware | Implemented |
| Docker | Uvicorn CMD, compose healthcheck | Implemented |
