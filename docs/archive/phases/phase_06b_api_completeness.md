# Phase 06B — API Completeness (Submission Hardening)

**Status:** Complete  
**Scope:** Final API gaps before submission (backend only)

---

## What we added

| Feature | Implementation |
|---------|----------------|
| **POS ingest endpoint** | `POST /pos/ingest` — same idempotency model as events (`app/pos_ingestion.py`) |
| **Funnel billing stage** | Stage `billing_queue` — visitors who joined the billing queue |
| **POS correlation window** | Billing activity must fall within **5 minutes before** transaction time |
| **Anomaly timestamps** | `detected_at` on every alert |
| **Severity labels** | `INFO`, `WARN`, `CRITICAL` (PDF-aligned) |
| **Documentation** | README and examples updated for `/pos/ingest` and funnel stages |

---

## Tests added

- `tests/test_pos_ingestion.py` — POS batch ingest  
- Updates to `tests/test_metrics.py`, `tests/test_funnel.py`, `tests/test_anomalies.py`

---

## Behaviour reviewers should know

**Conversion rate** uses visitor-level counting: a customer with multiple sessions (REENTRY) counts once if any session converts.

**Funnel stages (in order):**

1. Visitors (entry)  
2. Engaged (zone visit)  
3. Billing queue  
4. Purchased (POS)

---

## How to verify

```powershell
pytest
```

Full suite: **126 tests** covering ingest, sessions, metrics, funnel, heatmap, anomalies, health.

---

## Related

- [Phase 06A — API alignment](phase_06a_api_alignment.md)  
- [Phase 03 — Session builder](phase_03_session_builder.md)  
- [api_reference.md](../../architecture/api_reference.md)
