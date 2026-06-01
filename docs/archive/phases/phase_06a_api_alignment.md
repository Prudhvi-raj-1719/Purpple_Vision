# Phase 06A — API Alignment with Challenge Spec

**Status:** Complete  
**Scope:** Intelligence API fields and responses (no CCTV or dashboard work in this pass)

---

## What we added

Improvements so API responses match the challenge PDF more closely.

| Area | Added or restored |
|------|-------------------|
| **Metrics** | `average_dwell_by_zone` — dwell per product zone |
| **Metrics** | `current_queue_depth` — from latest billing queue event |
| **Heatmap** | `data_confidence` — `false` when fewer than 20 customer sessions (warns reviewers) |
| **Anomalies** | `suggested_action` — plain-language next step for store staff |
| **Logging** | `event_count` on ingest requests for observability |
| **Tests** | `# PROMPT:` headers on test modules per challenge Part D |

---

## Files touched

- `app/models.py`, `app/metrics.py`, `app/heatmap.py`, `app/anomalies.py`, `app/logging_config.py`
- `tests/test_metrics.py`, `tests/test_heatmap.py`, `tests/test_anomalies.py`
- `examples/metrics_endpoint.json`, `examples/heatmap_endpoint.json`, `examples/anomalies_endpoint.json`

---

## What we did not change in this phase

- Detection pipeline (Part A)  
- Streamlit dashboard layout (Part E)  
- Funnel billing-queue stage naming (completed in Phase 06B)  
- POS HTTP ingest endpoint (completed in Phase 06B)

---

## How to verify

```powershell
pytest tests/test_metrics.py tests/test_heatmap.py tests/test_anomalies.py -q
```

---

## Related

- [Phase 06B — API completeness](phase_06b_api_completeness.md)  
- [Phase 01 — Foundation](phase_01_foundation.md)
