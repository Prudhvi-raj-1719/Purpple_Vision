# Project Status

**Last updated:** 2026-06-01 (documentation refresh)  
**Store:** `STORE_BLR_002` (Brigade Bangalore demo)

Quick links: [README](../README.md) · [DESIGN](DESIGN.md) · [project journey](reports/project_journey.md)

---

## Completed

- ✓ **Detection Pipeline** — YOLO11m + ByteTrack; CAM1/CAM2/CAM3/CAM5 processors, POS loader, purchase matching
- ✓ **Event Ingestion** — `POST /events/ingest` with idempotent UUID dedup
- ✓ **Session Logic** — ENTRY/REENTRY → EXIT; visitor-level dedup for REENTRY
- ✓ **Metrics** — visitors, sessions, dwell, queue, billing reach, conversion
- ✓ **Funnel** — visitor-level stages with drop-off percentages
- ✓ **Heatmap** — zone engagement scores with data-confidence flag
- ✓ **Anomalies** — QUEUE_SPIKE, CONVERSION_DROP, DEAD_ZONE
- ✓ **Health Endpoint** — DB availability, feed staleness, STALE_FEED warnings
- ✓ **Dashboard** — Streamlit UI consuming FastAPI only
- ✓ **Revenue KPI** — `total_revenue_inr` on `/metrics` and dashboard card
- ✓ **Validation Dataset** — `data/synthetic/` with ENTRY events (3 sessions, 66.7% conversion)
- ✓ **Demo Runner** — `scripts/demo_runner.py` orchestrates pipeline → bridge → validation

---

## Bonus

- ✓ **Dashboard UI** — health panel, queue KPIs, dwell-by-zone table, heatmap confidence badge, reviewer labels

---

## Future Improvements

- Real-time WebSocket updates (live dashboard refresh without manual reload)
- Better anomaly baselines (7-day rolling conversion, 30-minute dead-zone timer per challenge PDF)
- Production PostgreSQL deployment (multi-store, concurrent ingest)

---

## Validation snapshot

Run `python scripts/demo_validation_run.py` for deterministic proof:

| Metric | Expected |
|--------|----------|
| Visitors | 3 |
| Sessions | 3 |
| Converted | 2 |
| Revenue (INR) | 2,148.50 |
| Conversion | 66.7% |

Report: [reports/demo_validation_report.md](reports/demo_validation_report.md)

---

## Documentation map

| Path | Contents |
|------|----------|
| [reports/project_journey.md](reports/project_journey.md) | Complete development story (Phase 1–6) |
| [reports/](reports/) | Validation and verification evidence |
| [archive/](archive/) | Superseded docs and migration notes |

---

## Known operational gaps

1. **Brigade CCTV demo** — zone-only events without CAM3 ENTRY → 0 sessions on production bridged data (`2026-04-10`). Use validation DB + `2026-06-01` for non-zero dashboard demo.
2. **Purchase matching** — offline JSON only; not exposed via API.
3. **Staff detection** — pipeline stub; metrics respect `is_staff` flag when set.
4. **Cross-camera ReID** — not implemented; visitor IDs are per-camera track tokens.

---

## Quick commands

```powershell
docker compose up --build
pytest
python scripts/demo_validation_run.py
python scripts/demo_runner.py
streamlit run dashboard/streamlit_app.py
```
