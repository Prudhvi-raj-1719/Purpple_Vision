# Engineering Choices — Purpple Vision

Five decisions that shaped the Store Intelligence platform. Each follows: **Problem → Options → AI recommendation → Final decision → Reasoning**.

---

## Decision 1: Detection stack selection

### Problem

Process 20-minute multi-camera CCTV clips on CPU-class hardware and emit structured behavioural events for analytics.

### Options considered

| Option | Pros | Cons |
|--------|------|------|
| **YOLO11m + ByteTrack + rule-based zones** | Fast to ship, COCO weights, polygon zones | Not SOTA mAP; per-camera IDs |
| RT-DETR / YOLOv10 | Better accuracy | Heavier tuning; less hackathon time |
| VLM zone classification | Flexible labels | Latency, cost, non-deterministic |
| MediaPipe | Lightweight | Weak multi-person retail scenes |

### AI recommendation

Use pre-trained YOLO with ByteTrack; invest time in edge-case rules (re-entry, queue, dwell stability) rather than model training.

### Final decision

**YOLO11m + ByteTrack + polygon zone rules** (`pipeline/detect.py`, `tracker.py`, `zones.py`, `dwell.py`, `entry_exit.py`, `queue.py`).

### Reasoning

Challenge Part A rewards edge-case handling and schema quality over benchmark mAP. CPU-viable inference with frame skipping (`PROCESS_EVERY_N_FRAMES = 10`) enables four-camera demo runs. Rule-based line crossing and zone overlap are auditable for reviewers.

---

## Decision 2: Event-driven architecture

### Problem

Persist visitor behaviour for idempotent ingest, replay, and multiple analytics views (funnel, heatmap, anomalies).

### Options considered

| Option | Pros | Cons |
|--------|------|------|
| **Immutable events + derived sessions** | Idempotent ingest; full history | Recompute sessions per request |
| Session-aggregated only | Fast reads | Lose event granularity; hard replay |
| Flat metrics only | Simplest API | Cannot audit funnel stages |
| Stream processor (Kafka) | Real-time scale | Over-engineered for SQLite hackathon |

### AI recommendation

Hybrid: store raw events; derive `VisitorSession` in memory at query time.

### Final decision

**Event-driven persistence** — SQLite `events` table + `build_sessions()` in `app/sessions.py`.

### Reasoning

Matches challenge ingest contract (`event_id` dedup). Heatmap needs per-zone dwell; funnel needs stage transitions. Recomputing sessions for one UTC day is acceptable at hackathon scale.

---

## Decision 3: SQLite for challenge deployment

### Problem

Zero-ops database for `docker compose up` acceptance gate and local reviewer setup.

### Options considered

| Option | Pros | Cons |
|--------|------|------|
| **SQLite** | Single file, bind mount, no extra service | Limited concurrent writes |
| PostgreSQL | Production-grade | Extra container, migrations |
| In-memory only | Fastest tests | No persistence across restarts |
| DuckDB / parquet | Analytics speed | Non-standard for FastAPI CRUD |

### AI recommendation

SQLite with SQLAlchemy 2.0; document `DATABASE_URL` override path.

### Final decision

**SQLite** at `data/databases/store_intelligence.db` with isolated demo DBs for validation.

### Reasoning

Challenge explicitly allows SQLite. Single bind-mounted file survives Docker restarts. Separate `demo_validation.db` prevents synthetic tests from touching production data.

---

## Decision 4: Session-based funnel (not event counting)

### Problem

Funnel must show Entry → Zone → Billing → Purchase without double-counting re-entries or orphan events.

### Options considered

| Option | Pros | Cons |
|--------|------|------|
| **Visitor-level funnel** | One row per shopper; REENTRY safe | Requires session engine first |
| Raw event counts | Easy to implement | Inflates visitors; breaks drop-off |
| Session-level funnel | Per-visit detail | Double-counts repeat visitors |
| POS-only funnel | Simple | Ignores store journey |

### AI recommendation

Compute funnel on unique `visitor_id` with session semantics; exclude staff.

### Final decision

**Session-based funnel** with visitor-level stages in `app/funnel.py`.

### Reasoning

North Star conversion is visitors ÷ visitors. REENTRY opens a new session but not a new unique visitor. Orphan zone events without ENTRY are excluded automatically (no session).

---

## Decision 5: Synthetic validation dataset

### Problem

Brigade demo pipeline produced zone events but **zero ENTRY** → zero sessions → empty dashboard despite working API.

### Options considered

| Option | Pros | Cons |
|--------|------|------|
| **Synthetic JSONL + isolated DB** | Proves full stack deterministically | Not real CCTV |
| Fix CAM3 only | Real data | Time-consuming; clip-dependent |
| Hardcode API responses | Fast demo | Fails integrity check |
| Seed from challenge sample only | Official format | May lack billing correlation |

### AI recommendation

Create tiny synthetic dataset with ENTRY, zones, billing, POS aligned to 5-minute correlation window.

### Final decision

**`data/synthetic/demo_events.jsonl` + `demo_pos.csv`** ingested via `scripts/demo_validation_run.py` into `demo_validation.db`.

### Reasoning

Validates sessions (3), conversion (66.7%), revenue (₹2,148.50), funnel, and dashboard without modifying business logic. Reviewers can reproduce in one command. Real Brigade pipeline remains separate under `data/outputs/`.

---

## Summary table

| # | Decision | Choice |
|---|----------|--------|
| 1 | Detection stack | YOLO11m + ByteTrack + rules |
| 2 | Architecture | Event-driven + derived sessions |
| 3 | Database | SQLite (isolated demo DBs) |
| 4 | Funnel | Session-based, visitor-level |
| 5 | Validation | Synthetic ENTRY dataset |

Architecture details: [DESIGN.md](DESIGN.md)

Historical phase logs: [archive/phases/](archive/phases/)
