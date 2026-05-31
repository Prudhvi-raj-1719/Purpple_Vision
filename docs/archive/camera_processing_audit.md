# Camera Processing Audit — Inference Frequency Consistency

**Date:** 2026-05-30  
**Scope:** All pipeline camera processors and shared video loops  
**Config source of truth:** `pipeline/config.py`

| Constant | Value | Purpose |
|----------|-------|---------|
| `PROCESS_EVERY_N_FRAMES` | **10** | YOLO/ByteTrack inference stride (all cameras) |
| `PROGRESS_LOG_EVERY_N_FRAMES` | **100** | Progress log interval on original video frame index |

---

## 1. Processor architecture

```
pipeline/config.py          ← PROCESS_EVERY_N_FRAMES, PROGRESS_LOG_EVERY_N_FRAMES
        │
        ├── cam1_processor.py ──► dwell.process_zone_engagement_video()
        ├── cam2_processor.py ──► dwell.process_zone_engagement_video()
        ├── entry_exit.py (CAM3) ──► process_cam3_video() [inline loop]
        ├── queue.py (CAM5) ──► process_cam5_video() [inline loop]
        └── staff.py (CAM4) ──► stub only (no video loop)
```

| Camera | Entry file | Shared engine | Detection module |
|--------|------------|---------------|------------------|
| CAM1 | `cam1_processor.py` | `dwell.ZoneEngagementEngine` | `detect.detect_persons()` |
| CAM2 | `cam2_processor.py` | `dwell.ZoneEngagementEngine` | `detect.detect_persons()` |
| CAM3 | `entry_exit.py` | `EntryExitCounter` | `detect.detect_persons()` |
| CAM4 | `staff.py` | — | **Not implemented** |
| CAM5 | `queue.py` | `PaymentQueueEngine` | `queue.detect_persons()` (local wrapper) |

All active processors decode every video frame but run YOLO only when `frame_index % PROCESS_EVERY_N_FRAMES == 0`. Event engines receive the **original video frame index** on sampled frames only — event semantics and timestamps are unchanged.

---

## 2. Inference frequency table

| Camera | Processor | Frame skip? | `PROCESS_EVERY_N_FRAMES` source | Effective stride | Skip location |
|--------|-----------|-------------|-----------------------------------|------------------|---------------|
| CAM1 | `cam1_processor.py` → `dwell.py` | **Yes** | `config.py` | **every 10 frames** | `dwell.py` ~L369 |
| CAM2 | `cam2_processor.py` → `dwell.py` | **Yes** | `config.py` | **every 10 frames** | `dwell.py` ~L369 |
| CAM3 | `entry_exit.py` | **Yes** | `config.py` | **every 10 frames** | `entry_exit.py` ~L269 |
| CAM4 | `staff.py` | N/A | — | **no pipeline** | — |
| CAM5 | `queue.py` | **Yes** | `config.py` *(was local duplicate)* | **every 10 frames** | `queue.py` ~L524 |

### YOLO call rate (per 10,000 video frames)

| Camera | Before audit | After audit |
|--------|--------------|-------------|
| CAM1 | 1,000 calls | 1,000 calls (unchanged) |
| CAM2 | 1,000 calls | 1,000 calls (unchanged) |
| CAM3 | 1,000 calls *(fixed earlier)* | 1,000 calls |
| CAM4 | — | — |
| CAM5 | 1,000 calls | 1,000 calls *(already skipped; now uses shared config)* |

---

## 3. CAM4 / CAM5 detail

### CAM4 — no processor

- **File:** `pipeline/staff.py` — one-line module docstring only.
- **No** `process_cam4_video()`, no `VideoCapture` loop, no YOLO calls.
- Staff classification is applied downstream via `is_staff` on events (`event_adapter.py`, `app/sessions.py`), not from a dedicated CAM4 clip processor in this repo.
- **Action:** None required until a CAM4 video processor is implemented; when added, it must import `PROCESS_EVERY_N_FRAMES` from `config.py`.

### CAM5 — frame skipping confirmed

**Before audit:** CAM5 already skipped inference every 10 frames but defined a **local** `PROCESS_EVERY_N_FRAMES = 10` in `queue.py` (line 40), duplicating `config.py`.

**Exact skip guard (unchanged logic, now uses config import):**

```python
# pipeline/queue.py — process_cam5_video()
if original_frame % PROCESS_EVERY_N_FRAMES != 0:
    original_frame += 1
    ...
    continue

detections = detect_persons(frame, yolo_model)  # only on frames 0, 10, 20, …
```

**Change applied:** Removed local constant; import `PROCESS_EVERY_N_FRAMES` and `PROGRESS_LOG_EVERY_N_FRAMES` from `config.py`. Added progress logging. Event logic in `PaymentQueueEngine` untouched.

---

## 4. Changes applied in this audit

| File | Change |
|------|--------|
| `config.py` | Added `PROGRESS_LOG_EVERY_N_FRAMES = 100` |
| `dwell.py` | Progress logs every 100 frames (skip + process paths); `total_frames` in startup log |
| `entry_exit.py` | Progress logs on skip path; `PROGRESS_LOG_EVERY_N_FRAMES` from config |
| `queue.py` | Import shared constants from config; progress logs every 100 frames |

Progress log format (all cameras):

```
[PROGRESS] <camera> frame=<video_frame> processed=<inference_count> (<pct>% complete) <event_counts…>
```

Event counts logged per camera:

| Camera | Counts in progress line |
|--------|-------------------------|
| CAM1/CAM2 | `zone_enter`, `zone_exit`, `dwell_completed` |
| CAM3 | `entries`, `exits` |
| CAM5 | `queue_enter`, `queue_exit`, `payment_enter`, `payment_exit` |

---

## 5. Estimated runtime per camera

Assumptions: 1535×864, YOLO11m, ~250 ms/inference, ~5 ms/decode per frame, 30 fps, **30-minute clip** (~54,000 frames).

| Camera | Frames | YOLO calls | Est. decode | Est. inference | **Est. total** |
|--------|--------|------------|-------------|----------------|----------------|
| CAM1 | 54,000 | 5,400 | ~4.5 min | ~22.5 min | **~27 min** |
| CAM2 | 54,000 | 5,400 | ~4.5 min | ~22.5 min | **~27 min** |
| CAM3 | 54,000 | 5,400 | ~4.5 min | ~22.5 min | **~27 min** |
| CAM4 | — | 0 | — | — | **N/A** |
| CAM5 | 54,000 | 5,400 | ~4.5 min | ~22.5 min | **~27 min** |

### Hypothetical every-frame inference (stride = 1)

| Metric | Stride 1 | Stride 10 |
|--------|----------|-----------|
| YOLO calls / 30 min clip | 54,000 | 5,400 |
| Inference wall time | ~225 min (~3.8 h) | ~22.5 min |
| **Speedup vs every-frame** | 1× | **~10× on inference** |
| **End-to-end speedup (YOLO-bound)** | 1× | **~6–8×** |

CAM3 was the outlier before the prior fix (every-frame YOLO ≈ 3.8 h per 30 min clip). It now matches CAM1/CAM2/CAM5.

---

## 6. Consistency checklist

- [x] CAM1 uses `PROCESS_EVERY_N_FRAMES` from `config.py` via `dwell.py`
- [x] CAM2 uses `PROCESS_EVERY_N_FRAMES` from `config.py` via `dwell.py`
- [x] CAM3 uses `PROCESS_EVERY_N_FRAMES` from `config.py` in `entry_exit.py`
- [x] CAM5 uses `PROCESS_EVERY_N_FRAMES` from `config.py` in `queue.py` *(deduplicated)*
- [x] CAM4 — no processor; documented for future implementation
- [x] Progress logging every 100 original video frames on all active processors
- [x] Event semantics unchanged — only inference frequency standardized

---

## 7. Future CAM4 implementation note

When implementing `process_cam4_video()`, follow the same pattern:

```python
from pipeline.config import PROCESS_EVERY_N_FRAMES, PROGRESS_LOG_EVERY_N_FRAMES

if original_frame % PROCESS_EVERY_N_FRAMES != 0:
    original_frame += 1
    continue

detections = detect_persons(frame, yolo_model)
# staff crop / is_staff flag logic on sampled frames only
```

Use the real `original_frame` index for any timestamp or crop naming to preserve temporal alignment with other cameras.
