# Phase 6B — Final API Completeness Report

**Date:** May 2026  
**Scope:** Code-only gaps from the final submission audit (no pipeline/dashboard changes).

---

## 1. Gaps closed

| # | Gap | Implementation |
|---|-----|----------------|
| 1 | `POST /pos/ingest` | `app/pos_ingestion.py` — batch ≤500, idempotent by `transaction_id`, partial success; wired in `app/main.py` |
| 2 | Funnel Billing Queue stage | Funnel stage `billing_queue` counts visitors with `joined_queue` (not zone-only billing); `visitors_joined_billing_queue()` in `app/funnel.py` |
| 3 | POS conversion window | `app/pos_correlation.py` — `txn − 5min ≤ billing_activity_at ≤ txn` (PDF wording) |
| 4 | Anomaly `detected_at` | `Anomaly.detected_at` UTC on every alert; optional injectable for tests |
| 5 | Severity INFO / WARN / CRITICAL | `AnomalySeverity`: `INFO`, `WARN`, `CRITICAL`; alerts use `WARN` instead of `WARNING` |
| 6 | README inconsistencies | 125 tests, `/pos/ingest` in table, funnel stage note, POS window note, ingest paths |

### Models & examples

- `PosIngestErrorDetail`, `PosIngestStatusResponse` in `app/models.py`
- `examples/pos_ingest_endpoint.json`, updated `funnel_endpoint.json` and `anomalies_endpoint.json`
- `CHOICES.md` / `DESIGN.md` POS window text updated

### Tests added/updated

| File | Changes |
|------|---------|
| `tests/test_pos_ingestion.py` | **New** — 6 tests for POS ingest |
| `tests/test_metrics.py` | POS window tests (before txn, after txn) |
| `tests/test_funnel.py` | `billing_queue` stage, join vs zone-only |
| `tests/test_anomalies.py` | `detected_at`, `WARN`, enum coverage |
| `tests/test_edge_cases.py` | Funnel stage key `billing_queue` |

---

## 2. Backward compatibility notes

| Change | Impact |
|--------|--------|
| Funnel stage `reached_billing` → `billing_queue` | Stage **name** changed to match PDF; counts now use `joined_queue` |
| `AnomalySeverity.WARNING` → `WARN` | JSON severity values are `"WARN"` (PDF-aligned) |
| POS conversion window | Sessions converted only if billing falls in the 5-minute window **before** txn (may change conversion counts vs Phase 6A forward window) |

Existing response fields (`title`, `description`, `supporting_metrics`, etc.) are unchanged.

---

## 3. Gaps still impossible without CCTV / video / multi-day data

| Gap | Why still blocked |
|-----|-------------------|
| Part A detection pipeline (YOLO, tracking, zones, dwell, queue, staff, emit) | Requires CCTV clip processing |
| `scripts/run_pipeline.sh` functional | Depends on pipeline |
| `tests/test_pipeline.py` | No pipeline output |
| `tests/assertions.py` challenge ground truth | Needs reference outputs from dataset/clips |
| Anomaly **7-day conversion baseline** | Needs ≥7 days of stored history + rolling query |
| Dead zone **30-minute inactivity** | Needs sub-hour zone event streams from live CV |
| Cross-camera deduplication / group entry split | CV + layout logic |
| Streamlit dashboard (Part E bonus) | Out of scope |
| True live queue depth without join events | Needs continuous pipeline state |

### Optional future (no video)

| Gap | Notes |
|-----|-------|
| Emit `INFO` severity anomalies | Enum supported; no detector uses `INFO` yet |
| `tests/assertions.py` | Can populate if static expected JSON provided |

---

## 4. Verification

```powershell
pytest --cov=app -q
```

Expected: all tests pass; `app/` coverage ~95%.

---

## 5. Estimated rubric impact (vs pre–Phase 6B audit)

| Section | Before | After (est.) |
|---------|--------|----------------|
| Part B API | ~86% | **~95%** |
| Part C (POS HTTP ingest) | partial | **improved** |
| Base score | ~63/100 | **~68–72/100** |
| Submission readiness | ~72% | **~78%** |

Part A (30 pts) remains the primary uncovered block.
