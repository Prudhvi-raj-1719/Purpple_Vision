# Phase 6A — PDF Alignment Report

**Date:** May 2026  
**Scope:** Backend-only gaps fixable without CCTV/video pipeline work.

---

## 1. PDF gaps identified

| PDF requirement | Prior state | Phase 6A action |
|-----------------|-------------|-----------------|
| Metrics: `average_dwell_by_zone` | Only session-level `average_dwell_time_ms` | **Implemented** |
| Metrics: `current_queue_depth` | Missing | **Implemented** (latest non-staff `BILLING_QUEUE_JOIN` `metadata.queue_depth`) |
| Heatmap: `data_confidence` (<20 sessions) | Removed in Phase 4D | **Restored** (`bool`, `false` when &lt;20 customer sessions) |
| Anomalies: `suggested_action` | Only `title` + `description` | **Added** (kept existing fields for compatibility) |
| Logging: `event_count` on ingest | Missing | **Implemented** via `request.state` + middleware |
| Part D: `# PROMPT:` in tests | Missing | **Added** to all `tests/test_*.py` |
| Anomalies: 7-day conversion baseline | Fixed same-day thresholds | **Not implemented** — needs 7 days of historical ingest |
| Anomalies: dead zone = no visits 30 min | Heatmap normalized score | **Not implemented** — needs sub-hour / live zone event windows |
| Anomalies: `detected_at` | Removed earlier | **Not implemented** — not in current API contract |
| Anomalies: severity `WARN` vs `WARNING` | Uses `WARNING` | **Unchanged** — avoids breaking clients; PDF lists both spellings |
| Funnel: explicit Billing Queue stage | `reached_billing` only | **Not implemented** — funnel shape unchanged |
| POS correlation “5 min before txn” | Forward window from billing | **Not implemented** — semantic change, out of 6A scope |
| Part A: detection pipeline | Stubs | **Not touched** |
| Part E: dashboard | Stub | **Not touched** |

Sources: Phase 5 audit, `PROJECT_STATE.md`, original challenge PDF (Part B/C/D), git history of `app/models.py` scaffold.

---

## 2. What was implemented

### Metrics (`app/metrics.py`, `app/models.py`)

- `average_dwell_by_zone: list[{ zone_id, average_dwell_ms }]`
- `current_queue_depth: int` (0 when no customer queue joins)
- Tests: `tests/test_metrics.py` (`TestPdfMetricsFields`, endpoint assertions)

### Heatmap (`app/heatmap.py`, `app/models.py`)

- `data_confidence: bool` on `StoreHeatmapResponse`
- `MIN_SESSIONS_FOR_DATA_CONFIDENCE = 20`
- Tests: `tests/test_heatmap.py` (`TestDataConfidence`)

### Anomalies (`app/anomalies.py`, `app/models.py`)

- `suggested_action` on every anomaly (queue, conversion, dead zone)
- `title`, `description`, `supporting_metrics` retained
- Tests: `tests/test_anomalies.py`

### Logging (`app/logging_config.py`, `app/ingestion.py`)

- `event_count` in structured log payload for ingest requests
- Test: `tests/test_edge_cases.py` (`TestIngestLogging`)

### Documentation / examples

- Updated `examples/metrics_endpoint.json`, `heatmap_endpoint.json`, `anomalies_endpoint.json`
- `# PROMPT:` / `# CHANGES MADE:` headers on all nine test modules
- README, `DESIGN.md`, `CHOICES.md` touch-ups

---

## 3. Gaps still requiring dataset / video / multi-day data

| Gap | Why blocked |
|-----|-------------|
| YOLO / ByteTrack / zone / dwell / queue **pipeline** | Requires processing CCTV clips |
| Anomaly **7-day conversion baseline** | Needs ≥7 UTC days of events + POS per store in DB |
| Dead zone **30-minute inactivity** | Needs time-bucketed zone activity, not daily aggregates |
| **Real-time** queue depth without join events | Needs live pipeline emitting queue state |
| **Cross-camera deduplication** / group entry split | CV + layout logic |
| **POS HTTP ingest** | Optional; seed/ORM path works for challenge data |
| **Streamlit dashboard** | Part E bonus |
| **`tests/test_pipeline.py`** | Depends on pipeline output |
| **`tests/assertions.py`** challenge examples | Needs reference outputs from dataset |

---

## 4. Verification

```powershell
pytest --cov=app -q
```

All existing tests remain compatible; new fields are additive on metrics, heatmap, and anomalies responses.

---

## 5. Backward compatibility

- Existing metric fields unchanged.
- Heatmap zone objects unchanged; new top-level `data_confidence`.
- Anomalies retain `title`, `description`, `supporting_metrics`; clients may ignore `suggested_action`.
- Non-ingest requests omit `event_count` in logs (field omitted when unset).
