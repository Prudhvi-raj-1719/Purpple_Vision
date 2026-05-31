# CAM3 Performance Report — Inference Frequency Alignment

**Date:** 2026-05-30  
**Scope:** `pipeline/entry_exit.py` vs `pipeline/cam1_processor.py` / `pipeline/cam2_processor.py`  
**Change:** Align YOLO inference stride only — ENTRY/EXIT logic unchanged.

---

## 1. Frame processing strategy comparison

| Aspect | CAM1 / CAM2 | CAM3 (before) | CAM3 (after) |
|--------|-------------|---------------|--------------|
| Entry module | `cam1_processor.py` / `cam2_processor.py` | `entry_exit.py` | `entry_exit.py` |
| Shared loop | `dwell.process_zone_engagement_video()` | Inline loop in `process_cam3_video()` | Inline loop in `process_cam3_video()` |
| `PROCESS_EVERY_N_FRAMES` | **Yes** — imported from `config.py` (default **10**) | **No** — not used | **Yes** — same constant from `config.py` |
| Frame skipping | Skips YOLO/ByteTrack when `frame % 10 != 0` | Runs YOLO on **every** frame | Skips YOLO/ByteTrack when `frame % 10 != 0` |
| Video read | Every frame still decoded | Every frame decoded | Every frame decoded (same as CAM1/CAM2) |
| Analytics on skip | No zone update | N/A | No entry/exit update (same sampling tradeoff as CAM1/CAM2) |
| Progress logging | Minimal completion log | Every 100 frames (`frame/total`) | Every 100 frames: `frame`, `processed`, `% complete` |

### CAM1/CAM2 skip logic (reference)

```python
# pipeline/dwell.py
if original_frame % process_every_n != 0:
    original_frame += 1
    del frame
    continue

detections = detect_persons(frame, yolo_model)
```

### CAM3 original behavior

```python
# pipeline/entry_exit.py (before)
detections = detect_persons(frame, yolo_model)  # every frame, no skip guard
```

### CAM3 optimized behavior

```python
# pipeline/entry_exit.py (after)
if frame_idx % PROCESS_EVERY_N_FRAMES != 0:
    frame_idx += 1
    del frame
    continue

detections = detect_persons(frame, yolo_model)
```

---

## 2. Verification — CAM3 processed every frame

**Confirmed.** Before this change, `process_cam3_video()` called `detect_persons()` → `yolo_model.predict()` once per decoded frame with no modulo guard. CAM1/CAM2 only invoked inference on frames 0, 10, 20, … (10% of frames).

At 1535×864 and ~30 fps, a typical 30-minute CAM3 clip (~54,000 frames) triggered **~54,000 YOLO inferences** vs **~5,400** for CAM1/CAM2 on the same length clip.

---

## 3. Change applied

**File:** `pipeline/entry_exit.py`

- Import `PROCESS_EVERY_N_FRAMES` from `pipeline.config` (value **10**, shared with CAM1/CAM2).
- Skip inference/tracking/entry-exit update on non-sample frames (identical guard pattern to `dwell.py`).
- Pass the real video `frame_idx` into `EntryExitCounter.process_detections()` on sampled frames only — **ENTRY/EXIT transition logic untouched**.
- Logging additions:
  - Startup: `CAM3 inference stride: every 10 frames (same as CAM1/CAM2)`
  - Progress (every 100 video frames): `frame`, `processed`, `% complete`, entry/exit counts, last YOLO ms
  - Completion: total frames, processed count, percent, inference stride

---

## 4. Estimated speedup

Assumptions (typical YOLO11m on 1535×864 CPU/GPU mix):

| Phase | Per-frame cost (approx.) |
|-------|--------------------------|
| `capture.read()` | ~2–8 ms |
| `yolo_model.predict()` | ~150–400 ms |
| ByteTrack + doorway check | ~1–5 ms |

### Inference-only speedup

| Metric | Original | Optimized |
|--------|----------|-----------|
| YOLO calls per 10,000 video frames | 10,000 | 1,000 |
| **Inference speedup** | 1× | **~10×** |

### End-to-end clip speedup (model-bound workload)

When YOLO dominates total time (matches observed hang in `predict()`):

```
T_original  ≈ N × (T_read + T_yolo + T_track)
T_optimized ≈ N × T_read + (N/10) × (T_yolo + T_track)
```

Example with N = 54,000 frames, T_read = 5 ms, T_yolo = 250 ms, T_track = 3 ms:

| | Wall time |
|--|-----------|
| **Original** | 54,000 × 258 ms ≈ **3.9 hours** |
| **Optimized** | 54,000 × 5 ms + 5,400 × 253 ms ≈ **38 min** |
| **Estimated end-to-end speedup** | **~6×** |

Speedup approaches the full **10×** ceiling when `T_yolo >> T_read`. If decode/I/O is heavy, observed gain will be lower but still substantial.

---

## 5. Tradeoffs (unchanged from CAM1/CAM2 policy)

- Doorway state is evaluated every 10 frames, not every frame. A person crossing the entry polygon between sample frames may be detected one sample later — same temporal resolution as zone engagement on CAM1/CAM2.
- ByteTrack still receives detections at the reduced rate; track continuity relies on the same stride as shelf cameras.
- **ENTRY/EXIT event rules** (`OUTSIDE_DOORWAY` → `INSIDE_DOORWAY`, etc.) are unchanged; only input frequency matches CAM1/CAM2.

---

## 6. Recommended validation

1. Re-run CAM3 on a short clip; confirm `[PROGRESS] frame=… processed=…` shows `processed ≈ frame / 10`.
2. Compare entry/exit counts on a 5-minute segment before vs after — expect small drift from sampling, same class of error as CAM1/CAM2 zone timing.
3. If crossings are missed on fast walk-throughs, tune `PROCESS_EVERY_N_FRAMES` globally in `config.py` (affects all cameras consistently).
