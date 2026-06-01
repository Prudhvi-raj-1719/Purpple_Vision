# Phase 02 — Detection Pipeline (CCTV → Events)

**Status:** Complete  
**Challenge part:** A (Detection layer)

---

## What we built

Computer-vision processors that read Brigade CCTV clips and write **behavioural events** in Purpple schema (JSONL files).

| Camera | Module | What it detects |
|--------|--------|-----------------|
| **CAM1** | `pipeline/cam1_processor.py` | Shelf zones — left wall (ZONE_ENTER, ZONE_EXIT, ZONE_DWELL) |
| **CAM2** | `pipeline/cam2_processor.py` | Shelf zones — right wall |
| **CAM3** | `pipeline/entry_exit.py` | Store entry and exit (**ENTRY**, **EXIT**, REENTRY) — required for sessions |
| **CAM5** | `pipeline/queue.py` | Billing queue (BILLING_QUEUE_JOIN, BILLING_QUEUE_ABANDON) |

**Shared stack:** YOLO11m person detection + ByteTrack tracking + polygon zones (`pipeline/zones.py`). Events are emitted through `pipeline/emit.py` with schema validation.

**Performance:** Inference runs every 10th video frame (`PROCESS_EVERY_N_FRAMES` in `pipeline/config.py`) so a ~30-minute clip finishes in roughly 25–30 minutes per camera on CPU-class hardware.

---

## Outputs

| Path | Contents |
|------|----------|
| `data/outputs/pipeline/pipeline_demo/cam*_events.jsonl` | Purpple-schema events for the API |
| `data/outputs/pipeline/pipeline_demo/cam*_events.notbk.jsonl` | Raw mirror for offline purchase matching |

---

## How to run

```powershell
# Single camera
python -m pipeline.cam1_processor

# All cameras
python scripts/run_pipeline_demo.py

# Full demo (cameras + POS + bridge + validation)
python scripts/demo_runner.py
```

`scripts/demo_runner.py` clears previous pipeline JSONL files and `purchase_matches.json` before each run so results are reproducible.

---

## What reviewers should know

- **CAM1/CAM2 alone do not open sessions** — zone events without CAM3 ENTRY are ignored by the session builder (see Phase 03).
- Brigade demo footage may produce zone events but zero ENTRY lines; use the **synthetic validation dataset** (`scripts/demo_validation_run.py`) to see non-zero KPIs on the dashboard.
- **CAM4 (staff)** is not implemented; `pipeline/staff.py` is a placeholder.

---

## Related

- [Phase 03 — Session Builder](phase_03_session_builder.md)
- [Phase 06 — Product integration](phase_06_product_integration.md)
