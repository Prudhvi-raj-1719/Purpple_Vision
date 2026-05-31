# Purpple Vision — Project State

**Last updated:** 2026-05-31 (documentation cleanup)  
**Overall completion:** ~76% · **Demo readiness:** ~35/100 · **Submission readiness:** ~80/100

Quick links: [README](README.md) · [DESIGN](DESIGN.md) · [Historical reports](docs/archive/)

---

## North Star

```
Conversion Rate = Visitors who completed a purchase ÷ Total unique visitors
```

POS correlation: billing activity within **5 minutes before** transaction timestamp (`app/pos_correlation.py`).

---

## Completed features

### Intelligence API (`app/`) — ~96%

- [x] Event + POS batch ingest (idempotent, partial success)
- [x] Session engine (ENTRY/REENTRY → EXIT)
- [x] Metrics, funnel, heatmap, anomalies, health endpoints
- [x] POS correlation window
- [x] Structured JSON logging + trace IDs
- [x] Docker deployment (no mandatory `.env`)
- [x] 125 pytest tests, ~95% `app/` coverage

### Computer vision pipeline (`pipeline/`) — code ~75%

- [x] YOLO11m detection + ByteTrack
- [x] Zone polygon overlap (`zones.py`)
- [x] CAM1/CAM2 dwell processor (66 demo events generated)
- [x] CAM3 entry/exit processor (code complete)
- [x] CAM5 queue/billing processor (code complete)
- [x] Event emission + NOTEBK adapter
- [x] Brigade POS loader (24 invoices)
- [x] Offline purchase matching
- [x] Demo orchestrator (`run_pipeline_demo.py`)

### Product integration

- [x] Bridge script (`bridge_pipeline_to_product.py`) → SQLite
- [x] Seed script for challenge-format data
- [x] Example API payloads (`examples/`)

### Dashboard — ~82%

- [x] Streamlit UI (`dashboard/streamlit_app.py`)
- [x] KPIs, funnel, heatmap, anomalies via FastAPI
- [x] Empty-state when sessions = 0

---

## Partially implemented

| Feature | Done | Gap |
|---------|------|-----|
| Multi-camera pipeline | CAM1/CAM2 emit events | CAM3/CAM5 demo JSONL **empty** (0 ENTRY) |
| End-to-end demo | Bridge + API work | Manual steps; **0 sessions** with current data |
| Purchase matching | Algorithm + JSON output | 0 matches; not in API |
| Anomaly detection | 3 live detectors | Fixed thresholds vs PDF rolling baselines |
| Revenue in dashboard | KPI card | No API revenue endpoint → shows **—** |
| REENTRY events | Logic in entry_exit | Not observed in demo output |
| Documentation | README/DESIGN current | Was outdated pre-cleanup |

---

## Remaining gaps

### Critical (demo impact)

1. **CAM3 ENTRY detection** — zero entries on last Brigade clip run → zero sessions.
2. **Automated pipeline → API** — bridge not chained in demo orchestrator.
3. **Non-zero analytics demo** — requires ENTRY + billing events + aligned POS times.

### Important (submission quality)

4. **`tests/assertions.py`** — challenge ground-truth assertions empty.
5. **`test_pipeline.py`** — no pipeline CI tests.
6. **`run_pipeline.sh`** — bash skeleton only.
7. **`pipeline/staff.py`** — staff classification not implemented.

### Nice-to-have

8. Cross-camera visitor deduplication (ReID).
9. 7-day anomaly baselines + 30-min dead-zone timer.
10. Daily revenue GET endpoint.
11. Purchase matches in API/DB.
12. Terminal dashboard (`rich`) and React frontend stubs.

---

## Future work

| Priority | Task |
|----------|------|
| P0 | Fix CAM3 geometry/thresholds; re-run demo + bridge |
| P0 | Chain `run_pipeline_demo` → `bridge_pipeline_to_product` |
| P1 | Populate `tests/assertions.py` with challenge examples |
| P1 | Add `test_pipeline.py` smoke tests |
| P1 | Implement `staff.py` or document staff-flag heuristic |
| P2 | Rolling anomaly baselines when multi-day data available |
| P2 | Revenue summary endpoint from POS table |
| P3 | Cross-camera ReID; purchase match API |

---

## Completion estimate

| Challenge part | Completion |
|----------------|------------|
| Part A — Detection pipeline | ~58% |
| Part B — Intelligence API | ~95% |
| Part C — Production (Docker, tests, logging) | ~88% |
| Part D — Documentation | ~85% (post-cleanup) |
| Part E — Dashboard bonus | ~82% |
| **Weighted overall** | **~76%** |

### Acceptance gates

| Gate | Status |
|------|--------|
| `docker compose up` starts API | Pass |
| README explains pipeline + demo | Pass (updated) |
| `POST /events/ingest` works | Pass |
| `GET /stores/.../metrics` returns JSON | Pass |
| DESIGN.md substantive | Pass |

---

## API reference (quick)

| Method | Path |
|--------|------|
| `GET` | `/health` |
| `POST` | `/events/ingest` |
| `POST` | `/pos/ingest` |
| `GET` | `/stores/{store_id}/metrics?date=YYYY-MM-DD` |
| `GET` | `/stores/{store_id}/funnel?date=YYYY-MM-DD` |
| `GET` | `/stores/{store_id}/heatmap?date=YYYY-MM-DD` |
| `GET` | `/stores/{store_id}/anomalies?date=YYYY-MM-DD` |

---

## Quick commands

```powershell
uvicorn app.main:app --reload --port 8000
pytest --cov=app
python scripts/run_pipeline_demo.py
python scripts/bridge_pipeline_to_product.py
streamlit run dashboard/streamlit_app.py --server.port 8501
docker compose up --build
```

---

## Current demo data snapshot

| Artifact | Value |
|----------|-------|
| Events in SQLite | 66 (zone-only, CAM1/CAM2) |
| POS transactions | 24 |
| Sessions | 0 |
| Metric date | `2026-04-10` |
| Store | `STORE_BLR_002` |

See [docs/archive/final_session_gap_report.md](docs/archive/final_session_gap_report.md) for root-cause analysis.
