# Technical Choices — Store Intelligence

> **Phase 0 skeleton.** Content will be expanded during implementation (minimum 250 words required for submission).

---

## Decision 1: Detection Model

**Options considered:**
- YOLOv8n (Ultralytics)
- YOLOv9
- RT-DETR
- MediaPipe

**What AI suggested:**
<!-- TBD -->

**Final choice:**
<!-- TBD -->

**Rationale:**
<!-- TBD -->

---

## Decision 2: Event Schema Design

**Options considered:**
- Flat event-per-action model
- Session-aggregated model
- Hybrid (events + session index)

**What AI suggested:**
<!-- TBD -->

**Final choice:**
<!-- TBD -->

**Rationale:**
<!-- TBD -->

---

## Decision 3: API Architecture

**Options considered:**
- SQLite (single-file, zero ops, hackathon-fast)
- PostgreSQL (production-grade, adds Docker complexity)

**What AI suggested:**
<!-- TBD -->

**Final choice:**
SQLite via SQLAlchemy (`sqlite:///./data/store_intelligence.db`)

**Rationale:**
<!-- TBD — 48h reliability, no DB container, acceptance-gate friendly -->

---

## Additional Decisions

<!-- Tracking algorithm, staff detection approach, zone classification, etc. -->
