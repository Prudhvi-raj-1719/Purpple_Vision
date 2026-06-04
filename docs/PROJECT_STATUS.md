# Project Status

**Last updated:** 2026-06-04  
**Submission guide:** [SUBMISSION.md](SUBMISSION.md)

---

## Completed

- ✓ **Detection Pipeline** — YOLO11m + ByteTrack; CAM1/CAM2/CAM3/CAM5 per store (`store_1`, `store_2`)
- ✓ **Per-store outputs** — `pipeline_demo_store_1`, `pipeline_demo_store_2` JSONL + tracking MP4
- ✓ **Event Ingestion** — `POST /events/ingest` with idempotent UUID dedup
- ✓ **Session Logic** — ENTRY/REENTRY → EXIT
- ✓ **Metrics / Funnel / Heatmap / Anomalies / Health**
- ✓ **Dashboard** — Streamlit with four store modes (validation + CCTV real)
- ✓ **store1_real / store2_real** — Manager UI, shelf videos (FFmpeg → H.264), brand-area analytics
- ✓ **Demo Runner** — `scripts/demo_runner.py` per `PURPPLE_STORE`
- ✓ **Validation datasets** — `store_1_validation.db`, `store_2_validation.db`
- ✓ **Docker** — API + optional dashboard profile (FFmpeg in image for video)

---

## Dashboard stores

| Label | Database | Layout |
|-------|----------|--------|
| Store 1 | `store_1_validation.db` | SaaS analytics |
| Store 2 | `store_2_validation.db` | SaaS analytics |
| store1_real | `store_1_intelligence.db` | CCTV manager view |
| store2_real | `store_2_intelligence.db` | CCTV manager view |

---

## Submission demo (video)

1. Install FFmpeg (see [SUBMISSION.md](SUBMISSION.md)).
2. `pip install -r requirements.txt`
3. `streamlit run dashboard/streamlit_app.py`
4. Select **store1_real** or **store2_real**, date **2026-04-10**.

No Render / cloud deploy required for judging.

---

## Validation snapshot (synthetic)

```powershell
python scripts/demo_validation_run.py --store all
```

| Store | Visitors | Conversion | Revenue (INR) | Date |
|-------|----------|------------|---------------|------|
| store_1 | 3 | 66.7% | 2,148.50 | 2026-06-01 |
| store_2 | (see report) | — | — | 2026-04-10 |

Reports: [reports/demo_validation_report_store_1.md](reports/demo_validation_report_store_1.md), [store_2](reports/demo_validation_report_store_2.md)

---

## Known operational notes

1. **Brigade CCTV (store_1)** — shelf zones fire without CAM3 ENTRY on some days → `unique_visitors` may be 0 on `/metrics`; **store1_real** falls back to shelf shopper counts for the Visitors KPI.
2. **store_2** — CAM2 disabled; right-camera tab may be empty until CAM2 footage is added.
3. **Shelf videos** — OpenCV writes `mp4v`; browsers need FFmpeg to build `*_web.mp4` for playback.
4. **Purchase matching** — offline JSON only; not on the manager dashboard.

---

## Quick commands

```powershell
pip install -r requirements.txt
streamlit run dashboard/streamlit_app.py
pytest
python scripts/demo_validation_run.py --store all
$env:PURPPLE_STORE = "store_1"; python scripts/demo_runner.py
docker compose up --build
```
